"""波动率目标减仓时点检验的验收。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports"
V = R / "vtcut"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["vtcut_summary.csv", "vtcut_events.csv", "vtcut_pbo.csv", "vtcut_events.png", "vtcut_nav.png"]:
    check((V / f).exists() and (V / f).stat().st_size > 0, f"缺少 reports/vtcut/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

VARIANTS = {"none", "base", "delay1", "delay3", "delay5", "half", "win120", "downside"}
PERIODS = {"2012-2019", "2020-2026", "2012-2026"}
s = pd.read_csv(V / "vtcut_summary.csv")
need = {"base", "variant", "period", "cagr", "max_drawdown", "sharpe", "turnover", "avg_exposure"}
check(need <= set(s.columns), f"vtcut_summary 缺列 {need - set(s.columns)}")
if need <= set(s.columns):
    for b in ("lowvol", "b3"):
        for v in VARIANTS:
            for p in PERIODS:
                check(len(s[(s.base == b) & (s.variant == v) & (s.period == p)]) == 1, f"缺 {b} {v} {p}")
    b2 = pd.read_csv(R / "b2" / "b2_summary.csv")
    b3 = pd.read_csv(R / "b3" / "b3_summary.csv")
    known = {("lowvol", "base"): b2[(b2.period == "FULL") & (b2.name == "lowvol_W250_N50_vt16_L60_s0.1")].cagr,
             ("lowvol", "none"): b2[(b2.period == "FULL") & (b2.name == "lowvol_W250_N50")].cagr,
             ("b3", "base"): b3[(b3.period == "FULL") & (b3.name == "b3_lv_q_v_buf_vt")].cagr,
             ("b3", "none"): b3[(b3.period == "FULL") & (b3.name == "b3_lv_q_v_buf")].cagr}
    for (b, v), want in known.items():
        hit = s[(s.base == b) & (s.variant == v) & (s.period == "2012-2026")]
        check(len(want) == 1 and len(hit) == 1 and abs(hit.cagr.iloc[0] - want.iloc[0]) < 2e-6,
              f"回归不一致 {b} {v}")
    check(np.allclose(s[s.variant == "none"].avg_exposure, 1.0), "不加仓位控制的平均仓位应为 1")

e = pd.read_csv(V / "vtcut_events.csv")
need = {"base", "period", "event_type", "h", "n_events", "fwd_mean", "uncond_mean", "frac_pos",
        "p_value", "missed_gain", "avoided_loss"}
check(need <= set(e.columns), f"vtcut_events 缺列 {need - set(e.columns)}")
if need <= set(e.columns):
    for b in ("lowvol", "b3"):
        for p in PERIODS:
            for t in ("all_cuts", "top10_cuts", "cuts_after_drop"):
                for h in (5, 10, 20):
                    check(len(e[(e.base == b) & (e.period == p) & (e.event_type == t) & (e.h == h)]) == 1,
                          f"缺事件 {b} {p} {t} {h}")
    check(e.p_value.dropna().between(0, 1).all(), "p 值应在 [0,1]")
    check((e.missed_gain >= 0).all() and (e.avoided_loss >= 0).all(), "错过收益、避免损失记为非负")
    full = e[(e.period == "2012-2026") & (e.event_type == "all_cuts")]
    check((full.n_events > 0).all(), "全区间应有减仓事件")

pb = pd.read_csv(V / "vtcut_pbo.csv")
check({"base", "n_configs", "n_blocks", "pbo"} <= set(pb.columns), "vtcut_pbo 缺列")
check(len(pb) >= 4 and pb.pbo.between(0, 1).all(), "PBO 应含 2 个底仓 × S=10/16")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: VTCUT 验收全部通过")
