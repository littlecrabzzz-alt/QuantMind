"""CSCV / PBO（回测过拟合概率）的验收测试。"""
from math import comb

import numpy as np
import pandas as pd
import pytest

from ashare_lab.pbo import cscv_pbo


def test_exact_reversal_gives_pbo_one():
    # 两块：第一块 A>B>C，第二块 C>B>A；样本内最优在样本外总是最差
    def block(m):
        return [m - 0.01, m, m + 0.01]
    r = pd.DataFrame({
        "A": block(0.003) + block(0.001),
        "B": block(0.002) + block(0.002),
        "C": block(0.001) + block(0.003),
    })
    out = cscv_pbo(r, n_blocks=2)
    assert out["n_splits"] == 2
    assert out["pbo"] == pytest.approx(1.0)
    # 样本外排名 1/(N+1)：logit = ln(0.25/0.75)
    np.testing.assert_allclose(out["logits"], np.log(0.25 / 0.75))
    assert list(out["selected"]) == ["A", "C"]


def test_consistent_winner_gives_pbo_zero():
    rng = np.random.default_rng(1)
    r = pd.DataFrame(rng.normal(0, 0.01, (1600, 10)), columns=[f"s{i}" for i in range(10)])
    r["s0"] += 0.004
    out = cscv_pbo(r, n_blocks=8)
    assert out["n_splits"] == comb(8, 4)
    assert out["pbo"] == 0.0
    assert (out["selected"] == "s0").all()
    assert out["prob_oos_loss"] == 0.0


def test_pure_noise_pbo_near_half():
    # 单个种子的 PBO 波动很大（切分高度相关），用 20 个种子的均值检验
    values = []
    for seed in range(20):
        r = pd.DataFrame(np.random.default_rng(seed).normal(0, 0.01, (2000, 40)))
        out = cscv_pbo(r, n_blocks=10)
        values.append(out["pbo"])
    assert out["n_splits"] == comb(10, 5)
    assert 0.35 < np.mean(values) < 0.6
    assert len(out["logits"]) == out["n_splits"]
    assert len(out["is_metric"]) == len(out["oos_metric"]) == out["n_splits"]


def test_blocks_contiguous_and_validation():
    r = pd.DataFrame(np.random.default_rng(0).normal(0, 0.01, (101, 3)))
    out = cscv_pbo(r, n_blocks=4)
    assert out["n_splits"] == comb(4, 2)
    with pytest.raises(ValueError):
        cscv_pbo(r, n_blocks=5)          # 必须为偶数
    with pytest.raises(ValueError):
        cscv_pbo(r.iloc[:, :1], n_blocks=4)   # 至少 2 个配置
    with pytest.raises(ValueError):
        cscv_pbo(r.iloc[:6], n_blocks=4)      # 每块至少 2 个观测


def test_nan_rows_dropped_and_metric_is_sharpe():
    rng = np.random.default_rng(3)
    r = pd.DataFrame(rng.normal(0, 0.01, (400, 5)))
    r.iloc[10, 2] = np.nan
    out = cscv_pbo(r, n_blocks=4)
    assert out["n_obs"] == 399
    clean = r.dropna().reset_index(drop=True)
    blocks = np.array_split(np.arange(len(clean)), 4)
    first = out["splits"][0]                      # 第一个组合：前两块为样本内
    assert list(first) == [0, 1]
    is_rows = np.concatenate([blocks[i] for i in first])
    sub = clean.iloc[is_rows]
    sharpe = sub.mean() / sub.std(ddof=1) * np.sqrt(252)
    assert out["selected"].iloc[0] == sharpe.idxmax()
    assert out["is_metric"][0] == pytest.approx(sharpe.max())
