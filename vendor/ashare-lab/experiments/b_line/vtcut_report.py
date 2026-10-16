"""固定变体、减仓事件及 CSCV：所有区间均从全区间回测切片。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/vtcut"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from ashare_lab import metrics
from ashare_lab.pbo import cscv_pbo
from b3_report import configure_fonts


PERIODS = {
    "2012-2019": ("2012-01-01", "2019-12-31"),
    "2020-2026": ("2020-01-01", "2026-09-30"),
    "2012-2026": ("2012-01-01", "2026-09-30"),
}
BASES = {"lowvol": "低波动底仓", "b3": "三组合成＋排名缓冲"}
EVENTS = {"all_cuts": "全部减仓", "top10_cuts": "最大 10% 减仓",
          "cuts_after_drop": "大跌后减仓"}
HORIZONS = (5, 10, 20)


def summarize(nav, exposure, statistics):
    rows = []
    for name in nav:
        base, variant = name.split("__")
        for period, (start, end) in PERIODS.items():
            series = nav[name].loc[start:end].dropna()
            series = series / series.iloc[0]
            rows.append({
                "base": base, "variant": variant, "period": period,
                "cagr": metrics.cagr(series), "max_drawdown": metrics.max_drawdown(series),
                "sharpe": metrics.sharpe(series), "turnover": statistics.loc[name, "turnover"],
                "avg_exposure": exposure[name].loc[start:end].mean(),
            })
    return pd.DataFrame(rows)


def event_study(nav, exposure):
    rng = np.random.default_rng(0)
    rows = []
    for base in BASES:
        full = nav[f"{base}__none"].dropna()
        cut = -exposure[f"{base}__base"].reindex(full.index).diff()
        daily = full.pct_change(fill_method=None)
        masks = {
            "all_cuts": cut > 0,
            # 阈值由全区间全部减仓日确定；相同幅度全部纳入。
            "top10_cuts": (cut > 0) & (cut >= cut[cut > 0].quantile(0.9)),
            "cuts_after_drop": (cut > 0) & (
                (daily <= -0.03) | (daily.shift(1) <= -0.03)
                | (full / full.shift(2) - 1 <= -0.05)),
        }
        for period, (start, end) in PERIODS.items():
            for event_type, mask in masks.items():
                for h in HORIZONS:
                    # 先计算跨区间的前瞻收益，再按事件日期切片；仅舍弃数据尾部。
                    population = (full.shift(-h) / full - 1).loc[start:end].dropna()
                    event = population[mask.reindex(population.index)]
                    n = len(event)
                    stats = dict.fromkeys(("fwd_mean", "uncond_mean", "frac_pos", "p_value",
                                           "missed_gain", "avoided_loss"), np.nan)
                    if n:
                        mean = event.mean()
                        values = population.to_numpy()
                        sampled = np.array([
                            rng.choice(values, size=n, replace=False).mean() for _ in range(5000)
                        ])
                        magnitude = cut.reindex(event.index)
                        stats.update(
                            fwd_mean=mean, uncond_mean=population.mean(),
                            frac_pos=(event > 0).mean(), p_value=(sampled <= mean).mean(),
                            missed_gain=(magnitude * event.clip(lower=0)).sum(),
                            avoided_loss=(magnitude * (-event).clip(lower=0)).sum(),
                        )
                    rows.append({"base": base, "period": period, "event_type": event_type,
                                 "h": h, "n_events": n, **stats})
    return pd.DataFrame(rows)


def pbo_summary(nav):
    rows = []
    for base in BASES:
        columns = [name for name in nav if name.startswith(f"{base}__")
                   and name != f"{base}__none"]
        returns = nav[columns].pct_change(fill_method=None).dropna()
        for n_blocks in (10, 16):
            result = cscv_pbo(returns, n_blocks=n_blocks)
            rows.append({"base": base, "n_configs": len(columns), "n_blocks": n_blocks,
                         "pbo": result["pbo"], "prob_oos_loss": result["prob_oos_loss"]})
    return pd.DataFrame(rows)


def plot_events(events):
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    x = np.arange(len(HORIZONS))
    width = 0.2
    for axis, (base, label) in zip(axes, BASES.items()):
        frame = events[(events.base == base) & (events.period == "2012-2026")]
        for i, (event_type, title) in enumerate(EVENTS.items()):
            values = frame[frame.event_type == event_type].set_index("h").reindex(HORIZONS)
            axis.bar(x + (i - 1.5) * width, values.fwd_mean, width, label=title)
        unconditional = frame[frame.event_type == "all_cuts"].set_index("h").reindex(HORIZONS)
        axis.bar(x + 1.5 * width, unconditional.uncond_mean, width, label="无条件均值")
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_title(label)
        axis.set_ylabel("平均前瞻收益")
        axis.yaxis.set_major_formatter(PercentFormatter(1))
        axis.legend(ncol=4)
        axis.grid(axis="y", alpha=0.25)
    axes[-1].set_xticks(x, [f"{h} 个交易日" for h in HORIZONS])
    fig.suptitle("减仓收盘信号后满仓底仓收益｜2012–2026")
    fig.tight_layout()
    fig.savefig(OUT / "vtcut_events.png", dpi=150)
    plt.close(fig)


def plot_drawdowns(nav):
    variants = {"none": "不控仓", "base": "基准控仓", "delay3": "延迟 3 日",
                "half": "减仓一半", "win120": "120 日窗口", "downside": "下行波动"}
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for axis, (base, label) in zip(axes, BASES.items()):
        for variant, title in variants.items():
            series = nav[f"{base}__{variant}"].dropna()
            axis.plot(series.index, metrics.drawdown_series(series), label=title)
        axis.set_title(label)
        axis.set_ylabel("回撤")
        axis.yaxis.set_major_formatter(PercentFormatter(1))
        axis.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.6)
        axis.legend(ncol=3)
        axis.grid(alpha=0.25)
    fig.suptitle("固定仓位变体的全区间回撤｜2012–2026")
    fig.tight_layout()
    fig.savefig(OUT / "vtcut_nav.png", dpi=150)
    plt.close(fig)


def main():
    nav = pd.read_parquet(OUT / "nav.parquet")
    exposure = pd.read_parquet(OUT / "exposure.parquet")
    statistics = pd.read_csv(OUT / "summary.csv").set_index("name")
    summary = summarize(nav, exposure, statistics)
    events = event_study(nav, exposure)
    pbo = pbo_summary(nav)
    summary.to_csv(OUT / "vtcut_summary.csv", index=False)
    events.to_csv(OUT / "vtcut_events.csv", index=False)
    pbo.to_csv(OUT / "vtcut_pbo.csv", index=False)
    configure_fonts()
    plot_events(events)
    plot_drawdowns(nav)
    print("区间指标来自全区间净值切片归一；turnover 为整段年化单边换手。")
    print("事件以 t 日收盘信号计，前瞻收益为满仓底仓 nav[t+h]/nav[t]-1。")
    print("p_value 为左尾随机抽样比例：越小表示事件后收益越低；事件重叠，非因果检验。")
    print("missed_gain / avoided_loss 是幅度加权收益之和，不是可实现的组合损益。")
    print(pbo.to_string(index=False))
    print(summary[summary.period.isin(["2012-2026", "2020-2026"])].to_string(index=False))
    print(events[events.period == "2012-2026"].to_string(index=False))


if __name__ == "__main__":
    main()
