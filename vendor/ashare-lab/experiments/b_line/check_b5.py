"""B5 验收：冲击模型关闭时与 B2/B3 一致、容量网格齐全、数值方向合理。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports"
B5 = R / "b5"
CASH = [1e7, 1e8, 1e9, 1e10]
STRATS = ["lowvol_vt", "b3_buf_vt", "lowvol"]
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["b5_capacity.csv", "b5_sens.csv", "b5_ref.csv", "b5_capacity.png"]:
    check((B5 / f).exists() and (B5 / f).stat().st_size > 0, f"缺少 reports/b5/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

# 1. 冲击关闭、1000 万、默认成本：与 B2/B3 报告逐位一致
ref = pd.read_csv(B5 / "b5_ref.csv")
b2 = pd.read_csv(R / "b2" / "b2_summary.csv")
b3 = pd.read_csv(R / "b3" / "b3_summary.csv")
want = {
    ("FULL", "lowvol_vt"): b2[(b2.period == "FULL") & (b2.name == "lowvol_W250_N50_vt16_L60_s0.1")].cagr,
    ("OOS", "lowvol_vt"): b2[(b2.period == "OOS") & (b2.name == "lowvol_W250_N50_vt16_L60_s0.1")].cagr,
    ("FULL", "b3_buf_vt"): b3[(b3.period == "FULL") & (b3.name == "b3_lv_q_v_buf_vt")].cagr,
    ("OOS", "b3_buf_vt"): b3[(b3.period == "OOS") & (b3.name == "b3_lv_q_v_buf_vt")].cagr,
}
for (p, s), v in want.items():
    hit = ref[(ref.period == p) & (ref.strategy == s)]
    check(len(v) == 1 and len(hit) == 1 and abs(hit.cagr.iloc[0] - v.iloc[0]) < 2e-6,
          f"b5_ref 与 B2/B3 不一致 {p} {s}")

# 2. 容量网格
c = pd.read_csv(B5 / "b5_capacity.csv")
need = {"period", "strategy", "cash", "cagr", "max_drawdown", "sharpe", "turnover", "cost_ratio",
        "impact_bp", "participation_p95", "cagr_drop"}
check(need <= set(c.columns), f"b5_capacity 缺列 {need - set(c.columns)}")
if need <= set(c.columns):
    for p in ("FULL", "OOS"):
        for s in STRATS:
            sub = c[(c.period == p) & (c.strategy == s)].sort_values("cash")
            check(list(sub.cash) == CASH, f"{p} {s} 资金档位不全")
            if len(sub) == 4:
                check((np.diff(sub.cagr) <= 0.003).all(), f"{p} {s} 年化随资金增加而明显上升，不合理")
                check((np.diff(sub.impact_bp) > 0).all(), f"{p} {s} 冲击应随资金单调上升")
                check(sub.impact_bp.iloc[0] < 15, f"{p} {s} 1000 万的冲击应小于 15bp")
                check(abs(sub.cagr_drop.iloc[0]) < 1e-12, "cagr_drop 以 1000 万为 0")
    check(c.participation_p95.between(0, 0.1 + 1e-9).all(), "单日成交占比不应超过 10% 上限")

s = pd.read_csv(B5 / "b5_sens.csv")
check({"strategy", "variant", "cagr", "impact_bp"} <= set(s.columns), "b5_sens 缺列")
check(len(s) >= 8, "b5_sens 应含 2 策略 × 4 变体")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: B5 验收全部通过")
