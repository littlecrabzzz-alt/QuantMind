"""社区第 6 条（PE/PB 历史分位）复现的验收。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports" / "c6"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["c6_summary.csv", "c6_grid.csv", "c6_nav.png", "c6_grid.png"]:
    check((R / f).exists() and (R / f).stat().st_size > 0, f"缺少 reports/c6/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

s = pd.read_csv(R / "c6_summary.csv")
need = {"period", "name", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover",
        "alpha_price", "beta_price", "alpha_tr", "beta_tr", "excess_cagr_tr"}
check(need <= set(s.columns), f"c6_summary 缺列 {need - set(s.columns)}")
check(set(s.period) == {"2015-2019", "2020-2026", "2015-2026"}, "区间应为 2015-2019 / 2020-2026 / 2015-2026")
names = {"pe_pct_W60_N50", "pb_pct_W60_N50", "ep_xs_N50", "bp_xs_N50", "all_eq", "lowvol_W250_N50",
         "index:000906.SH"}
for p in ("2015-2019", "2020-2026", "2015-2026"):
    for n in names:
        check(len(s[(s.period == p) & (s.name == n)]) == 1, f"c6_summary 缺 {p} {n}")

g = pd.read_csv(R / "c6_grid.csv")
need = {"metric", "window", "top_n", "period", "cagr", "max_drawdown", "sharpe", "turnover"}
check(need <= set(g.columns), f"c6_grid 缺列 {need - set(g.columns)}")
if need <= set(g.columns):
    for m in ("pe", "pb"):
        for w in (36, 60):
            for n in (10, 20, 50, 100):
                check(len(g[(g.metric == m) & (g.window == w) & (g.top_n == n)]) == 3,
                      f"c6_grid 缺 {m} W{w} N{n}")
    check(g.max_drawdown.lt(0).all() and g.turnover.between(0.1, 30).all(), "网格指标异常")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: C6 验收全部通过")
