"""运行 I1–I7 固定变体、IS 选参、容量重跑及报告。"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
from statistics import NormalDist
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ashare-ideas-mpl")
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pyarrow as pa

from ashare_lab import metrics
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.ideas_calendar import calendar_holdings, calendar_nav
from ashare_lab.pbo import cscv_pbo
from ashare_lab.strategies.factor_topn import FactorTopN
from experiments.expansion.common import PERIODS, bootstrap_mdd, metrics_table, plot_nav

START, END = "2012-01-01", "2026-09-30"
OUT = Path("reports/ideas")
DATA = None
INDUSTRY = None
CONFIGS = {
    "I1": [(f"momentum_J{j}", dict(factor="ret", lookback=j, skip=21)) for j in (63, 126, 252)],
    "I2": [("reversal_J5_week", dict(factor="ret", lookback=5, highest=False, rebalance="week_end")),
           ("reversal_J21_month", dict(factor="ret", lookback=21, highest=False))],
    "I3": [(f"smallcap_N{n}", dict(factor="total_mv", highest=False, top_n=n,
                                   universe="all", min_amount=3e7)) for n in (50, 100)],
    "I4": [(f"moneyflow_{side}", dict(factor="moneyflow", highest=side == "high"))
           for side in ("high", "low")],
    "I5": [("dividend100_lowvol250_N50", dict(factor="div_lowvol"))],
    "I6": [(f"industry_J{j}_K3", dict(factor="industry_ret", lookback=j)) for j in (21, 63, 126)],
}
DOUBTS = [
    "指定总验收在收集 tests/test_ideas_cb.py、tests/test_ideas_cta.py 时失败："
    "缺少 ashare_lab.ideas_cb、ashare_lab.ideas_cta；它们属于 I8/I9，且不在本单允许新建或修改的路径内。"
    "不改 tests、不扩大忽略列表、不创建越界实现；总验收无法在本单范围内通过。",
    "DSR 预登记 K=23，但本单只有 I1–I7 的 17 个变体；I8/I9 的 6 个夏普不可用。"
    "报告 K=23、可用 17 个变体的样本夏普方差得到的暂定 DSR，不能冒充完整 23 变体的 DSR；"
    "另列 K=17 敏感性结果。DSR 不参与五条通过规则。",
    "收益窗口的有效收盘计数取 (t-skip-J, t-skip] 的 J 行，另要求起止两端均有效。",
    "I6 行业参与门槛按可选股票数至少 5 只；行业分只平均有有效收益分数者，"
    "持仓覆盖入选行业全部可选股票；未分类股票不视作行业。",
    "I7 月份及节前日期仅使用上交所交易日历，不使用未来价格；区间末无下一开盘的隔夜交易不发起，"
    "收盘规则区间末按收盘卖出计费；上市前不能建立仓位。",
    "I7 的交易价格仍按 panel/calendar 对齐；规则计算补充只读归档 SSE 的已公布交易日历至 2026-10，"
    "以识别区间末国庆前的节前信号（不用区间后的价格）。",
    "I7 单边换手按交易边数/2（一次完整进出为 1）除以 252 交易日年数；买入持有亦计入进出成本。",
    "规则 2 的纯低波基准保持其 2012–2026 全区间，与共同口径一致，I7 虽始于上市日也不缩短该基准。",
]


def execute(task):
    idea, name, params, capacity = task
    started = time.monotonic()
    params = dict(params)
    if params["factor"] == "industry_ret":
        params["industry_table"] = INDUSTRY
    strategy = FactorTopN(**params)
    costs = CostModel(impact_k=1, max_participation=0.1) if capacity else CostModel()
    cash = 1e8 if capacity else 1e7
    result = run_backtest(strategy, DATA, BacktestConfig(START, END, cash, costs))
    turns = {}
    for period, (start, end) in PERIODS.items():
        nav = result.nav.loc[start:end]
        trades = result.trades[(result.trades.date >= pd.Timestamp(start)) &
                               (result.trades.date <= pd.Timestamp(end))]
        sliced = replace(result, nav=nav, trades=trades, exposure=result.exposure.loc[start:end])
        turns[period] = metrics.summary(sliced)["turnover"]
    meta = {"name": name, "parameters": {k: v for k, v in params.items() if k != "industry_table"},
            "turnover": turns, "initial_cash": cash, "impact_k": costs.impact_k,
            "max_participation": costs.max_participation,
            "is_calmar": metrics.calmar(result.nav.loc[:"2019-12-31"]),
            "full_cagr": metrics.cagr(result.nav), "seconds": time.monotonic() - started}
    print(f"完成 {idea}/{name}{' capacity' if capacity else ''}: {meta['seconds']:.1f}s", flush=True)
    return idea, name, capacity, result.nav / cash, meta


def save_result(item):
    idea, name, capacity, nav, meta = item
    folder = OUT / idea
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "capacity" if capacity else name
    nav.rename(name).to_frame().to_parquet(folder / f"{suffix}.parquet")
    (folder / f"{suffix}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def run_stocks(group, workers):
    global DATA, INDUSTRY
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    small = group == "small"
    print(f"加载 {'全 A' if small else '中证 800'}面板", flush=True)
    DATA = load_market_data("data/panel", "2010-01-01", END,
                            universe=None if small else "000906.SH")
    # 本组不用的 basic 宽表及时释放，减小 fork 的内存占用。
    needed = {"total_mv"} if small else {"dv_ttm"}
    DATA.extra = {key: value for key, value in DATA.extra.items() if key in needed}
    if not small:
        flow = pd.read_parquet("data/ideas/moneyflow.parquet",
                               filters=[("code", "in", DATA.close.columns.tolist())])
        flow["date"] = pd.to_datetime(flow.date)
        DATA.extra["net_mf_amount"] = flow.pivot(index="date", columns="code", values="net_mf_amount").reindex(
            index=DATA.calendar, columns=DATA.close.columns)
        del flow
        INDUSTRY = pd.read_parquet("data/panel/industry.parquet")
    ideas = ["I3"] if small else ["I1", "I2", "I4", "I5", "I6"]
    tasks = [(idea, name, params, False) for idea in ideas for name, params in CONFIGS[idea]]
    context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks), 6), mp_context=context) as pool:
        results = list(pool.map(execute, tasks))
        for item in results:
            save_result(item)
        candidates = []
        for idea in ideas:
            choices = [item for item in results if item[0] == idea]
            # 原配置顺序打破平手；选择只读取 IS Calmar。
            winner = max(choices, key=lambda item: item[4]["is_calmar"]
                         if np.isfinite(item[4]["is_calmar"]) else -np.inf)
            name = winner[1]
            params = dict(CONFIGS[idea])[name]
            candidates.append((idea, name, params, True))
        for item in pool.map(execute, candidates):
            save_result(item)


def run_calendar():
    full_calendar = pd.DatetimeIndex(pd.to_datetime(pd.read_parquet("data/panel/calendar.parquet").date))
    calendar = full_calendar[(full_calendar >= "2012-05-28") & (full_calendar <= END)]
    announced = pd.read_parquet("data/ideas/calendar.parquet")
    extra_days = pd.DatetimeIndex(pd.to_datetime(announced.loc[announced.is_open == 1, "date"]))
    signal_calendar = full_calendar.union(extra_days[extra_days > END]).sort_values()
    daily = pd.read_parquet("data/ideas/510300_fund_daily.parquet").set_index("date")
    adj = pd.read_parquet("data/ideas/510300_fund_adj.parquet").set_index("date").adj_factor
    daily.index = pd.DatetimeIndex(daily.index)
    adj.index = pd.DatetimeIndex(adj.index)
    factor = adj.reindex(full_calendar).ffill().reindex(calendar)
    close = daily.close.reindex(full_calendar).ffill().reindex(calendar) * factor
    # 缺口交易日收益为零；缺少开盘时沿用前一个收盘，不使用当天收盘替代开盘。
    open_ = daily.open.reindex(calendar).fillna(daily.close.reindex(full_calendar).ffill().shift().reindex(calendar)) * factor
    missing = daily.reindex(calendar)[["open", "close"]].isna().sum().to_dict()
    frame, turns = {}, {}
    for name in ("tom", "preholiday", "union", "overnight", "buy_hold_510300"):
        overnight = name == "overnight"
        if name == "buy_hold_510300":
            hold = pd.Series(True, index=calendar)
        elif overnight:
            hold = None
        else:
            hold = calendar_holdings(signal_calendar, name).reindex(calendar)
        frame[name] = calendar_nav(open_, close, hold, overnight=overnight)
        edges = pd.Series(0.0, index=calendar)
        if overnight:
            # 每个可观察的隔夜区间，两条交易边各记半次换仓。
            edges.iloc[:-1] += 0.5
            edges.iloc[1:] += 0.5
        else:
            held = hold.copy()
            held.iloc[0] = False
            edges = (held != held.shift(-1, fill_value=False)).astype(float) / 2
        turns[name] = {}
        for period, (start, end) in PERIODS.items():
            days = frame[name].loc[start:end]
            turns[name][period] = float(edges.loc[start:end].sum() * 252 / (len(days) - 1))
    folder = OUT / "I7"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(frame).to_parquet(folder / "nav.parquet")
    (folder / "calendar.json").write_text(json.dumps({"turnover": turns, "missing": missing}, indent=2) + "\n")
    print(f"完成 I7: {len(calendar)} 个交易日，原始价格缺口 {missing}", flush=True)


def deflated_sharpe(nav, variance_ann, trials):
    """Bailey & López de Prado 2014, Eq. 10; 全部 SR 先统一为日频。

    https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
    """
    normal = NormalDist()
    euler = 0.5772156649015329
    threshold_ann = np.sqrt(variance_ann) * ((1 - euler) * normal.inv_cdf(1 - 1 / trials)
                    + euler * normal.inv_cdf(1 - 1 / (trials * np.e)))
    r = nav.pct_change(fill_method=None).dropna()
    sr = r.mean() / r.std(ddof=1)
    skew, kurtosis = r.skew(), r.kurt() + 3
    denominator = np.sqrt(1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2)
    probability = normal.cdf((sr - threshold_ann / np.sqrt(252)) * np.sqrt(len(r) - 1) / denominator)
    return {"dsr": probability, "trials": trials, "sharpe_variance_ann": variance_ann,
            "threshold_sharpe_ann": threshold_ann, "skew": skew, "kurtosis": kurtosis,
            "n_returns": len(r)}


def write_reports():
    benchmarks = load_benchmarks("data/benchmarks")
    lowvol = pd.read_parquet("reports/b3_full/nav.parquet")["lowvol_W250_N50"].loc[START:END]
    ref_boot = bootstrap_mdd(lowvol.to_frame()).iloc[0]
    ref_mdd = metrics.max_drawdown(lowvol)
    all_navs, metadata = {}, {}
    for idea, configs in CONFIGS.items():
        folder = OUT / idea
        all_navs[idea] = pd.concat([pd.read_parquet(folder / f"{name}.parquet")[name]
                                    for name, _ in configs], axis=1)
        metadata[idea] = {name: json.loads((folder / f"{name}.json").read_text()) for name, _ in configs}
    all_navs["I7"] = pd.read_parquet(OUT / "I7/nav.parquet")
    variants = [(idea, name) for idea, frame in all_navs.items() for name in frame
                if name != "buy_hold_510300"]
    sharpe_values = [metrics.sharpe(all_navs[idea][name]) for idea, name in variants]
    variance = float(np.var(sharpe_values, ddof=1))
    pd.DataFrame({"idea": [i for i, _ in variants], "name": [n for _, n in variants],
                  "full_sharpe": sharpe_values}).to_csv(OUT / "all_variant_sharpes.csv", index=False)
    overview = []
    for idea, nav in all_navs.items():
        folder = OUT / idea
        table = metrics_table(nav, benchmarks, lowvol).merge(bootstrap_mdd(nav), on="name")
        if idea == "I7":
            turns = json.loads((folder / "calendar.json").read_text())["turnover"]
        else:
            turns = {name: meta["turnover"] for name, meta in metadata[idea].items()}
        table["turnover"] = [turns[row["name"]][row["period"]] for _, row in table.iterrows()]
        eligible_is = table[(table.period == "IS") & (table.name != "buy_hold_510300")]
        winner = eligible_is.sort_values("calmar", ascending=False, kind="stable").iloc[0]["name"]
        rows = table[table.name == winner].set_index("period")
        full = rows.loc["FULL"]
        dsr = deflated_sharpe(nav[winner], variance, 23)
        dsr17 = deflated_sharpe(nav[winner], variance, len(variants))
        table["candidate"] = table.name == winner
        table.to_csv(folder / "summary.csv", index=False)
        nav.to_parquet(folder / "nav.parquet")
        pd.DataFrame({name: metrics.annual_returns(nav[name].dropna()) for name in nav}).to_csv(folder / "annual.csv")
        comparison = nav.copy()
        comparison["lowvol_W250_N50"] = lowvol.reindex(nav.index)
        for code in benchmarks:
            comparison[code] = benchmarks[code].reindex(nav.index)
        plot_nav(comparison, folder / "nav.png", f"{idea} 固定变体与参照")
        checks = [bool(rows.loc["IS", "alpha_000906.SH_TR"] > 0 and rows.loc["OOS", "alpha_000906.SH_TR"] > 0),
                  bool(full.mdd_p05 >= ref_boot.mdd_p05 and full.max_drawdown >= ref_mdd),
                  bool(full.corr_lowvol < 0.5)]
        pbo = None
        if idea == "I7":
            evaluated = nav.drop(columns="buy_hold_510300").pct_change(fill_method=None).dropna()
            result = cscv_pbo(evaluated, n_blocks=16)
            pbo = result["pbo"]
            pd.DataFrame({"logit": result["logits"], "selected": result["selected"],
                          "is_sharpe": result["is_metric"], "oos_sharpe": result["oos_metric"]}).to_csv(
                              folder / "pbo.csv", index=False)
            checks.append(bool(pbo <= 0.3))
            capacity_line = "5. 通过（不适用）：ETF 无冲击，不适用；冲击增量按 0，未执行引擎容量回测。"
            checks.append(True)
        else:
            checks.append(True)
            capacity_meta = json.loads((folder / "capacity.json").read_text())
            if capacity_meta["name"] != winner:
                raise ValueError(f"{idea}: 容量候选与 IS 候选不一致")
            capacity = pd.read_parquet(folder / "capacity.parquet")[winner]
            capacity_table = metrics_table(capacity.to_frame(), benchmarks, lowvol).merge(
                bootstrap_mdd(capacity.to_frame()), on="name")
            capacity_table["turnover"] = capacity_table.period.map(capacity_meta["turnover"])
            capacity_table.to_csv(folder / "capacity_summary.csv", index=False)
            decrease = metrics.cagr(nav[winner]) - metrics.cagr(capacity)
            checks.append(bool(decrease < 0.01))
            capacity_line = (f"5. {'通过' if checks[-1] else '不通过'}：全区间 1e7 默认成本 CAGR={metrics.cagr(nav[winner]):.4%}，"
                             f"1e8/k=1/参与率≤10% CAGR={metrics.cagr(capacity):.4%}；下降={decrease:.4%}，要求 <1.0000%。")
        status = lambda value: "通过" if value else "不通过"
        text = [f"# {idea} 验证结论", "",
                f"候选：`{winner}`，仅按 IS Calmar={rows.loc['IS', 'calmar']:.6f} 最高选定（平手按预登记顺序）。",
                "股票全区间一次回测，IS/OOS 为同一净值切片；I7 从 2012-05-28 上市起。", "",
                f"1. {status(checks[0])}：相对 000906.SH_TR，IS α={rows.loc['IS', 'alpha_000906.SH_TR']:.4%}，"
                f"OOS α={rows.loc['OOS', 'alpha_000906.SH_TR']:.4%}，两者均须 >0。",
                f"2. {status(checks[1])}：全区间自助回撤 p05={full.mdd_p05:.4%}（纯低波 {ref_boot.mdd_p05:.4%}）；"
                f"实际最大回撤={full.max_drawdown:.4%}（纯低波 {ref_mdd:.4%}）；两者均须不差于参照。",
                f"3. {status(checks[2])}：全区间与纯低波日收益相关={full.corr_lowvol:.6f}，要求 <0.5。",
                (f"4. {status(checks[3])}：4 个变体，CSCV 16 块 PBO={pbo:.6f}，要求 ≤0.3。" if pbo is not None
                 else f"4. 通过（不适用）：{len(CONFIGS[idea])} 个变体，未超过 3；PBO 不适用。"),
                capacity_line, "",
                f"结论：{'通过全部适用规则' if all(checks) else '未通过'}。", "",
                f"暂定 DSR（K=23，可用17变体方差）={dsr['dsr']:.6f}；"
                f"{'可能是运气（DSR<0.9）' if dsr['dsr'] < 0.9 else 'DSR≥0.9'}，不作否决条件。",
                f"K=17 敏感性 DSR={dsr17['dsr']:.6f}；年化夏普样本方差={variance:.8f}，"
                f"偏度={dsr['skew']:.6f}，非超额峰度={dsr['kurtosis']:.6f}。",
                "DSR 公式来源：[Bailey & López de Prado (2014)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)。",
                "", "## doubts", "", *[f"- {d}" for d in DOUBTS], ""]
        (folder / "verdict.md").write_text("\n".join(text))
        (folder / "dsr.json").write_text(json.dumps({"provisional_k23": dsr, "sensitivity_k17": dsr17}, indent=2) + "\n")
        overview.append({"idea": idea, "candidate": winner, "passed": all(checks),
                         **{f"rule{i+1}": value for i, value in enumerate(checks)},
                         "pbo": pbo, "dsr_provisional": dsr["dsr"]})
        print(f"报告 {idea}: {winner}, {'通过' if all(checks) else '未通过'}", flush=True)
    pd.DataFrame(overview).to_csv(OUT / "verdicts.csv", index=False)
    (OUT / "doubts.md").write_text("\n".join(f"- {d}" for d in DOUBTS) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["all", "index", "small", "calendar", "report"], default="all")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 6:
        parser.error("workers 必须为 1..6")
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "all":
        for stage in ("index", "small", "calendar", "report"):
            subprocess.run([sys.executable, __file__, "--stage", stage, "--workers",
                            str(1 if stage == "small" else args.workers)], check=True)
    elif args.stage in ("index", "small"):
        run_stocks(args.stage, args.workers)
    elif args.stage == "calendar":
        run_calendar()
    else:
        write_reports()


if __name__ == "__main__":
    main()
