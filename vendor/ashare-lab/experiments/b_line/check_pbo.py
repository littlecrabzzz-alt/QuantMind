"""CSCV/PBO 审计验收。"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2] / "reports" / "pbo"
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


for f in ["pbo_summary.csv", "pbo_logits.png", "pbo_is_oos.png", "returns_ma_grid.parquet",
          "returns_vt_grid.parquet"]:
    check((R / f).exists() and (R / f).stat().st_size > 0, f"缺少 reports/pbo/{f}")
if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)

ma = pd.read_parquet(R / "returns_ma_grid.parquet")
vt = pd.read_parquet(R / "returns_vt_grid.parquet")
check(ma.shape[1] == 54, f"均线择时网格应有 54 列，实际 {ma.shape[1]}")
check(vt.shape[1] == 20, f"波动率目标网格应有 20 列，实际 {vt.shape[1]}")
for name, frame in (("ma", ma), ("vt", vt)):
    check(frame.index.min() <= pd.Timestamp("2012-01-06") and frame.index.max() >= pd.Timestamp("2026-09-29"),
          f"{name} 日收益应覆盖 2012-01 至 2026-09")
    check(frame.abs().max().max() < 0.2, f"{name} 日收益出现异常值")

s = pd.read_csv(R / "pbo_summary.csv")
need = {"set", "n_configs", "n_blocks", "n_splits", "pbo", "prob_oos_loss", "degradation_slope",
        "median_logit", "chosen_is_rank"}
check(need <= set(s.columns), f"pbo_summary 缺列 {need - set(s.columns)}")
if need <= set(s.columns):
    for st in ("ma_grid", "vt_grid", "combined"):
        for nb in (10, 16):
            check(len(s[(s.set == st) & (s.n_blocks == nb)]) == 1, f"pbo_summary 缺 {st} S={nb}")
    check(s.pbo.between(0, 1).all(), "PBO 应在 [0,1]")
    check((s[s.n_blocks == 16].n_splits == 12870).all(), "S=16 应有 C(16,8)=12870 种切分")
    check((s[s.set == "ma_grid"].n_configs == 54).all() and (s[s.set == "vt_grid"].n_configs == 20).all(),
          "配置数不对")
    check((s[s.set == "combined"].n_configs >= 80).all(), "combined 应含均线网格、波动率网格、B1、B3 组合")

if fail:
    print("FAIL\n" + "\n".join(fail))
    sys.exit(1)
print("OK: PBO 验收全部通过")
