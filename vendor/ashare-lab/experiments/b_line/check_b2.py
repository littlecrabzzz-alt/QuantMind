"""B2 验收：网格齐全、选参只用样本内、回归一致、产出齐全。"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports"
B2 = R / "b2"
TARGETS = [0.08, 0.10, 0.12, 0.14, 0.16]
WINDOWS = [10, 20, 40, 60]
BASES = {"lowvol", "indneutral_count"}
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["b2_grid.csv", "b2_choice.json", "b2_summary.csv", "b2_robust.csv", "b2_bootstrap.csv",
          "b2_heatmap.png", "b2_nav.png"]:
    check((B2 / f).exists() and (B2 / f).stat().st_size > 0, f"缺少 reports/b2/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

g = pd.read_csv(B2 / "b2_grid.csv")
need = {"period", "base", "target_vol", "window", "cagr", "max_drawdown", "sharpe", "calmar",
        "turnover", "avg_exposure", "alpha", "beta"}
check(need <= set(g.columns), f"b2_grid 缺列 {need - set(g.columns)}")
check(set(g["period"]) == {"IS", "OOS"}, "b2_grid period 应为 IS/OOS")
check(set(g["base"]) == BASES, f"b2_grid base 应为 {BASES}")
for (p, b), sub in g.groupby(["period", "base"]):
    cells = set(zip(sub["target_vol"].round(4), sub["window"]))
    check(cells == {(round(t, 4), w) for t in TARGETS for w in WINDOWS} and len(sub) == 20,
          f"{p}/{b} 网格不完整")
check(g["avg_exposure"].between(0.05, 1.0).all(), "平均仓位超出 (0.05, 1]")
check((g["max_drawdown"] < 0).all(), "回撤应为负")

# 选参规则：样本内、base=lowvol，3x3 邻域（含自身，边界只用存在的格）Calmar 均值最大
c = json.loads((B2 / "b2_choice.json").read_text())
check({"target_vol", "window", "rule"} <= set(c), "b2_choice.json 缺字段")
is_lv = g[(g.period == "IS") & (g.base == "lowvol")].pivot(index="target_vol", columns="window", values="calmar")
is_lv = is_lv.reindex(index=sorted(is_lv.index), columns=sorted(is_lv.columns))
arr = is_lv.to_numpy()
score = np.full(arr.shape, np.nan)
for i in range(arr.shape[0]):
    for j in range(arr.shape[1]):
        score[i, j] = np.nanmean(arr[max(0, i - 1):i + 2, max(0, j - 1):j + 2])
i, j = np.unravel_index(np.nanargmax(score), score.shape)
want = (round(float(is_lv.index[i]), 4), int(is_lv.columns[j]))
check((round(float(c["target_vol"]), 4), int(c["window"])) == want,
      f"选参与样本内邻域规则不符：选了 {(c['target_vol'], c['window'])}，规则给出 {want}")

s = pd.read_csv(B2 / "b2_summary.csv")
need = {"period", "name", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover",
        "avg_exposure", "alpha", "beta", "benchmark", "cagr_cash2pct"}
check(need <= set(s.columns), f"b2_summary 缺列 {need - set(s.columns)}")
check(set(s["period"]) == {"IS", "OOS", "FULL"}, "b2_summary period 应为 IS/OOS/FULL")
if need <= set(s.columns):
    check((s["benchmark"] == "000906.SH 价格指数").all(), "benchmark 须注明 000906.SH 价格指数")
    known = {("OOS", "lowvol_W250_N50"): 0.103218, ("IS", "lowvol_W250_N50"): 0.154363,
             ("FULL", "lowvol_W250_N50"): 0.121139, ("OOS", "lowvol_W250_N50_L60_e0.3"): 0.038135}
    for (p, n), v in known.items():
        hit = s[(s.period == p) & (s.name == n)]
        check(len(hit) == 1 and abs(hit["cagr"].iloc[0] - v) < 2e-6, f"回归不一致 {p} {n}")
    tag = f"_vt{c['target_vol'] * 100:g}_L{int(c['window'])}_s0.1"
    for p in ("IS", "OOS", "FULL"):
        for b in ("lowvol_W250_N50", "indneutral_count_W250_N50"):
            check(len(s[(s.period == p) & (s.name == b + tag)]) == 1, f"b2_summary 缺 {p} {b + tag}")
    check((s["cagr_cash2pct"] >= s["cagr"] - 1e-12).all(), "现金收益调整后年化不应更低")

r = pd.read_csv(B2 / "b2_robust.csv")
check({"variant", "period", "cagr", "max_drawdown", "calmar", "turnover"} <= set(r.columns), "b2_robust 缺列")
check(len(r) >= 6, "b2_robust 至少含 step 0.05/0.2、滑点 20bp 三种 × IS/OOS")

b = pd.read_csv(B2 / "b2_bootstrap.csv")
check({"name", "mdd_p05", "mdd_p50", "mdd_p95"} <= set(b.columns), "b2_bootstrap 缺列")
check((b["mdd_p05"] <= b["mdd_p50"]).all() and (b["mdd_p50"] <= b["mdd_p95"]).all(), "自助法分位顺序错误")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: B2 验收全部通过")
