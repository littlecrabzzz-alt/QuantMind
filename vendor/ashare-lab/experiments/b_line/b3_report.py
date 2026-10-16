"""B3 固定参数多因子研究：双基准归因、月度 IC、分组收益及覆盖率。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/b3"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ashare_lab import metrics
from ashare_lab.benchmark import benchmark_table, load_benchmarks
from ashare_lab.data.market import load_market_data
from ashare_lab.multifactor import GROUPS, composite
from ashare_lab.strategy import month_end_dates


STATS = ["cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover"]
FACTOR_NAMES = ["vol_250", "roe_ttm", "gm_std", "ep", "bp", "dy", "quality", "value", "lv_q_v"]


def final_summary(benchmarks):
    rows = []
    full_nav = None
    for period in ("IS", "OOS", "FULL"):
        source = ROOT / "reports" / f"b3_{period.lower()}"
        statistics = pd.read_csv(source / "summary.csv")
        nav = pd.read_parquet(source / "nav.parquet")
        for _, row in statistics.iterrows():
            name = row["name"]
            attribution = benchmark_table(nav[name].dropna(), benchmarks)
            price, tr = attribution.loc["000906.SH"], attribution.loc["000906.SH_TR"]
            stats = row[STATS].to_dict()
            if name == "index:000906.SH":
                stats["turnover"] = 0.0
            rows.append({"period": period, "name": name, **stats,
                         "alpha_price": price.alpha_ann, "beta_price": price.beta,
                         "alpha_tr": tr.alpha_ann, "beta_tr": tr.beta,
                         "excess_cagr_tr": tr.excess_cagr})
        if period == "FULL":
            full_nav = nav
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "b3_summary.csv", index=False)
    return summary, full_nav


def forward_returns():
    data = load_market_data("data/panel", "2010-01-01", "2026-09-30", universe="000906.SH")
    dates = month_end_dates(data.calendar)
    dates = dates[dates >= "2011-12-01"]
    # 不把缺失的月末价格前向填充为可实现的收益。
    prices = data.adj_close().loc[dates].where(data.close.loc[dates].notna())
    returns = prices.shift(-1) / prices - 1
    return returns.iloc[:-1]


def factor_diagnostics():
    returns = forward_returns()
    monthly_ic, monthly_deciles = [], []
    directions = {factor: sign for group in GROUPS.values() for factor, sign in group.items()}
    for version in ("pit", "naive"):
        factors = pd.read_parquet(OUT / f"factors_{version}.parquet")
        scores = factors.mul(pd.Series(directions))
        scores["quality"] = composite(factors, ["quality"])
        scores["value"] = composite(factors, ["value"])
        scores["lv_q_v"] = composite(factors, list(GROUPS))
        if version == "pit":
            coverage = scores.lv_q_v.notna().groupby(level="date").mean()
            coverage.groupby(coverage.index.year).mean().rename_axis("year").rename(
                "coverage"
            ).to_csv(OUT / "b3_coverage.csv")
        for date, frame in scores.groupby(level="date", sort=True):
            if date < pd.Timestamp("2012-01-01") or date not in returns.index:
                continue
            period = "IS" if date < pd.Timestamp("2020-01-01") else "OOS"
            frame = frame.droplevel("date")
            future = returns.loc[date].reindex(frame.index).rename("future")
            for factor in FACTOR_NAMES:
                paired = pd.concat([frame[factor], future], axis=1).dropna()
                # Pearson 相关作用于平均排名，等同截面 Spearman；平值截面无 IC。
                ranks = paired.rank(method="average")
                ic = (ranks[factor].corr(ranks.future)
                      if len(ranks) > 1 and ranks[factor].std() > 0 and ranks.future.std() > 0
                      else np.nan)
                monthly_ic.append({"date": date, "factor": factor, "version": version,
                                   "period": period, "ic": ic})
            if version == "pit":
                # 先用全部有分数的可选股票分组，再剔除缺失的下一月收益。
                signal = frame.lv_q_v.dropna().sort_index()
                if len(signal) >= 10:
                    decile = pd.qcut(signal.rank(method="first"), 10, labels=False) + 1
                    paired = pd.DataFrame({"decile": decile, "ret": future.reindex(signal.index)})
                    for bucket, ret in paired.dropna().groupby("decile").ret.mean().items():
                        monthly_deciles.append({"date": date, "period": period,
                                                "decile": int(bucket), "ret": ret})
    monthly = pd.DataFrame(monthly_ic)
    rows = []
    for (factor, version, period), frame in monthly.groupby(["factor", "version", "period"]):
        values = frame.ic.dropna()
        mean, std, n = values.mean(), values.std(ddof=1), len(values)
        ir = mean / std if std > 0 else np.nan
        rows.append({"factor": factor, "version": version, "period": period,
                     "ic_mean": mean, "ic_ir": ir, "t_stat": ir * np.sqrt(n), "n_months": n})
    ic = pd.DataFrame(rows)
    ic.to_csv(OUT / "b3_ic.csv", index=False)
    deciles = pd.DataFrame(monthly_deciles).groupby(["period", "decile"]).ret.agg(
        mean_ret="mean", n_months="count"
    ).reset_index()
    deciles.to_csv(OUT / "b3_deciles.csv", index=False)
    return ic


def configure_fonts():
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})


def plot_nav(nav, benchmarks):
    labels = {
        "lowvol_W250_N50": "低波动基础",
        "lowvol_W250_N50_vt16_L60_s0.1": "低波动＋波动率目标",
        "b3_lv_q_v": "低波＋质量＋价值",
        "b3_lv_q_v_buf": "三因子＋排名缓冲",
        "b3_lv_q_v_buf_vt": "三因子＋缓冲＋波动率目标",
        "000906.SH_TR": "中证800全收益基准",
    }
    nav = nav.assign(**{"000906.SH_TR": benchmarks["000906.SH_TR"].reindex(nav.index)})
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for name, label in labels.items():
        series = nav[name].dropna()
        line, = axes[0].plot(series.index, series / series.iloc[0], label=label)
        axes[1].plot(series.index, metrics.drawdown_series(series), color=line.get_color())
    axes[0].set_yscale("log")
    axes[0].set_ylabel("净值（对数）")
    axes[1].set_ylabel("回撤")
    axes[0].set_title("B3 多因子研究｜公告日 PIT｜参数事先固定")
    axes[0].legend(loc="upper left", ncol=2)
    for axis in axes:
        axis.axvline(pd.Timestamp("2020-01-01"), color="black", linestyle="--", alpha=0.6)
        axis.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "b3_nav.png", dpi=150)
    plt.close(fig)


def plot_ic(ic):
    labels = ["低波动", "ROE", "毛利率稳定性", "EP", "BP", "股息率", "质量组", "价值组", "三组合成"]
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    x = np.arange(len(FACTOR_NAMES))
    for axis, period in zip(axes, ("IS", "OOS")):
        for offset, version in ((-0.2, "pit"), (0.2, "naive")):
            values = ic[(ic.period == period) & (ic.version == version)].set_index(
                "factor"
            ).ic_mean.reindex(FACTOR_NAMES)
            axis.bar(x + offset, values, width=0.4, label=version.upper())
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_ylabel("月度 Rank IC 均值")
        axis.set_title("样本内 IS" if period == "IS" else "样本外 OOS")
        axis.legend()
        axis.grid(axis="y", alpha=0.25)
    axes[-1].set_xticks(x, labels)
    fig.suptitle("B3 因子预测力｜已统一因子方向｜PIT 与 naive 对照")
    fig.tight_layout()
    fig.savefig(OUT / "b3_ic.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    benchmarks = load_benchmarks("data/benchmarks")
    summary, nav = final_summary(benchmarks)
    ic = factor_diagnostics()
    configure_fonts()
    plot_nav(nav, benchmarks)
    plot_ic(ic)
    print(summary[summary.period == "OOS"].to_string(index=False))
    print(ic[ic.version == "pit"].to_string(index=False))


if __name__ == "__main__":
    main()
