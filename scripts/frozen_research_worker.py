"""Container-only research: frozen inputs -> model -> daily replay -> controls."""
from __future__ import annotations

from datetime import timedelta
import importlib.metadata
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import qlib
from qlib.backtest import backtest
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy, WeightStrategyBase
from qlib.data import D

import train
from backend.services.engine.data_platform.quantdb_factor_reader import QuantDBFactorReader
from backend.services.engine.qlib_app.utils.cn_exchange import CnExchange
from backend.shared.stock_utils import StockCodeUtil

FROZEN = Path("/frozen")
OUT = Path("/output")


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def choose_universe(frame, cutoff, spec):
    history = frame[(frame["trade_date"] <= pd.Timestamp(cutoff)) & (frame["volume"] > 0)]
    dates = sorted(history["trade_date"].unique())[-spec["liquidity_days"]:]
    history = history[history["trade_date"].isin(dates)]
    table = history.groupby("symbol")["amount"].agg(["median", "count"])
    table = table[(table["count"] >= spec["min_observations"]) & (table["median"] > 0)]
    table = table.reset_index().sort_values(["median", "symbol"], ascending=[False, True])
    table = table.head(spec["size"])
    if len(table) != spec["size"]:
        raise RuntimeError(f"Insufficient training-period universe coverage: {len(table)} / {spec['size']}")
    return table


def eligible(frame, universe, features, single_factor):
    frame = frame[frame["symbol"].isin(universe) & (frame["volume"] > 0)].copy()
    frame[features] = frame[features].replace([np.inf, -np.inf], np.nan)
    return frame[frame[single_factor].notna()].sort_values(["trade_date", "symbol"])


class EqualWeight(WeightStrategyBase):
    """Daily target weights over the same available universe as both rankings."""
    def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
        names = score.dropna().index
        return {symbol: 1 / len(names) for symbol in names} if len(names) else {}


class RecordingExchange(CnExchange):
    """Keep the existing execution and fee logic; record actual fills locally."""
    def __init__(self, **kwargs):
        self.fills = []
        super().__init__(backtest_id=None, **kwargs)

    def deal_order(self, order, trade_account=None, **kwargs):
        value, cost, price = super().deal_order(order, trade_account=trade_account, **kwargs)
        # Strategy order previews use a copied position, not a trading account.
        if trade_account is not None and value > 0:
            position = trade_account.current_position
            self.fills.append({
                "date": order.start_time.strftime("%Y-%m-%d"),
                "symbol": str(order.stock_id),
                "action": "buy" if int(order.direction) == 1 else "sell",
                "adjusted_quantity": float(order.deal_amount),
                "adjusted_price": float(price), "amount": float(value),
                "cost": float(cost), "cash_after": float(position.get_cash()),
            })
        return value, cost, price


def check_account(report, positions, fills, capital):
    if report.empty or not fills:
        raise RuntimeError("Empty portfolio or no actual fills")
    nav = report["account"].astype(float)
    if not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError("Invalid account values")
    previous = nav.shift(1).fillna(capital)
    net = nav / previous - 1
    if not np.allclose(net, report["return"] - report["cost"], atol=1e-8):
        raise RuntimeError("Daily net returns do not reconcile")
    cash = capital
    cash_error = 0.0
    for fill in fills:
        cash += (1 if fill["action"] == "sell" else -1) * fill["amount"] - fill["cost"]
        cash_error = max(cash_error, abs(cash - fill["cash_after"]))
        if cash < -0.01:
            raise RuntimeError("Negative cash in unlevered portfolio")
    final_position = positions[max(positions)]
    if cash_error > 0.01 or abs(cash - final_position.get_cash()) > 0.01:
        raise RuntimeError("Trade cash ledger does not reconcile")
    fees = sum(fill["cost"] for fill in fills)
    if abs(fees - float((report["cost"] * previous).sum())) > 0.01:
        raise RuntimeError("Recorded fees do not match account fees")
    if set(positions) != set(report.index):
        raise RuntimeError("Missing daily position snapshots")
    account_error = 0.0
    for day, position in positions.items():
        marked_value = position.get_cash() + sum(
            position.get_stock_amount(symbol) * position.get_stock_price(symbol)
            for symbol in position.get_stock_list())
        account_error = max(account_error, abs(marked_value - float(report.loc[day, "account"])))
    if account_error > 0.01:
        raise RuntimeError("Daily positions and cash do not match reported equity")
    expanded = np.r_[capital, nav.to_numpy()]
    drawdown = expanded / np.maximum.accumulate(expanded) - 1
    volatility = net.std(ddof=1)
    return {"total_return": float(nav.iloc[-1] / capital - 1),
            "max_drawdown": float(drawdown.min()), "trades": len(fills),
            "transaction_cost": float(fees), "cash_error": float(cash_error),
            "account_error": float(account_error),
            "sharpe": float((net.mean() - 0.02 / 252) / volatility * np.sqrt(252)) if volatility else None,
            "trading_days": len(report), "final_value": float(nav.iloc[-1])}


