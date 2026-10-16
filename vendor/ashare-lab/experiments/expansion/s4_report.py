"""S4：复用完整网格净值，运行集成、年度重选及亿元容量回测。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports/s4"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.benchmark import load_benchmarks
from ashare_lab.data.market import load_market_data
from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.pbo import cscv_pbo
from ashare_lab.strategies.ensemble import AnnualReselect, EnsembleVolTarget, neighbourhood
from ashare_lab.strategies.lowvol_trend import LowVolTrend
from ashare_lab.strategies.vol_target import VolTarget
from experiments.configs import B5_COST, S4_GRID
from experiments.expansion.common import PERIODS, bootstrap_mdd, metrics_table


DEFAULT = "lowvol_W250_N50_vt16_L60_s0.1"
LOWVOL = "lowvol_W250_N50"
MAIN = ["fixed", "ensemble", "reselect"]


def make_members():
    members, coords = {}, {}
    for config in S4_GRID:
        member = VolTarget(base=LowVolTrend(**config["base"]),
                           target_vol=config["target_vol"], window=config["window"],
                           step=config["step"])
        members[member.name] = member
        coords[member.name] = ((120, 250).index(config["base"]["vol_window"]),
                               (0.12, 0.14, 0.16).index(config["target_vol"]),
                               (20, 60).index(config["window"]))
    return members, coords


def grid_scores(window, coords):
    calmars = {name: metrics.calmar(window[name] / window[name].iloc[0]) for name in window}
    return pd.DataFrame([
        {"name": name, "calmar": calmars[name],
         "neighbourhood_calmar": np.mean([calmars[other]
                                         for other in neighbourhood(name, coords)])}
        for name in window
    ])


def annual_choices(strategy, calendar, grid, coords):
    strategy.rebalance_dates(calendar)
    score_columns = {name: np.nan for name in grid}
    rows = [{"year": calendar[0].year, "signal_date": pd.NaT,
             "selected": DEFAULT, "n_returns": 0, "used_default": True, **score_columns}]
    ends = calendar[~calendar.year.duplicated(keep="last")]
    for date in ends:
        window = grid.loc[:date].tail(strategy.lookback + 1)
        enough = len(window) >= strategy.lookback + 1
        scores = (grid_scores(window, coords).set_index("name").neighbourhood_calmar.to_dict()
                  if enough else score_columns)
        rows.append({"year": date.year + 1, "signal_date": date,
                     "selected": strategy.selection(date), "n_returns": max(0, len(window) - 1),
                     "used_default": not enough, **scores})
    return pd.DataFrame(rows)


def turnover_by_period(result):
    traded = result.trades[result.trades.side.isin(["buy", "sell"])].set_index("date")
    values = {}
    for period, (start, end) in PERIODS.items():
        nav = result.nav.loc[start:end]
        values[period] = float(traded.loc[start:end, "value"].sum() / 2 / nav.mean()
                               * 252 / (len(nav) - 1))
    return values


def plot(nav):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    for name in MAIN:
        series = nav[name]
        line, = axes[0].plot(series.index, series / series.iloc[0], label=name)
        axes[1].plot(series.index, metrics.drawdown_series(series), color=line.get_color())
    axes[0].set(yscale="log", ylabel="NAV (log)", title="S4: fixed / ensemble / annual reselect")
    axes[1].set_ylabel("Drawdown")
    axes[0].legend()
    for ax in axes:
        ax.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.5)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "nav.png", dpi=150)
    plt.close(fig)


def write_notes(table, boot, pbo, candidate):
    lookup = table.set_index(["name", "period"])
    resampled = boot.set_index("name")
    reference = lookup.loc[(LOWVOL, "FULL"), "max_drawdown"]
    reference_p05 = resampled.loc[LOWVOL, "mdd_p05"]
    pbo_ok = bool((pbo.pbo <= 0.3).all())
    lines = [
        "S4 参数集成研究",
        "全区间引擎运行一次，IS/OOS 为归一化切片；所有收盘信号由引擎次日开盘执行。",
        "集成近似：成员间股票构成仅月末更新；月内只按每日成员平均仓位调整总仓位。",
        "年度重选用年末截至当日的 757 个净值点（756 个收益），不足则用固定配置。",
        "choices.year 为下一生效年度；末行来自完整回测日历的最后交易日，可能尚未执行。",
        "年末历史不足时邻域评分留空。Calmar 未定义者不参与排名；全部未定义则用固定配置。",
        "容量版初始资金 1e8，成本 B5_COST；其他回测初始资金 1e7，默认成本。",
        "网格和 fixed 的 FULL 换手复用 s4_full/summary.csv；缺少分期成交，IS/OOS 换手留空。",
        "其余策略按各切片实际成交计算年化单边换手；纯低波仅报告已有 FULL 换手。",
        "bootstrap 为全区间日对数收益，20 日循环移动块，2000 次，种子 0，初始高点 1。",
        "PBO 按现有 cscv_pbo 的 Sharpe 选参排名计算，不改变为 Calmar。",
        f"IS 邻域平均 Calmar 最高的网格候选：{candidate}；不使用 OOS 选择。",
        f"PBO 门槛（两种分块均 <= 0.3）：{pbo_ok}；"
        + "; ".join(f"{int(row.n_blocks)} 块={row.pbo:.6f}" for row in pbo.itertuples()),
    ]
    for name in [candidate, *MAIN]:
        inside, outside = lookup.loc[(name, "IS")], lookup.loc[(name, "OOS")]
        full = lookup.loc[(name, "FULL")]
        alpha_ok = inside["alpha_000906.SH_TR"] > 0 and outside["alpha_000906.SH_TR"] > 0
        p05 = resampled.loc[name, "mdd_p05"]
        drawdown_ok = full.max_drawdown >= reference and p05 >= reference_p05
        lines.append(f"{name}: TR alpha IS={inside['alpha_000906.SH_TR']:.6f}, "
                     f"OOS={outside['alpha_000906.SH_TR']:.6f}, alpha 通过={alpha_ok}; "
                     f"FULL MDD={full.max_drawdown:.6f} (纯低波 {reference:.6f}), "
                     f"bootstrap p05={p05:.6f} (纯低波 {reference_p05:.6f}), 回撤通过={drawdown_ok}.")
        if name in MAIN:
            decline = full.cagr - lookup.loc[(name + "__cap1e8", "FULL"), "cagr"]
            improvement = outside.calmar > lookup.loc[("fixed", "OOS"), "calmar"]
            lines.append(f"  OOS Calmar={outside.calmar:.6f}, "
                         f"固定版={lookup.loc[('fixed', 'OOS'), 'calmar']:.6f}, "
                         f"高于固定版={improvement}; 容量 CAGR 下降={decline:.6f}, "
                         f"容量通过={decline < 0.01}; "
                         f"该策略全部门槛通过={bool(alpha_ok and drawdown_ok and improvement and pbo_ok and decline < 0.01)}.")
    if candidate != DEFAULT:
        lines.append("IS 网格候选未单独跑容量版（本任务仅要求 fixed/ensemble/reselect 三个容量版），"
                     "不据此宣称网格候选通过容量门槛。")
    (OUT / "notes.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    members, coords = make_members()
    source = pd.read_parquet(ROOT / "reports/s4_full/nav.parquet")
    # 排名平手始终遵循源净值列顺序，而非重新排序。
    names = [name for name in source if name in members]
    if len(names) != 12:
        raise ValueError("s4_full 净值必须含全部 12 个 S4 网格配置")
    grid = source[names].loc[slice(*PERIODS["FULL"])]
    if grid.isna().any().any():
        raise ValueError("S4 网格全区间净值存在缺失")
    coords = {name: coords[name] for name in names}
    nav = grid.copy()
    nav["fixed"] = grid[DEFAULT]
    source_summary = pd.read_csv(ROOT / "reports/s4_full/summary.csv").set_index("name")
    scalar_keys = ["max_drawdown", "max_drawdown_duration", "ulcer_index", "cagr", "ann_vol",
                   "sharpe", "calmar", "worst_month", "turnover", "cost_ratio", "avg_exposure"]
    rows = [{"name": name, **source_summary.loc[name, scalar_keys].to_dict()} for name in names]
    rows.append({"name": "fixed", **source_summary.loc[DEFAULT, scalar_keys].to_dict()})
    turnovers = {period: {} for period in PERIODS}
    turnovers["FULL"] = {row["name"]: row["turnover"] for row in rows}

    is_scores = grid_scores(grid.loc[slice(*PERIODS["IS"])], coords)
    candidate = is_scores.loc[is_scores.neighbourhood_calmar.idxmax(), "name"]
    is_scores["selected"] = is_scores.name == candidate
    is_scores.to_csv(OUT / "grid_is_calmar.csv", index=False)
    reselect = AnnualReselect(members, grid, coords, DEFAULT)
    choices = annual_choices(reselect, grid.index, grid, coords)
    choices.to_csv(OUT / "choices.csv", index=False)
    returns = grid.pct_change(fill_method=None).dropna()
    pbo = pd.DataFrame([{"n_blocks": blocks,
                         **{key: value for key, value in cscv_pbo(returns, blocks).items()
                            if key in ("pbo", "prob_oos_loss", "degradation_slope")}}
                        for blocks in (16, 10)])
    pbo.to_csv(OUT / "pbo.csv", index=False)
    print("pbo.csv\n" + pbo.to_string(index=False), flush=True)
    print("choices.csv\n" + choices.to_string(index=False), flush=True)

    print("Loading market data (2010-01-01..2026-09-30, 000906.SH)", flush=True)
    data = load_market_data(ROOT / "data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    ensemble = EnsembleVolTarget([members[name] for name in names])
    strategies = {"fixed": members[DEFAULT], "ensemble": ensemble, "reselect": reselect}
    # 成员信号只依赖行情与日期；跨回测复用这些历史信号缓存，不共享账户或持仓。
    jobs = [(name, False) for name in ("ensemble", "reselect")] + [(name, True) for name in MAIN]
    for name, capacity in jobs:
        label = name + ("__cap1e8" if capacity else "")
        print(f"Running {label}", flush=True)
        result = run_backtest(strategies[name], data, BacktestConfig(
            start=PERIODS["FULL"][0], end=PERIODS["FULL"][1],
            initial_cash=1e8 if capacity else 1e7,
            costs=CostModel(**B5_COST) if capacity else CostModel()))
        nav[label] = result.nav / result.nav.iloc[0]
        stats = metrics.summary(result)
        rows.append({"name": label, **{key: value for key, value in stats.items() if np.isscalar(value)}})
        for period, value in turnover_by_period(result).items():
            turnovers[period][label] = value
        print(f"Completed {label}: FULL cagr={stats['cagr']:.8f}", flush=True)
        del result
    del data
    nav.rename_axis("date").to_parquet(OUT / "nav.parquet")
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    lowvol = pd.read_parquet(ROOT / "reports/b3_full/nav.parquet")[LOWVOL].loc[slice(*PERIODS["FULL"])]
    benchmarks = load_benchmarks(ROOT / "data/benchmarks")
    reference_summary = pd.read_csv(ROOT / "reports/b3_full/summary.csv").set_index("name")
    turnovers["FULL"][LOWVOL] = reference_summary.loc[LOWVOL, "turnover"]
    evaluation = nav.assign(**{LOWVOL: lowvol})
    table = pd.concat([metrics_table(evaluation, benchmarks, lowvol,
                                     turnover=turnovers[period], periods={period: bounds})
                       for period, bounds in PERIODS.items()], ignore_index=True)
    table.to_csv(OUT / "metrics.csv", index=False)
    boot = bootstrap_mdd(evaluation)
    boot.to_csv(OUT / "bootstrap.csv", index=False)
    plot(nav)
    write_notes(table, boot, pbo, candidate)
    print("fixed / ensemble / reselect IS / OOS / FULL metrics:\n"
          + table[table.name.isin(MAIN)].to_string(index=False), flush=True)
    print("Capacity FULL CAGR:\n" + table[(table.period == "FULL")
          & table.name.str.endswith("__cap1e8")][["name", "cagr"]].to_string(index=False), flush=True)
    print(f"Reports written to {OUT}", flush=True)


if __name__ == "__main__":
    main()
