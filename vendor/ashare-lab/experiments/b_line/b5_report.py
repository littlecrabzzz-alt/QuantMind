"""B5 容量与平方根冲击：汇总真实成交、资金曲线和敏感性结果。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/b5"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter

from ashare_lab.data.market import load_market_data


STATS = ["cagr", "max_drawdown", "sharpe", "turnover", "cost_ratio"]
LABELS = {"lowvol_vt": "低波动＋波动率目标",
          "b3_buf_vt": "三因子＋缓冲＋波动率目标", "lowvol": "低波动基础"}


def trade_statistics(trades, row, data):
    """与引擎相同：缺失成交额记零，窗口不包含执行日。"""
    traded = trades[(trades.name == row["name"]) & trades.side.isin(["buy", "sell"])]
    if traded.empty:
        return {"impact_bp": 0.0, "participation_p50": 0.0, "participation_p95": 0.0}
    dates = data.calendar.get_indexer(pd.DatetimeIndex(traded.date))
    codes = data.open.columns.get_indexer(traded.code)
    opens = data.open.to_numpy()[dates, codes]
    amount = data.amount.fillna(0.0).to_numpy()
    window = int(row["cost_impact_window"])
    adv = np.empty(len(traded))
    for date in np.unique(dates):
        mask = dates == date
        adv[mask] = amount[max(0, date - window):date, :][:, codes[mask]].mean(axis=0)
    impact = (np.abs(traded.price.to_numpy() / opens - 1) - row["cost_slippage"]) * 1e4
    participation = traded.value.to_numpy() / adv
    return {"impact_bp": float(np.average(impact, weights=traded.value)),
            "participation_p50": float(np.quantile(participation, 0.5)),
            "participation_p95": float(np.quantile(participation, 0.95))}


def capacity_summary(data):
    rows = []
    for period in ("FULL", "OOS"):
        source = ROOT / "reports" / f"b5_capacity_{period.lower()}"
        summary = pd.read_csv(source / "summary.csv")
        trades = pd.read_parquet(source / "trades.parquet")
        for _, row in summary.iterrows():
            strategy = row["name"].split("__", 1)[0]
            rows.append({"period": period, "strategy": strategy, "cash": row.initial_cash,
                         **row[STATS].to_dict(), **trade_statistics(trades, row, data)})
    result = pd.DataFrame(rows)
    baseline = result[result.cash == 1e7].set_index(["period", "strategy"]).cagr
    result["cagr_drop"] = [row.cagr - baseline.loc[(row.period, row.strategy)]
                           for row in result.itertuples()]
    result.to_csv(OUT / "b5_capacity.csv", index=False)
    return result


def sensitivity_summary(data):
    source = ROOT / "reports/b5_sens"
    summary = pd.read_csv(source / "summary.csv")
    trades = pd.read_parquet(source / "trades.parquet")
    rows = []
    for _, row in summary.iterrows():
        strategy, variant = row["name"].split("__", 1)
        rows.append({"strategy": strategy, "variant": variant,
                     **row[["cagr", "max_drawdown", "turnover", "cost_ratio"]].to_dict(),
                     "impact_bp": trade_statistics(trades, row, data)["impact_bp"]})
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "b5_sens.csv", index=False)
    return result


def reference_summary():
    summary = pd.read_csv(ROOT / "reports/b5_ref/summary.csv")
    rows = []
    for _, row in summary.iterrows():
        strategy, period = row["name"].split("__", 1)
        rows.append({"period": period, "strategy": strategy,
                     "cagr": row.cagr, "max_drawdown": row.max_drawdown})
    pd.DataFrame(rows).to_csv(OUT / "b5_ref.csv", index=False)


def plot_capacity(capacity):
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), sharex=True, sharey="row")
    for column, period in enumerate(("FULL", "OOS")):
        for strategy, label in LABELS.items():
            frame = capacity[(capacity.period == period) &
                             (capacity.strategy == strategy)].sort_values("cash")
            line, = axes[0, column].plot(frame.cash, frame.cagr, marker="o", label=label)
            axes[1, column].plot(frame.cash, frame.impact_bp, marker="o",
                                 color=line.get_color())
        axes[0, column].set_title("全区间 FULL" if period == "FULL" else "样本外 OOS")
        axes[0, column].yaxis.set_major_formatter(PercentFormatter(1))
        axes[0, column].legend()
        axes[1, column].set_xlabel("初始资金（元，对数）")
        for axis in axes[:, column]:
            axis.set_xscale("log")
            axis.set_xticks([1e7, 1e8, 1e9, 1e10], ["1000万", "1亿", "10亿", "100亿"])
            axis.grid(alpha=0.25)
    axes[0, 0].set_ylabel("年化收益")
    axes[1, 0].set_ylabel("成交额加权冲击（bp）")
    fig.suptitle("B5 容量与冲击成本｜冲击系数 1.0｜单日成交上限 10%")
    fig.tight_layout()
    fig.savefig(OUT / "b5_capacity.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    capacity = capacity_summary(data)
    sensitivity = sensitivity_summary(data)
    reference_summary()
    plot_capacity(capacity)
    print(capacity.to_string(index=False))
    print(sensitivity.to_string(index=False))


if __name__ == "__main__":
    main()
