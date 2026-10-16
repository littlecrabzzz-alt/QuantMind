"""社区第 2、7 条：四个指数上的均线择时复现（规则固定，次日开盘成交）。"""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.data.fundamentals import Fundamentals
from ashare_lab.index_timing import (
    index_ep, ma_rule, rel_underperf_years, rule_182_pe, rule_ma_dip_buy, rule_ma_dip_exit,
    simulate, trade_stats,
)
from ashare_lab.strategy import month_end_dates

OUT = ROOT / "reports" / "c27"
INDICES = {"000300.SH": (0.03, 0.05), "000906.SH": (0.03, 0.05),
           "000905.SH": (0.05, 0.08), "000852.SH": (0.05, 0.08)}
NAMES = {"000300.SH": "沪深300", "000906.SH": "中证800", "000905.SH": "中证500", "000852.SH": "中证1000"}
START, END = pd.Timestamp("2012-01-04"), pd.Timestamp("2026-09-30")
PERIODS = {"IS": ("2012-01-01", "2019-12-31"), "OOS": ("2020-01-01", "2026-09-30"),
           "FULL": ("2012-01-01", "2026-09-30")}
COST = 0.0005


def index_pe(month_ends):
    fund = Fundamentals.load(ROOT / "data" / "fundamentals")
    members = pd.read_parquet(ROOT / "data" / "panel" / "index_members.parquet")
    members["snapshot_date"] = pd.to_datetime(members.snapshot_date)
    basic = pd.read_parquet(ROOT / "data" / "panel" / "basic.parquet", columns=["date", "code", "total_mv"])
    basic["date"] = pd.to_datetime(basic.date)
    mv = basic.pivot(index="date", columns="code", values="total_mv").sort_index()
    rows = []
    for d in month_ends:
        earnings = fund.ttm("n_income_attr_p", d)
        cap = mv.loc[:d].iloc[-1] * 1e4
        ep = (earnings.reindex(cap.index) / cap.where(cap > 0))
        for code in INDICES:
            snaps = members[(members.index_code == code) & (members.snapshot_date <= d)]
            if snaps.empty:
                continue
            last = snaps[snaps.snapshot_date == snaps.snapshot_date.max()].set_index("code").weight
            value = index_ep(last, ep)
            rows.append({"date": d, "index": code, "pe": 1 / value if value > 0 else np.nan})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    daily = pd.read_parquet(ROOT / "data" / "panel" / "index_daily.parquet")
    daily["date"] = pd.to_datetime(daily.date)
    daily = daily[daily.date <= END]
    calendar = pd.DatetimeIndex(sorted(daily.date.unique()))
    pe = index_pe(month_end_dates(calendar))
    pe.to_csv(OUT / "c27_index_pe.csv", index=False)

    rows, navs = [], {}
    for code, (a1, a2) in INDICES.items():
        px = daily[daily.index_code == code].set_index("date").sort_index()
        close, open_ = px.close, px.open.fillna(px.close)
        pe_daily = (pe[pe["index"] == code].set_index("date").pe
                    .reindex(close.index, method="ffill"))   # 只用最近一个月末的值
        ma250 = ma_rule(close, 250)
        signals = {
            "hold": pd.Series(1, index=close.index),
            "ma250": ma250,
            "ma182": ma_rule(close, 182),
            "ma250_dip_exit": rule_ma_dip_exit(close, a1, a2, trend=ma250),
            "ma250_dip_buy": rule_ma_dip_buy(close, a1, a2, hold=5, trend=ma250),
            "ma182_pe": rule_182_pe(close, pe_daily, n=182, band=0.07, pe_max=20),
        }
        window = (close.index >= START)
        for rule, sig in signals.items():
            sim = simulate(open_[window], close[window], sig[window], cost=COST)
            sim2 = simulate(open_[window], close[window], sig[window], cost=COST, cash_rate=0.02)
            navs[(code, rule)] = sim.nav
            for period, (a, b) in PERIODS.items():
                nav = sim.nav.loc[a:b]
                nav = nav / nav.iloc[0]
                pos = sim.position.loc[a:b]
                stats = trade_stats(pos, nav)
                years = (len(nav) - 1) / 252
                rows.append({
                    "index": code, "rule": rule, "period": period,
                    "cagr": metrics.cagr(nav), "max_drawdown": metrics.max_drawdown(nav),
                    "sharpe": metrics.sharpe(nav), "avg_exposure": float(pos.mean()),
                    "trades_per_year": stats["n_trades"] / years if years > 0 else np.nan,
                    "win_rate": stats["win_rate"], "payoff": stats["payoff"],
                    "cagr_cash2pct": metrics.cagr(sim2.nav.loc[a:b] / sim2.nav.loc[a:b].iloc[0]),
                    "_nav": nav,
                })
    summary = pd.DataFrame(rows)
    hold = {(r["index"], r["period"]): r["_nav"] for r in rows if r["rule"] == "hold"}
    summary["rel_underperf_years"] = [
        rel_underperf_years(r["_nav"], hold[(r["index"], r["period"])]) for r in rows
    ]
    summary = summary.drop(columns="_nav")
    # 持有组仓位第一天为 0（信号滞后一日），按定义记为满仓。
    summary.loc[summary.rule == "hold", "avg_exposure"] = 1.0
    summary.to_csv(OUT / "c27_summary.csv", index=False)

    os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    for ax, code in zip(axes.ravel(), INDICES):
        for rule in ("hold", "ma250", "ma182", "ma250_dip_exit", "ma250_dip_buy", "ma182_pe"):
            ax.plot(navs[(code, rule)], label=rule, lw=1.2 if rule != "hold" else 2)
        ax.axvline(pd.Timestamp("2020-01-01"), color="k", ls="--", lw=1)
        ax.set_yscale("log")
        ax.set_title(f"{NAMES[code]}（{code}，价格指数）")
        ax.grid(alpha=0.3)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("指数均线择时复现｜收盘信号、次日开盘成交、单边 5bp｜规则固定")
    fig.tight_layout()
    fig.savefig(OUT / "c27_nav.png", dpi=150)
    plt.close(fig)

    pd.set_option("display.width", 250)
    cols = ["index", "rule", "cagr", "max_drawdown", "sharpe", "avg_exposure", "trades_per_year",
            "win_rate", "payoff", "rel_underperf_years"]
    for period in ("FULL", "OOS"):
        print(period)
        print(summary[summary.period == period][cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
