"""B2 波动率目标仓位研究：先用 --choose 冻结样本内选参，再生成最终报告。"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/b2"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from ashare_lab import metrics
from ashare_lab.attribution import alpha_beta


LOWVOL = "lowvol_W250_N50"
NEUTRAL = "indneutral_count_W250_N50"
TIMING = "lowvol_W250_N50_L60_e0.3"
INDEX = "index:000906.SH"
STATS = ["cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover", "avg_exposure"]


def benchmark_prices():
    prices = pd.read_parquet(ROOT / "data/panel/index_daily.parquet",
                             columns=["date", "index_code", "close"])
    prices = prices[prices.index_code == "000906.SH"].copy()
    prices["date"] = pd.to_datetime(prices.date)
    return prices.set_index("date").close.sort_index()


def read_experiment(name):
    source = ROOT / "reports" / name
    return pd.read_csv(source / "summary.csv"), pd.read_parquet(source / "nav.parquet")


def grid_rows(period, benchmark):
    summary, nav = read_experiment(f"b2_grid_{period.lower()}")
    rows = []
    for _, row in summary.iterrows():
        series = nav[row["name"]].dropna()
        attribution = alpha_beta(series, benchmark.loc[series.index[0]:series.index[-1]])
        rows.append({"period": period,
                     "base": "lowvol" if row["base"] == LOWVOL else "indneutral_count",
                     "target_vol": row.target_vol, "window": int(row.window),
                     **row[[key for key in STATS if key != "ann_vol"]].to_dict(),
                     **{key: attribution[key] for key in ("alpha", "beta")}})
    return pd.DataFrame(rows)


def choose_from_is(grid):
    """此函数只接受 IS 表；同分按目标波动、窗口升序取首格。"""
    if set(grid.period) != {"IS"}:
        raise ValueError("选参只能传入样本内数据")
    table = grid[grid.base == "lowvol"].pivot(
        index="target_vol", columns="window", values="calmar").sort_index().sort_index(axis=1)
    values = table.to_numpy()
    scores = np.empty(values.shape)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            scores[i, j] = np.nanmean(values[max(0, i-1):i+2, max(0, j-1):j+2])
    i, j = np.unravel_index(np.nanargmax(scores), scores.shape)
    return {"target_vol": float(table.index[i]), "window": int(table.columns[j]), "step": 0.1,
            "rule": "只用 IS、base=lowvol：5×4 网格各格的 3×3 邻域（含自身，边界只取存在格）"
                    "Calmar 均值最大；同分按 target_vol、window 升序取首格。OOS 不参与选参。",
            "is_neighborhood_calmar": float(scores[i, j])}


def choose(benchmark):
    inside = grid_rows("IS", benchmark)
    choice = choose_from_is(inside)
    # 冻结选择后才读取样本外结果，明确隔离选参和评估。
    (OUT / "b2_choice.json").write_text(json.dumps(choice, ensure_ascii=False, indent=2) + "\n")
    outside = grid_rows("OOS", benchmark)
    pd.concat([inside, outside], ignore_index=True).to_csv(OUT / "b2_grid.csv", index=False)
    print(json.dumps(choice, ensure_ascii=False, indent=2))


def final_summary(benchmark):
    rows = []
    full_nav = None
    for period in ("IS", "OOS", "FULL"):
        statistics, nav = read_experiment(f"b2_final_{period.lower()}")
        for _, row in statistics.iterrows():
            name = row["name"]
            series = nav[name].dropna()
            attribution = alpha_beta(series, benchmark.loc[series.index[0]:series.index[-1]])
            stats = row[STATS].to_dict()
            if name == INDEX:
                stats.update(turnover=0.0, avg_exposure=1.0)
            cash_cagr = (stats["cagr"] if name == INDEX else
                         (1 + stats["cagr"]) * (1 + 0.02 * (1 - stats["avg_exposure"])) - 1)
            rows.append({"period": period, "name": name, **stats,
                         **{key: attribution[key] for key in ("alpha", "beta", "r2")},
                         "benchmark": "000906.SH 价格指数", "cagr_cash2pct": cash_cagr})
        if period == "FULL":
            full_nav = nav
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "b2_summary.csv", index=False)
    return summary, full_nav


def robustness():
    summary, _ = read_experiment("b2_robust")
    rows = []
    for _, row in summary.iterrows():
        variant = "slippage_0.002" if np.isclose(row.cost_slippage, 0.002) else f"step_{row.step:g}"
        period = "IS" if row.start == "2012-01-01" else "OOS"
        rows.append({"variant": variant, "period": period,
                     **row[["cagr", "max_drawdown", "calmar", "turnover", "avg_exposure"]].to_dict()})
    pd.DataFrame(rows).to_csv(OUT / "b2_robust.csv", index=False)


def bootstrap(nav):
    """20 日移动块有放回抽样，循环衔接尾部；同一重排用于全部组合。"""
    returns = nav.pct_change(fill_method=None).dropna()
    log_returns = np.log1p(returns.to_numpy())
    n, portfolios = log_returns.shape
    rng = np.random.default_rng(0)
    mdds = np.empty((2000, portfolios))
    for start in range(0, 2000, 100):
        starts = rng.integers(0, n, size=(100, (n + 19) // 20))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
        for column in range(portfolios):
            paths = np.cumsum(log_returns[indices, column], axis=1)
            # 初始净值 1 也属于历史高点，避免漏掉首个下跌块。
            peaks = np.maximum(0, np.maximum.accumulate(paths, axis=1))
            mdds[start:start+100, column] = np.expm1((paths - peaks).min(axis=1))
    quantiles = np.quantile(mdds, [0.05, 0.5, 0.95], axis=0)
    result = pd.DataFrame({"name": nav.columns, "mdd_p05": quantiles[0],
                           "mdd_p50": quantiles[1], "mdd_p95": quantiles[2]})
    result.to_csv(OUT / "b2_bootstrap.csv", index=False)
    return result


def configure_fonts():
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})


def plot_heatmap(choice):
    grid = pd.read_csv(OUT / "b2_grid.csv")
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    for i, period in enumerate(("IS", "OOS")):
        for j, (key, label) in enumerate((("calmar", "Calmar"), ("max_drawdown", "最大回撤"))):
            table = grid[(grid.period == period) & (grid.base == "lowvol")].pivot(
                index="target_vol", columns="window", values=key).sort_index().sort_index(axis=1)
            ax = axes[i, j]
            image = ax.imshow(table.to_numpy(), aspect="auto", cmap="YlGnBu")
            fig.colorbar(image, ax=ax)
            ax.set_xticks(range(len(table.columns)), table.columns)
            ax.set_yticks(range(len(table.index)), [f"{value:.0%}" for value in table.index])
            ax.set_xlabel("实现波动窗口（交易日）")
            ax.set_ylabel("目标年化波动")
            ax.set_title(f"{'样本内 IS' if period == 'IS' else '样本外 OOS'}｜{label}")
            for row in range(len(table.index)):
                for col in range(len(table.columns)):
                    value = table.iloc[row, col]
                    ax.text(col, row, f"{value:.3f}" if key == "calmar" else f"{value:.1%}",
                            ha="center", va="center", color="black",
                            bbox={"facecolor": "white", "alpha": 0.65, "edgecolor": "none", "pad": 1})
            row = int(np.flatnonzero(np.isclose(table.index, choice["target_vol"]))[0])
            col = list(table.columns).index(choice["window"])
            ax.add_patch(Rectangle((col-0.5, row-0.5), 1, 1, fill=False, edgecolor="red", linewidth=3))
    fig.suptitle("低波动基础策略：波动率目标仓位｜选参只看样本内")
    fig.tight_layout()
    fig.savefig(OUT / "b2_heatmap.png", dpi=150)
    plt.close(fig)


def plot_nav(nav, choice):
    selected = f"{LOWVOL}_vt{choice['target_vol']*100:g}_L{choice['window']}_s0.1"
    labels = {LOWVOL: "低波动基础", selected: "低波动＋波动率目标", TIMING: "均线择时",
              INDEX: "中证800价格指数（不含分红）"}
    exposures = pd.read_parquet(ROOT / "reports/b2_final_full/exposure.parquet")
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    for name, label in labels.items():
        series = nav[name].dropna()
        line, = axes[0].plot(series.index, series / series.iloc[0], label=label)
        color = line.get_color()
        axes[1].plot(series.index, metrics.drawdown_series(series), color=color)
        exposure = pd.Series(1.0, index=series.index) if name == INDEX else exposures[name]
        axes[2].plot(exposure.index, exposure, color=color, alpha=0.8, linewidth=0.8)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("净值（对数）")
    axes[1].set_ylabel("回撤")
    axes[2].set_ylabel("仓位信号（exposure）")
    axes[2].set_ylim(-0.02, 1.05)
    axes[0].set_title("波动率目标仓位｜基准：000906.SH 价格指数｜选参只看样本内")
    axes[0].legend(loc="upper left", ncol=2)
    for axis in axes:
        axis.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.6)
        axis.grid(alpha=0.25)
    axes[0].annotate("样本内 ←｜→ 样本外", xy=(pd.Timestamp("2020-01-01"), 0.02),
                     xycoords=("data", "axes fraction"), ha="center")
    fig.tight_layout()
    fig.savefig(OUT / "b2_nav.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choose", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    benchmark = benchmark_prices()
    if args.choose:
        choose(benchmark)
        return
    choice = json.loads((OUT / "b2_choice.json").read_text())
    summary, nav = final_summary(benchmark)
    robustness()
    tag = f"_vt{choice['target_vol']*100:g}_L{choice['window']}_s0.1"
    resampled = bootstrap(nav[[LOWVOL, LOWVOL + tag, TIMING, NEUTRAL, NEUTRAL + tag, INDEX]])
    configure_fonts()
    plot_heatmap(choice)
    plot_nav(nav, choice)
    print("基准：000906.SH 价格指数；现金 2% 收益为估算；20 日块自助法 2000 次，种子 0。")
    print(summary[summary.period == "OOS"].to_string(index=False))
    print(resampled.to_string(index=False))


if __name__ == "__main__":
    main()
