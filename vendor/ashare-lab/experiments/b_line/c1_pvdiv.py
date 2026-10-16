"""社区第 1 条：20 日量价背离因子（−corr(价格, 成交量)）的 IC 与可交易性。

用法：c1_pvdiv.py scores   计算月末打分 → reports/c1/scores.parquet，并输出日度/月度 IC
      c1_pvdiv.py report   读回测结果出汇总表和图
"""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

OUT = ROOT / "reports" / "c1"
WINDOW, MIN_OBS = 20, 16


def pv_divergence(adj_close, volume):
    """−corr(后复权价, 成交量)，窗口 20 日，停牌日（缺失）不参与，有效天数不足 16 记缺失。"""
    price = adj_close.where(volume > 0)
    vol = volume.where(volume > 0)
    return -price.rolling(WINDOW, min_periods=MIN_OBS).corr(vol)


def neutralize(frame, target, controls):
    """逐期横截面：target 对 controls 做 OLS，取残差。"""
    out = pd.Series(np.nan, index=frame.index)
    for date, sub in frame.groupby(level="date"):
        sub = sub[[target, *controls]].dropna()
        if len(sub) < 50:
            continue
        x = np.column_stack([np.ones(len(sub)), sub[controls].to_numpy()])
        beta, *_ = np.linalg.lstsq(x, sub[target].to_numpy(), rcond=None)
        out.loc[sub.index] = sub[target].to_numpy() - x @ beta
    return out


def ic_table(score, fwd, periods):
    rows = []
    for name, (a, b) in periods.items():
        dates = [d for d in score.index.get_level_values("date").unique() if a <= d <= b]
        ics = []
        for d in dates:
            s = pd.concat([score.loc[d], fwd.loc[d]], axis=1).dropna()
            if len(s) >= 50:
                ics.append(s.iloc[:, 0].rank().corr(s.iloc[:, 1].rank()))
        ics = pd.Series(ics, dtype=float)
        rows.append({"period": name, "ic_mean": ics.mean(), "ic_ir": ics.mean() / ics.std(ddof=1),
                     "t_stat": ics.mean() / ics.std(ddof=1) * np.sqrt(len(ics)), "n": len(ics)})
    return rows


def scores():
    from ashare_lab.data.market import load_market_data
    from ashare_lab.factors import compute_factors
    from ashare_lab.strategy import month_end_dates
    from ashare_lab.universe import eligible

    OUT.mkdir(parents=True, exist_ok=True)
    data = load_market_data(ROOT / "data" / "panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    adj = data.adj_close()
    div = pv_divergence(adj, data.volume)
    ret = adj.pct_change(fill_method=None).where(data.close.notna())

    months = month_end_dates(data.calendar)
    months = months[months >= pd.Timestamp("2011-12-01")]
    factors = compute_factors(data, months)                      # 只含可选股票
    factors["pv_div"] = [div.at[d, c] for d, c in factors.index]
    factors["pv_div_neu"] = neutralize(factors, "pv_div", ["rev_20", "vol_20", "mom_12_1"])
    factors[["pv_div", "pv_div_neu", "rev_20", "vol_20", "mom_12_1"]].to_parquet(OUT / "scores.parquet")

    periods = {"IS": (pd.Timestamp("2012-01-01"), pd.Timestamp("2019-12-31")),
               "OOS": (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-08-31"))}
    # 月度 IC：月末打分 vs 下一个月末之间的收益
    nxt = adj.loc[months].shift(-1) / adj.loc[months] - 1
    fwd_m = nxt.stack(future_stack=True).rename("fwd")
    rows = []
    for col in ("pv_div", "pv_div_neu"):
        for r in ic_table(factors[col], fwd_m, periods):
            rows.append({"factor": col, "horizon": "1M", **r})
    # 日度 IC（原文口径）：t 日收盘打分 vs t+1 日收益，只用当日中证 800 可选股票
    days = data.calendar[(data.calendar >= "2012-01-01") & (data.calendar <= "2026-09-29")]
    fwd_d = ret.shift(-1)
    ic_d = []
    for d in days:
        mask = eligible(d, data)
        s = pd.concat([div.loc[d][mask], fwd_d.loc[d][mask]], axis=1).dropna()
        if len(s) >= 50:
            ic_d.append((d, s.iloc[:, 0].rank().corr(s.iloc[:, 1].rank())))
    ic_d = pd.Series(dict(ic_d))
    for name, (a, b) in periods.items():
        x = ic_d.loc[a:b]
        rows.append({"factor": "pv_div", "horizon": "1D", "period": name, "ic_mean": x.mean(),
                     "ic_ir": x.mean() / x.std(ddof=1), "t_stat": x.mean() / x.std(ddof=1) * np.sqrt(len(x)),
                     "n": len(x)})
    ic = pd.DataFrame(rows)
    ic.to_csv(OUT / "c1_ic.csv", index=False)
    print(ic.round(4).to_string(index=False))


def report():
    from ashare_lab import metrics
    from ashare_lab.benchmark import benchmark_table, load_benchmarks

    nav = pd.read_parquet(OUT / "run" / "nav.parquet")
    summ = pd.read_csv(OUT / "run" / "summary.csv").set_index("name")
    bench = load_benchmarks(ROOT / "data" / "benchmarks")
    rows = []
    for period, (a, b) in {"2012-2019": ("2012-01-01", "2019-12-31"),
                           "2020-2026": ("2020-01-01", "2026-09-30"),
                           "2012-2026": ("2012-01-01", "2026-09-30")}.items():
        for name in nav.columns:
            s = nav[name].loc[a:b].dropna()
            s = s / s.iloc[0]
            t = benchmark_table(s, bench)
            rows.append({"period": period, "name": name, "cagr": metrics.cagr(s),
                         "max_drawdown": metrics.max_drawdown(s), "sharpe": metrics.sharpe(s),
                         "turnover": summ.loc[name, "turnover"],
                         "alpha_tr": t.loc["000906.SH_TR", "alpha_ann"],
                         "excess_cagr_tr": t.loc["000906.SH_TR", "excess_cagr"]})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "c1_summary.csv", index=False)

    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for name in nav.columns:
        axes[0].plot(nav[name], label=name)
        axes[1].plot(metrics.drawdown_series(nav[name].dropna()), label=name)
    axes[0].set_yscale("log")
    axes[0].set_title("量价背离复现｜中证 800｜月末前 50 只等权")
    for ax in axes:
        ax.axvline(pd.Timestamp("2020-01-01"), color="k", ls="--", lw=1)
        ax.grid(alpha=0.3)
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(OUT / "c1_nav.png", dpi=150)
    pd.set_option("display.width", 200)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    {"scores": scores, "report": report}[sys.argv[1]]()
