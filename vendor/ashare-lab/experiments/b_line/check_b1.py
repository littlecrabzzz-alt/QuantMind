"""B1 验收：回归（原低波动结果不变）+ 产出齐全 + 数值自洽。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


def row(summary, name):
    hit = summary[summary["name"] == name]
    check(len(hit) == 1, f"缺少或重复行 {name}")
    return hit.iloc[0] if len(hit) else None


# 1. 回归：与 05 号研究记录 final_* 完全一致（同一数据版本、同一引擎）
KNOWN = {
    "b1_is": {"lowvol_W250_N50": 0.154363, "all_W250_N50": 0.068012, "index:000906.SH": 0.075012},
    "b1_oos": {"lowvol_W250_N50": 0.103218, "all_W250_N50": 0.082593, "index:000906.SH": 0.018307},
    "b1_full": {"lowvol_W250_N50": 0.121139, "all_W250_N50": 0.068426, "index:000906.SH": 0.049797},
}
NEW = ["indneutral_count_W250_N50", "indneutral_cap_W250_N50", "indtilt_W250_N50"]
for exp, known in KNOWN.items():
    path = R / exp / "summary.csv"
    check(path.exists(), f"缺少 {path}")
    if not path.exists():
        continue
    s = pd.read_csv(path)
    for name, cagr in known.items():
        r = row(s, name)
        if r is not None:
            check(abs(r["cagr"] - cagr) < 2e-6, f"{exp} {name} cagr {r['cagr']:.6f} != {cagr}")
    for name in NEW:
        r = row(s, name)
        if r is not None:
            check(np.isfinite(r["cagr"]) and -0.9 < r["max_drawdown"] < 0, f"{exp} {name} 指标异常")
            check(0 < r["turnover"] < 20, f"{exp} {name} 换手异常 {r['turnover']}")
    check((R / exp / "nav.parquet").exists(), f"缺少 {exp}/nav.parquet")

# 2. 报告产出
B1 = R / "b1"
for f in ["b1_summary.csv", "b1_annual.csv", "b1_decomp.csv", "b1_industry_weights.csv",
          "b1_nav.png", "b1_industry.png"]:
    check((B1 / f).exists() and (B1 / f).stat().st_size > 0, f"缺少 reports/b1/{f}")

if (B1 / "b1_summary.csv").exists():
    s = pd.read_csv(B1 / "b1_summary.csv")
    need = {"period", "name", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar",
            "turnover", "alpha", "beta", "r2", "benchmark"}
    check(need <= set(s.columns), f"b1_summary 缺列 {need - set(s.columns)}")
    check(set(s["period"]) == {"IS", "OOS", "FULL"}, "b1_summary period 应为 IS/OOS/FULL")
    if need <= set(s.columns):
        check((s["benchmark"] == "000906.SH 价格指数").all(), "benchmark 列须注明 000906.SH 价格指数")
        idx = s[s["name"] == "index:000906.SH"]
        check(len(idx) == 3 and np.allclose(idx["beta"], 1, atol=1e-9)
              and np.allclose(idx["alpha"], 0, atol=1e-9), "指数自身 β 应为 1、α 为 0")
        strat = s[s["name"] != "index:000906.SH"]
        check(strat["beta"].between(0.2, 1.3).all(), "策略 β 超出合理范围")
        oos = s[(s["period"] == "OOS") & (s["name"] == "lowvol_W250_N50")]
        check(len(oos) == 1 and abs(oos["cagr"].iloc[0] - 0.103218) < 2e-6, "b1_summary 与回测不一致")

if (B1 / "b1_decomp.csv").exists():
    d = pd.read_csv(B1 / "b1_decomp.csv")
    need = {"period", "total", "selection", "allocation", "interaction"}
    check(need <= set(d.columns), f"b1_decomp 缺列 {need - set(d.columns)}")
    if need <= set(d.columns):
        check(set(d["period"]) == {"IS", "OOS", "FULL"}, "b1_decomp period 应为 IS/OOS/FULL")
        check(np.allclose(d["total"], d["selection"] + d["allocation"] + d["interaction"], atol=1e-10),
              "分解不可加")

if (B1 / "b1_industry_weights.csv").exists():
    w = pd.read_csv(B1 / "b1_industry_weights.csv")
    need = {"date", "portfolio", "industry", "weight"}
    check(need <= set(w.columns), f"b1_industry_weights 缺列 {need - set(w.columns)}")
    if need <= set(w.columns):
        check({"lowvol", "universe"} <= set(w["portfolio"]), "须含 lowvol 与 universe 两组权重")
        sums = w.groupby(["date", "portfolio"])["weight"].sum()
        check(np.allclose(sums, 1, atol=1e-8), "每期行业权重合计应为 1")
        check(w["date"].nunique() >= 170, "月度权重期数不足（2012-01 起每月一期）")

if fail:
    print("FAIL")
    print("\n".join(fail))
    sys.exit(1)
print("OK: B1 验收全部通过")
