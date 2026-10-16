"""全区间候选的 CSCV / PBO 审计：均线网格、波动率网格及合并集合。"""

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports/pbo"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / ".matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ashare_lab.pbo import cscv_pbo


LABELS = {"ma_grid": "低波动＋均线择时", "vt_grid": "低波动＋波动率目标",
          "combined": "全部候选组合"}
CHOSEN = {"ma_grid": "lowvol_W250_N50_L60_e0.3",
          "vt_grid": "lowvol_W250_N50_vt16_L60_s0.1",
          "combined": "lowvol_W250_N50_vt16_L60_s0.1"}


def daily_returns(experiment):
    nav = pd.read_parquet(ROOT / "reports" / experiment / "nav.parquet")
    nav = nav.loc[:, ~nav.columns.str.startswith("index:")]
    return nav.pct_change(fill_method=None).dropna(how="any")


def configure_fonts():
    available = {font.name for font in font_manager.fontManager.ttflist}
    fonts = [font for font in ("PingFang SC", "Hiragino Sans GB", "Arial Unicode MS")
             if font in available]
    if not fonts:
        raise RuntimeError("缺少中文字体：PingFang SC / Hiragino Sans GB / Arial Unicode MS")
    plt.rcParams.update({"font.sans-serif": fonts, "axes.unicode_minus": False})


def plot_results(results):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for axis, (name, result) in zip(axes, results.items()):
        axis.hist(result["logits"], bins=40, alpha=0.8)
        axis.axvline(0, color="black", linestyle="--")
        axis.set_title(f"{LABELS[name]}｜PBO={result['pbo']:.1%}")
        axis.set_xlabel("样本外排名 logit λ")
        axis.set_ylabel("切分数")
        axis.grid(alpha=0.25)
    fig.suptitle("CSCV 回测过拟合概率｜S=16")
    fig.tight_layout()
    fig.savefig(OUT / "pbo_logits.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    rng = np.random.default_rng(0)
    for axis, (name, result) in zip(axes, results.items()):
        x, y = result["is_metric"], result["oos_metric"]
        sample = rng.choice(len(x), size=min(3000, len(x)), replace=False)
        axis.scatter(x[sample], y[sample], s=6, alpha=0.2)
        slope = result["degradation_slope"]
        line_x = np.array([x.min(), x.max()])
        axis.plot(line_x, y.mean() + slope * (line_x - x.mean()), color="red",
                  label=f"OLS 斜率={slope:.3f}")
        axis.axhline(0, color="black", linestyle="--", linewidth=0.8)
        axis.set_title(LABELS[name])
        axis.set_xlabel("样本内年化夏普")
        axis.set_ylabel("样本外年化夏普")
        axis.legend()
        axis.grid(alpha=0.25)
    fig.suptitle("CSCV 绩效衰减｜S=16｜回归使用全部切分")
    fig.tight_layout()
    fig.savefig(OUT / "pbo_is_oos.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ma = daily_returns("pbo_ma_grid")
    vt = daily_returns("pbo_vt_grid")
    ma.to_parquet(OUT / "returns_ma_grid.parquet")
    vt.to_parquet(OUT / "returns_vt_grid.parquet")
    combined = pd.concat([ma, vt, daily_returns("b1_full"), daily_returns("b3_full")], axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()].dropna(how="any")
    rows, results = [], {}
    for name, returns in (("ma_grid", ma), ("vt_grid", vt), ("combined", combined)):
        sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
        chosen_rank = float(sharpe.rank(ascending=False, method="average")[CHOSEN[name]])
        for n_blocks in (10, 16):
            result = cscv_pbo(returns, n_blocks=n_blocks)
            rows.append({"set": name, "n_configs": returns.shape[1], "n_blocks": n_blocks,
                         "n_splits": result["n_splits"], "n_obs": result["n_obs"],
                         "pbo": result["pbo"], "prob_oos_loss": result["prob_oos_loss"],
                         "degradation_slope": result["degradation_slope"],
                         "median_logit": float(np.median(result["logits"])),
                         "chosen_is_rank": chosen_rank})
            if n_blocks == 16:
                results[name] = result
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "pbo_summary.csv", index=False)
    configure_fonts()
    plot_results(results)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