def run_portfolio(name, score, cfg, universe):
    portfolio = cfg["portfolio"]
    start, end = cfg["split"]["test"]
    exchange = RecordingExchange(freq="day", start_time=start, end_time=end,
                                 codes=universe, **cfg["exchange"])
    common = {"signal": score, "risk_degree": portfolio["risk_degree"]}
    if name == "equal_weight":
        strategy = EqualWeight(**common)
    else:
        strategy = TopkDropoutStrategy(**common, topk=portfolio["topk"],
                                      n_drop=portfolio["n_drop"], hold_thresh=1,
                                      only_tradable=True)
    result, _ = backtest(
        start_time=start, end_time=end, strategy=strategy,
        executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                  "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}},
        account=portfolio["initial_capital"], benchmark=portfolio["benchmark"],
        exchange_kwargs={"exchange": exchange},
    )
    report, positions = result["1day"]
    report.to_csv(OUT / f"{name}-equity.csv", index_label="date")
    pd.DataFrame(exchange.fills).to_csv(OUT / f"{name}-trades.csv", index=False)
    holdings = []
    for day, position in positions.items():
        for symbol in sorted(position.get_stock_list()):
            holdings.append({"date": str(day.date()), "symbol": symbol,
                             "adjusted_quantity": position.get_stock_amount(symbol),
                             "adjusted_price": position.get_stock_price(symbol)})
    pd.DataFrame(holdings).to_csv(OUT / f"{name}-positions.csv", index=False)
    metrics = check_account(report, positions, exchange.fills, portfolio["initial_capital"])
    metrics["native_benchmark_return"] = float((1 + report["bench"]).prod() - 1)
    # Portfolios start in cash and buy at the first close. Exclude the index
    # return from the previous close to that first close for a comparable start.
    metrics["benchmark_return"] = float((1 + report["bench"].iloc[1:]).prod() - 1)
    return metrics


