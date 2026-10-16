"""扩展研究共用的切片指标、循环块自助法与报告绘图。"""

from pathlib import Path
import numpy as np
import pandas as pd

from ashare_lab import metrics
from ashare_lab.benchmark import alpha_beta

PERIODS = {"IS": ("2012-01-01", "2019-12-31"),
           "OOS": ("2020-01-01", "2026-09-30"),
           "FULL": ("2012-01-01", "2026-09-30")}


def metrics_table(nav_frame, benchmarks, lowvol_nav, turnover=None, periods=PERIODS):
    rows = []
    for name in nav_frame:
        available = nav_frame[name].dropna()
        for period, (start, end) in periods.items():
            nav = available.loc[start:end]
            if len(nav) < 2:
                continue
            nav = nav / nav.iloc[0]
            row = {"name": name, "period": period, "start": nav.index[0], "end": nav.index[-1],
                   **{key: getattr(metrics, key)(nav) for key in
                      ("cagr", "ann_vol", "sharpe", "max_drawdown", "calmar")},
                   "turnover": (turnover or {}).get(name, np.nan)}
            for code in ("000906.SH", "000906.SH_TR"):
                stats = alpha_beta(nav, benchmarks[code])
                row.update({f"alpha_{code}": stats["alpha_ann"], f"beta_{code}": stats["beta"]})
            aligned = pd.concat([nav.rename("nav"), lowvol_nav.rename("lowvol")],
                                axis=1, join="inner").dropna().pct_change(fill_method=None)
            row["corr_lowvol"] = aligned.nav.corr(aligned.lowvol)
            rows.append(row)
    return pd.DataFrame(rows)


def bootstrap_mdd(nav_frame, draws=2000, block=20, seed=0):
    rows = []
    for name in nav_frame:
        log_returns = np.log1p(nav_frame[name].dropna().pct_change(fill_method=None).dropna().to_numpy())
        n = len(log_returns)
        if n == 0:
            rows.append({"name": name, "mdd_p05": np.nan, "mdd_p50": np.nan, "mdd_p95": np.nan})
            continue
        # 每列重置生成器：相同历史长度共用 b2 的抽样顺序，较短变体独立 dropna。
        rng = np.random.default_rng(seed)
        mdds = np.empty(draws)
        for start in range(0, draws, 100):
            count = min(100, draws - start)
            starts = rng.integers(0, n, size=(count, (n + block - 1) // block))
            indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(count, -1)[:, :n]
            paths = np.cumsum(log_returns[indices], axis=1)
            peaks = np.maximum(0, np.maximum.accumulate(paths, axis=1))
            mdds[start:start + count] = np.expm1((paths - peaks).min(axis=1))
        q = np.quantile(mdds, [0.05, 0.5, 0.95])
        rows.append(dict(zip(("name", "mdd_p05", "mdd_p50", "mdd_p95"), (name, *q))))
    return pd.DataFrame(rows)


def monthly_signals(dates):
    dates = pd.DatetimeIndex(dates)
    month_ends = pd.Series(dates, index=dates).groupby(dates.to_period("M")).last()
    return pd.DatetimeIndex([dates[0], *month_ends]).unique().sort_values()


def plot_nav(nav_frame, output, title):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "b_line"))
    from b2_report import configure_fonts
    import matplotlib.pyplot as plt
    configure_fonts()
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    for name in nav_frame:
        nav = nav_frame[name].dropna()
        line, = axes[0].plot(nav.index, nav / nav.iloc[0], label=name)
        axes[1].plot(nav.index, metrics.drawdown_series(nav), color=line.get_color())
    axes[0].set(title=title, ylabel="净值（对数）", yscale="log")
    axes[1].set_ylabel("回撤")
    axes[0].legend(loc="upper left", ncol=3, fontsize=8)
    for ax in axes:
        ax.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.5)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
