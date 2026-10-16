"""社区第 2、7 条（指数均线择时）复现验收。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports" / "c27"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["c27_summary.csv", "c27_index_pe.csv", "c27_nav.png"]:
    check((R / f).exists() and (R / f).stat().st_size > 0, f"缺少 reports/c27/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

s = pd.read_csv(R / "c27_summary.csv")
need = {"index", "rule", "period", "cagr", "max_drawdown", "sharpe", "avg_exposure",
        "trades_per_year", "win_rate", "payoff", "rel_underperf_years", "cagr_cash2pct"}
check(need <= set(s.columns), f"c27_summary 缺列 {need - set(s.columns)}")
rules = {"hold", "ma250", "ma182", "ma250_dip_exit", "ma250_dip_buy", "ma182_pe"}
if need <= set(s.columns):
    for ix in ("000300.SH", "000905.SH", "000852.SH", "000906.SH"):
        for r in rules:
            for p in ("IS", "OOS", "FULL"):
                check(len(s[(s["index"] == ix) & (s.rule == r) & (s.period == p)]) == 1, f"缺 {ix} {r} {p}")
    h = s[s.rule == "hold"]
    check(np.allclose(h.avg_exposure, 1) and np.allclose(h.rel_underperf_years, 0), "持有组仓位应为 1、相对跑输为 0")
    check(s.avg_exposure.between(0, 1).all(), "平均仓位应在 [0,1]")
    check((s.max_drawdown.lt(0) | s.avg_exposure.eq(0)).all(), "回撤应为负（从未持仓的规则除外）")

pe = pd.read_csv(R / "c27_index_pe.csv")
check({"date", "index", "pe"} <= set(pe.columns), "c27_index_pe 缺列")
if {"date", "index", "pe"} <= set(pe.columns):
    v = pe[pe["index"] == "000300.SH"].pe
    check(v.between(5, 40).mean() > 0.95, "沪深 300 的 PE 应大多在 5–40 之间")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: C27 验收全部通过")