def main():
    if not Path(train.__file__).resolve().is_relative_to(FROZEN / "code"):
        raise RuntimeError("Training module was imported outside the frozen code tree")
    cfg = json.loads((FROZEN / "config.json").read_text())
    features = cfg["features"]
    derived = cfg.get("derived_factor")
    source_features = cfg.get("source_features", features) if derived else features
    source = cfg["factor_source"]
    factor = cfg["portfolio"]["single_factor"]
    write("runtime.json", {"packages": {name: importlib.metadata.version(name) for name in
          ("numpy", "pandas", "lightgbm", "pyqlib", "duckdb", "pyarrow")},
          "training_code": str(Path(train.__file__).resolve()),
          "factor_root": "/frozen/quantdb", "provider": "/frozen/qlib",
          "network": "none", "signal_lag": "Qlib strategy reads previous trading day; no extra shift"})
    qlib.init(provider_uri="/frozen/qlib", region="cn", kernels=1,
              expression_cache=None, dataset_cache=None,
              exp_manager={"class": "MLflowExpManager", "module_path": "qlib.workflow.expm",
                           "kwargs": {"uri": "file:/tmp/mlruns", "default_exp_name": "research"}})
    reader = QuantDBFactorReader("/frozen/quantdb", market="CN")
    train_start, train_end = cfg["split"]["train"]
    test_start, test_end = cfg["split"]["test"]
    liquidity_start = (pd.Timestamp(train_end) - timedelta(days=180)).date().isoformat()
    history = reader.read_range(source, features=source_features, start=liquidity_start, end=train_end)
    available = {StockCodeUtil.to_prefix(symbol) for symbol in D.list_instruments(
        D.instruments("all"), start_time=liquidity_start, end_time=train_end, as_list=True)}
    # Keep main-board names only: the inherited 9.5% limit approximation is not
    # suitable for STAR/ChiNext/BJ; historical ST rules still need separate work.
    history = history[history["symbol"].isin(available) & history["symbol"].str.match(r"^(SH60|SZ00)")]
    pool = choose_universe(history, train_end, cfg["universe"])
    pool.to_csv(OUT / "universe.csv", index=False)
    universe = pool["symbol"].tolist()
    print("Universe selected using training history:", len(universe), flush=True)
    del history
    frame, actual_features = train.load_data(
        train_start, train_end, source_features, target_horizon_days=1,
        valid_end=cfg["split"]["valid"][1], test_end=test_end,
        local_dir="/frozen/quantdb", quantdb_dir="/frozen/quantdb", factor_source=source)
    if actual_features != source_features:
        raise RuntimeError("Training silently changed requested features")
    frame = frame[frame["symbol"].isin(universe)].copy()
    raw_factor = None
    if derived:
        from research_expression import diagnostics, evaluate, validate

        validate(derived["expression"], source_features)
        if derived["name"] != "research_signal" or features != source_features + [derived["name"]]:
            raise ValueError("Derived factor must augment the frozen baseline once")
        raw_factor = reader.read_range(source, features=source_features,
            start=train_start, end=test_end)
        raw_factor = raw_factor[raw_factor.symbol.isin(universe)].copy()
        trading_calendar = D.calendar(start_time=raw_factor.trade_date.min(), end_time=test_end, freq="day")
        raw_factor = raw_factor[raw_factor.trade_date.isin(trading_calendar)].sort_values(["symbol", "trade_date"])
        raw_factor[derived["name"]] = evaluate(raw_factor, derived["expression"], source_features)
        grouped = raw_factor.groupby("symbol")
        raw_factor["forward_return"] = grouped.close.shift(-2) / grouped.close.shift(-1) - 1
        raw_factor["label_end"] = grouped.trade_date.shift(-2)
        frame = frame.merge(raw_factor[["symbol", "trade_date", derived["name"]]],
                            on=["symbol", "trade_date"], validate="one_to_one")
        values = raw_factor[["symbol", "trade_date", derived["name"], "forward_return", "label_end"]]
        values.to_parquet(OUT / "factor-values.parquet", index=False)
        analysis = diagnostics(raw_factor, derived["name"], source_features, cfg)
        analysis["history_start"] = str(raw_factor.trade_date.min().date())
        analysis["required_history_observations"] = validate(derived["expression"], source_features)["lookback"]
        analysis["warmup_note"] = "Snapshot begins at train_start; unavailable initial rolling values remain missing and are included in coverage."
        write("factor-analysis.json", analysis)
        write("factor-definition.json", derived)
        if frame[derived["name"]].notna().mean() < .5 or frame[derived["name"]].nunique() < 2:
            raise ValueError("Generated factor has insufficient coverage or is constant")
    frame[features] = frame[features].replace([np.inf, -np.inf], np.nan)
    fit, valid, test = train._split_data(frame, cfg)
    model_result = train._train_single_model("lightgbm", fit, valid, test, frame,
                                           features, cfg, need_full_pred=False)
    model_result["model"].save_model(str(OUT / "model.lgb"))
    write("model-metadata.json", {"features": features, "fill_values": model_result["fill_values"],
          "training_metrics": model_result["train_m"], "validation_metrics": model_result["val_m"],
          "test_metrics": model_result["test_m"], "best_iteration": model_result["best_iteration"],
          "fit_rows": len(fit), "validation_rows": len(valid), "test_rows": len(test)})
    calendar = pd.DatetimeIndex(D.calendar(start_time=pd.Timestamp(test_start) - timedelta(days=30),
                                         end_time=test_end, freq="day"))
    previous_day = calendar[calendar < pd.Timestamp(test_start)][-1]
    signal_days = calendar[(calendar >= previous_day) & (calendar < pd.Timestamp(test_end))]
    batch = (raw_factor.copy() if derived else
             reader.read_range(source, features=features, start=str(previous_day.date()), end=test_end))
    batch = eligible(batch, universe, features, factor)
    batch = batch[batch["trade_date"].isin(signal_days)].copy()
    model = lgb.Booster(model_file=str(OUT / "model.lgb"))

    def predict(data):
        x = data[features].astype("float32").fillna(model_result["fill_values"])
        return model.predict(x.to_numpy(dtype=np.float32), num_threads=4)

    batch["model"] = predict(batch)
    replay = []
    for index, day in enumerate(signal_days, 1):
        if derived:
            # Recompute from a prefix containing no rows after today's observation.
            prefix = raw_factor[raw_factor.trade_date <= day].copy()
            prefix[derived["name"]] = evaluate(prefix, derived["expression"], source_features)
            daily = eligible(prefix[prefix.trade_date == day], universe, features, factor)
        else:
            daily = eligible(reader.read_day(source, features=features, trade_date=str(day.date())),
                             universe, features, factor)
        daily["score"] = predict(daily)
        replay.append(daily[["trade_date", "symbol", "score"]])
        if index % 10 == 0:
            print(f"Daily replay: {index}/{len(signal_days)}", flush=True)
    replay = pd.concat(replay, ignore_index=True)
    replay.to_parquet(OUT / "daily-replay.parquet", index=False)
    joined = batch.merge(replay, on=["trade_date", "symbol"], validate="one_to_one")
    error = float(np.max(np.abs(joined["model"] - joined["score"])))
    if len(joined) != len(batch) or len(joined) != len(replay) or error > 1e-10:
        raise RuntimeError("Daily independent inference differs from batch predictions")
    if set(batch["trade_date"]) != set(signal_days) or not np.isfinite(batch["model"]).all():
        raise RuntimeError("Missing or non-finite signals in test replay")
    batch["single_factor"] = batch[factor]
    batch["equal_weight"] = 1.0
    scores = batch.set_index(["trade_date", "symbol"])[["model", "single_factor", "equal_weight"]]
    scores.index.names = ["datetime", "instrument"]
    scores = scores.sort_index()
    scores.to_parquet(OUT / "signals.parquet")
    print("Daily inference verified:", len(signal_days), "days; max difference", error, flush=True)
    comparisons = {}
    for name in scores:
        print("Backtesting", name, flush=True)
        comparisons[name] = run_portfolio(name, scores[name], cfg, universe)
        write("comparison-progress.json", comparisons)
    improvement = comparisons["model"]["total_return"] - comparisons["single_factor"]["total_return"]
    summary = {"checks_passed": True, "research_status": "needs_validation",
               "purpose": cfg["purpose"], "comparison": comparisons,
               "model_minus_single_factor_pp": improvement * 100,
               "replay_days": len(signal_days), "replay_rows": len(replay), "replay_max_error": error,
               "limitations": ["Previously inspected development interval; no final holdout claim",
                               "Inherited CnExchange quote fallback and historical limit/ST rules remain unaudited",
                               "Frozen files do not prove original factors were point-in-time correct",
                               "Equal weight holds the whole pool; Top20 controls match each other more closely",
                               "Standalone research results are not registered in the platform database"]}
    write("summary.json", summary)
    rows = "\n".join(f"| {name} | {m['total_return']:.2%} | {m['max_drawdown']:.2%} | {m['trades']} | {m['transaction_cost']:,.2f} |"
                     for name, m in comparisons.items())
    (OUT / "README.md").write_text(f"""# 冻结输入与自动对照实验

数据、代码、配置和容器镜像在执行前固定。容器只读挂载快照、关闭网络，研究结果写入独立目录。

股票池：训练结束前{cfg['universe']['liquidity_days']}个交易日成交额中位数最高的{len(universe)}只主板股票，至少{cfg['universe']['min_observations']}日有效记录；同一股票池用于三组策略。
资金{cfg['portfolio']['initial_capital']:,.0f}元，目标总仓位{cfg['portfolio']['risk_degree']:.0%}，每日决策、次交易日{cfg['exchange']['deal_price']}成交。模型与单因子{factor}均为Top{cfg['portfolio']['topk']}、n_drop={cfg['portfolio']['n_drop']}；等权对照覆盖整个可用股票池。

| 策略 | 净收益 | 最大回撤 | 成交笔数 | 费用（元） |
| --- | --- | --- | --- | --- |
{rows}

模型相对单因子收益差：{improvement * 100:+.2f}个百分点。研究状态：需要进一步验证。
指数从首笔建仓日收盘至期末的收益为{comparisons['model']['benchmark_return']:.2%}；Qlib原生口径包含此前一晚涨跌，保留为 `native_benchmark_return`，不与组合收益混用。
历史逐日推理重放覆盖{len(signal_days)}个信号日、{len(replay)}条评分；与批量预测最大差{error}。
三组均通过逐笔现金、逐日收益和总费用核对；各组 `*-equity.csv`、`*-trades.csv`、`*-positions.csv` 保留完整记录。

查看 `summary.json`、`model-metadata.json`、`universe.csv`、`signals.parquet`、`daily-replay.parquet` 和 `runtime.json`。
本区间已被用于研究，不能作为最终样本外检验。本次直接复用训练函数、Qlib策略和CnExchange，不写入平台模型或回测数据库。
现有报价回退、历史ST与涨跌停规则、原始因子PIT正确性仍需独立审计；快照和同口径对照不能消除这些限制。
""")


if __name__ == "__main__":
    main()
