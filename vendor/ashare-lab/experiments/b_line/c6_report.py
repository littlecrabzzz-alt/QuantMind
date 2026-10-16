"""C6 估值历史分位复现：分区间指标、双基准归因及参数网格。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/c6"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter

from ashare_lab import metrics
from ashare_lab.benchmark import benchmark_table, load_benchmarks


PERIODS = {
    "2015-2019": ("2015-01-01", "2019-12-31"),
    "2020-2026": ("2020-01-01", "2026-09-30"),
    "2015-2026": ("2015-01-01", "2026-09-30"),
}
STATS = ["cagr", "ann_vol", "sharpe", "max_drawdown", "calmar"]


def final_summary(nav, benchmarks):
    turnover = pd.read_csv(OUT / "run/summary.csv").set_index("name").turnover
    rows = []
    for period, (start, end) in PERIODS.items():
        for name in nav:
            series = nav[name].loc[start:end].dropna()
            series = series / series.iloc[0]
            attribution = benchmark_table(series, benchmarks.loc[start:end])
            price, tr = attribution.loc["000906.SH"], attribution.loc["000906.SH_TR"]
            rows.append({
                "period": period, "name": name,
                **{stat: getattr(metrics, stat)(series) for stat in STATS},
                "turnover": 0.0 if name == "index:000906.SH" else turnover.loc[name],
                "alpha_price": price.alpha_ann, "beta_price": price.beta,
                "alpha_tr": tr.alpha_ann, "beta_tr": tr.beta,
                "excess_cagr_tr": tr.excess_cagr,
            })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "c6_summary.csv", index=False)
    parameters = summary.name.str.extract(r"^(pe|pb)_pct_W(36|60)_N(10|20|50|100)$")
    parameters.columns = ["metric", "window", "top_n"]
    grid = pd.concat([parameters, summary[["period", "cagr", "max_drawdown", "sharpe",
                                          "turnover"]]], axis=1).dropna(subset=["metric"])
    grid[["window", "top_n"]] = grid[["window", "top_n"]].astype(int)
    grid.to_csv(OUT / "c6_grid.csv", index=False)
    return summary, grid


def configure_fonts():
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})


def plot_nav(nav, benchmarks):
    labels = {
        "pe_pct_W60_N50": "PE历史分位 W60 N50",
        "pb_pct_W60_N50": "PB历史分位 W60 N50",
        "ep_xs_N50": "EP截面 N50",
        "bp_xs_N50": "BP截面 N50",
        "all_eq": "成分等权",
        "lowvol_W250_N50": "低波动 W250 N50",
        "000906.SH_TR": "中证800全收益基准",
    }
    nav = nav.assign(**{"000906.SH_TR": benchmarks["000906.SH_TR"].reindex(nav.index)})
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for name, label in labels.items():
        series = nav[name].dropna()
        series = series / series.iloc[0]
        line, = axes[0].plot(series.index, series, label=label)
        axes[1].plot(series.index, metrics.drawdown_series(series), color=line.get_color())
    axes[0].set_yscale("log")
    axes[0].set_ylabel("净值（对数）")
    axes[1].set_ylabel("回撤")
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[0].set_title("C6 估值历史分位复现｜中证800历史成分｜2015–2026")
    axes[0].legend(loc="upper left", ncol=2)
    for axis in axes:
        axis.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.6)
        axis.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "c6_nav.png", dpi=150)
    plt.close(fig)


def plot_grid(grid):
    full = grid[grid.period == "2015-2026"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    for column, metric in enumerate(("pe", "pb")):
        for row, (stat, label) in enumerate((("cagr", "年化收益"),
                                           ("max_drawdown", "最大回撤"))):
            axis = axes[row, column]
            for window in (36, 60):
                values = full[(full.metric == metric) & (full.window == window)].sort_values("top_n")
                axis.plot(values.top_n, values[stat], marker="o", label=f"W{window}")
            axis.set_title(f"{metric.upper()}历史分位｜{label}")
            axis.set_ylabel(label)
            axis.yaxis.set_major_formatter(PercentFormatter(1))
            axis.set_xticks([10, 20, 50, 100])
            axis.legend()
            axis.grid(alpha=0.25)
        axes[1, column].set_xlabel("持股数 top_n")
    fig.suptitle("C6 参数网格｜2015–2026｜默认交易成本")
    fig.tight_layout()
    fig.savefig(OUT / "c6_grid.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    nav = pd.read_parquet(OUT / "run/nav.parquet")
    benchmarks = load_benchmarks("data/benchmarks")
    summary, grid = final_summary(nav, benchmarks)
    configure_fonts()
    plot_nav(nav, benchmarks)
    plot_grid(grid)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
