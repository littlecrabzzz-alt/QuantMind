"""B1 行业中性低波动研究；基准为不含分红的中证 800 价格指数。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports" / "b1"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ashare_lab import metrics
from ashare_lab.attribution import alpha_beta
from ashare_lab.data.market import load_market_data
from ashare_lab.industry import industry_at
from ashare_lab.strategies import IndustryLowVol, LowVolTrend


LOWVOL = "lowvol_W250_N50"
ALL = "all_W250_N50"
NEUTRAL = "indneutral_count_W250_N50"
TILT = "indtilt_W250_N50"
LABELS = {
    LOWVOL: "低波动",
    ALL: "成分等权",
    NEUTRAL: "行业中性（数量）",
    "indneutral_cap_W250_N50": "行业中性（市值）",
    TILT: "行业倾斜",
    "index:000906.SH": "中证800价格指数（不含分红）",
}


def industry_weights(data, industry):
    """直接重算月末目标权重；universe 对应有效波动率候选集合 E。"""
    parameters = dict(vol_window=250, top_n=50, timing_index=None)
    strategies = {
        "lowvol": LowVolTrend(**parameters),
        "universe": LowVolTrend(select="all", **parameters),
        "indneutral_count": IndustryLowVol(industry=industry, **parameters),
    }
    calendar = data.calendar[(data.calendar >= "2012-01-01") &
                             (data.calendar <= "2026-09-30")]
    rows = []
    for t in strategies["lowvol"].rebalance_dates(calendar):
        history = data.truncate(t)
        for portfolio, strategy in strategies.items():
            weights = strategy.target_weights(t, history)
            groups = industry_at(t, industry, weights.index)
            grouped = weights.groupby(groups).sum()
            rows.extend({"date": t, "portfolio": portfolio, "industry": group,
                         "weight": weight} for group, weight in grouped.items())
    return pd.DataFrame(rows)


def plot_nav(nav):
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    for name, series in nav.items():
        axes[0].plot(series.index, series / series.iloc[0], label=LABELS[name])
        axes[1].plot(series.index, metrics.drawdown_series(series))
    axes[0].set_yscale("log")
    axes[0].set_ylabel("净值（对数）")
    axes[1].set_ylabel("回撤")
    axes[0].set_title("行业中性低波动研究｜基准：000906.SH 价格指数（不含分红）")
    axes[0].legend(loc="upper left", ncol=2)
    for axis in axes:
        axis.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.6)
        axis.grid(alpha=0.25)
    axes[0].annotate("样本内 ←｜→ 样本外", xy=(pd.Timestamp("2020-01-01"), 0.02),
                     xycoords=("data", "axes fraction"), ha="center")
    fig.tight_layout()
    fig.savefig(OUT / "b1_nav.png", dpi=150)
    plt.close(fig)


def plot_industry(weights):
    wide = weights.pivot_table(index="date", columns=["portfolio", "industry"],
                               values="weight", fill_value=0)
    low = wide["lowvol"]
    universe = wide["universe"]
    industries = low.columns.union(universe.columns)
    low = low.reindex(columns=industries, fill_value=0)
    universe = universe.reindex(columns=industries, fill_value=0)
    leaders = low.mean().nlargest(8).index
    stacked = low[leaders].copy()
    stacked["其他"] = low.drop(columns=leaders).sum(axis=1)
    deviation = low - universe
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    axes[0].stackplot(stacked.index, *stacked.to_numpy().T,
                      labels=stacked.columns, colors=plt.get_cmap("tab20").colors[:9])
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("目标行业权重")
    axes[0].set_title("低波动组合行业配置（平均权重前八行业）")
    axes[0].legend(loc="upper left", ncol=5)
    axes[1].plot(deviation.index, 0.5 * deviation.abs().sum(axis=1), label="行业偏离度")
    for industry in ("银行", "公用事业"):
        excess = deviation[industry] if industry in deviation else pd.Series(0.0, index=deviation.index)
        axes[1].plot(excess.index, excess, label=f"{industry}超配幅度")
    axes[1].axhline(0, color="black", linewidth=0.7)
    axes[1].set_ylabel("相对候选集合等权的偏离")
    axes[1].legend()
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "b1_industry.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})
    data = load_market_data(ROOT / "data/panel", "2010-01-01", "2026-09-30",
                            universe="000906.SH")
    columns = ["cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover"]
    summaries, decompositions = [], []
    full_nav = None
    for period in ("IS", "OOS", "FULL"):
        source = ROOT / "reports" / f"b1_{period.lower()}"
        statistics = pd.read_csv(source / "summary.csv").set_index("name")
        nav = pd.read_parquet(source / "nav.parquet")
        benchmark = data.index_close["000906.SH"].loc[nav.index[0]:nav.index[-1]]
        for name, series in nav.items():
            attribution = alpha_beta(series, benchmark)
            summaries.append({"period": period, "name": name,
                              **statistics.loc[name, columns].to_dict(),
                              **{key: attribution[key] for key in ("alpha", "beta", "r2", "resid_vol")},
                              "benchmark": "000906.SH 价格指数"})
        returns = nav[[LOWVOL, ALL, NEUTRAL, TILT]].pct_change(fill_method=None).dropna()
        total = (returns[LOWVOL] - returns[ALL]).mean() * 252
        selection = (returns[NEUTRAL] - returns[ALL]).mean() * 252
        allocation = (returns[TILT] - returns[ALL]).mean() * 252
        decompositions.append(dict(period=period, total=total, selection=selection,
                                   allocation=allocation, interaction=total-selection-allocation))
        if period == "FULL":
            full_nav = nav
    summary = pd.DataFrame(summaries)
    decomp = pd.DataFrame(decompositions)
    summary.to_csv(OUT / "b1_summary.csv", index=False)
    decomp.to_csv(OUT / "b1_decomp.csv", index=False)
    pd.DataFrame({name: metrics.annual_returns(series) for name, series in full_nav.items()})\
        .rename_axis("year").to_csv(OUT / "b1_annual.csv")
    industry = pd.read_parquet(ROOT / "data/panel/industry.parquet")
    weights = industry_weights(data, industry)
    weights.to_csv(OUT / "b1_industry_weights.csv", index=False, date_format="%Y-%m-%d")
    plot_nav(full_nav)
    plot_industry(weights)
    print("基准：000906.SH 价格指数（不含分红）；分解口径：日超额收益均值 × 252。")
    print(summary[summary.period == "OOS"].to_string(index=False))
    print(decomp.to_string(index=False))


if __name__ == "__main__":
    main()
