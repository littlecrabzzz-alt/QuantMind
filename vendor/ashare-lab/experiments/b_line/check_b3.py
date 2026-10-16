"""B3 验收：回归、产出齐全、PIT/对照组都在、数值自洽。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports"
B3 = R / "b3"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["factors_pit.parquet", "factors_naive.parquet", "b3_summary.csv", "b3_ic.csv",
          "b3_deciles.csv", "b3_coverage.csv", "b3_nav.png", "b3_ic.png"]:
    check((B3 / f).exists() and (B3 / f).stat().st_size > 0, f"缺少 reports/b3/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

fp = pd.read_parquet(B3 / "factors_pit.parquet")
check({"vol_250", "roe_ttm", "gm_std", "ep", "bp", "dy"} <= set(fp.columns), "因子列不全")
dates = pd.DatetimeIndex(fp.index.get_level_values("date").unique())
check(dates.min() <= pd.Timestamp("2012-01-31") and dates.max() >= pd.Timestamp("2026-08-31"),
      "因子日期应覆盖 2012-01 至 2026-08 每个月末")
check(len(dates) >= 176, "月末期数不足")

NAMES = ["b3_lowvol", "b3_quality", "b3_value", "b3_lv_q", "b3_lv_v", "b3_lv_q_v",
         "b3_lv_q_v_buf", "b3_lv_q_v_naive", "b3_lv_q_v_buf_vt", "lowvol_W250_N50",
         "lowvol_W250_N50_vt16_L60_s0.1", "index:000906.SH"]
s = pd.read_csv(B3 / "b3_summary.csv")
need = {"period", "name", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar", "turnover",
        "alpha_price", "beta_price", "alpha_tr", "beta_tr", "excess_cagr_tr"}
check(need <= set(s.columns), f"b3_summary 缺列 {need - set(s.columns)}")
for p in ("IS", "OOS", "FULL"):
    for n in NAMES:
        check(len(s[(s.period == p) & (s.name == n)]) == 1, f"b3_summary 缺 {p} {n}")
known = {("IS", "lowvol_W250_N50"): 0.154363, ("OOS", "lowvol_W250_N50"): 0.103218,
         ("FULL", "lowvol_W250_N50"): 0.121139}
for (p, n), v in known.items():
    hit = s[(s.period == p) & (s.name == n)]
    check(len(hit) == 1 and abs(hit.cagr.iloc[0] - v) < 2e-6, f"回归不一致 {p} {n}")
    # 只用低波一组的合成打分必须与原策略逐位一致
    hit2 = s[(s.period == p) & (s.name == "b3_lowvol")]
    check(len(hit2) == 1 and abs(hit2.cagr.iloc[0] - v) < 2e-6, f"b3_lowvol 与原低波动不一致 {p}")
if need <= set(s.columns):
    idx = s[s.name == "index:000906.SH"]
    check(np.allclose(idx.beta_price, 1, atol=1e-9) and np.allclose(idx.alpha_price, 0, atol=1e-9),
          "价格指数对自身 β=1、α=0")
    check((s.loc[s.name != "index:000906.SH", "turnover"].between(0.1, 30)).all(), "换手异常")

ic = pd.read_csv(B3 / "b3_ic.csv")
need = {"factor", "version", "period", "ic_mean", "ic_ir", "t_stat", "n_months"}
check(need <= set(ic.columns), f"b3_ic 缺列 {need - set(ic.columns)}")
if need <= set(ic.columns):
    for fct in ["vol_250", "roe_ttm", "gm_std", "ep", "bp", "dy", "quality", "value", "lv_q_v"]:
        for ver in ("pit", "naive"):
            for p in ("IS", "OOS"):
                check(len(ic[(ic.factor == fct) & (ic.version == ver) & (ic.period == p)]) == 1,
                      f"b3_ic 缺 {fct}/{ver}/{p}")
    v = ic[ic.factor == "vol_250"]
    check(np.allclose(v[v.version == "pit"].sort_values("period").ic_mean,
                      v[v.version == "naive"].sort_values("period").ic_mean), "低波因子与财务无关，PIT/naive 应一致")
    check(ic.n_months.between(80, 100).all(), "IS 约 95 个月、OOS 约 80 个月")

dc = pd.read_csv(B3 / "b3_deciles.csv")
check({"period", "decile", "mean_ret", "n_months"} <= set(dc.columns), "b3_deciles 缺列")
check(set(dc.decile) == set(range(1, 11)), "应有 1–10 组")

cv = pd.read_csv(B3 / "b3_coverage.csv")
check({"year", "coverage"} <= set(cv.columns), "b3_coverage 缺列")
check(cv.coverage.between(0, 1).all() and cv.coverage.mean() > 0.8, "三组因子都有值的覆盖率应 > 80%")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: B3 验收全部通过")
