"""对基准的 α/β 验收测试。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.attribution import alpha_beta

IDX = pd.bdate_range("2020-01-01", periods=300)


def nav_from(returns, index):
    return pd.Series(np.cumprod(1 + np.asarray(returns)), index=index)


def test_exact_linear_relation():
    rng = np.random.default_rng(0)
    rb = rng.normal(0, 0.01, len(IDX))
    rp = 0.0001 + 1.5 * rb
    out = alpha_beta(nav_from(rp, IDX), nav_from(rb, IDX))
    assert out["beta"] == pytest.approx(1.5, abs=1e-10)
    assert out["alpha"] == pytest.approx(0.0001 * 252, abs=1e-10)
    assert out["r2"] == pytest.approx(1.0, abs=1e-10)
    assert out["n_obs"] == len(IDX) - 1


def test_aligns_on_common_dates_and_drops_gaps():
    rng = np.random.default_rng(1)
    rb = rng.normal(0, 0.01, len(IDX))
    rp = -0.0002 + 0.6 * rb
    port = nav_from(rp, IDX)
    bench = nav_from(rb, IDX)
    # 基准多出前后各 20 天，组合中间有一段缺失：只用两边都有的日收益
    extra = pd.bdate_range(IDX[0] - pd.Timedelta(days=40), periods=20)
    bench_long = pd.concat([pd.Series(1.0, index=extra), bench])
    port_gap = port.copy()
    port_gap.iloc[100:105] = np.nan
    out = alpha_beta(port_gap, bench_long)
    assert out["beta"] == pytest.approx(0.6, abs=1e-6)
    assert out["alpha"] == pytest.approx(-0.0002 * 252, abs=1e-6)
    assert out["n_obs"] < len(IDX) - 1


def test_residual_and_tracking():
    rng = np.random.default_rng(2)
    rb = rng.normal(0, 0.01, len(IDX))
    eps = rng.normal(0, 0.005, len(IDX))
    out = alpha_beta(nav_from(0.8 * rb + eps, IDX), nav_from(rb, IDX))
    assert 0.6 < out["beta"] < 1.0
    assert 0 < out["r2"] < 1
    assert out["resid_vol"] == pytest.approx(0.005 * np.sqrt(252), rel=0.15)
    assert set(out) >= {"alpha", "beta", "r2", "resid_vol", "n_obs"}


def test_too_short_returns_nan():
    out = alpha_beta(pd.Series([1.0, 1.01], index=IDX[:2]), pd.Series([1.0, 1.0], index=IDX[:2]))
    assert np.isnan(out["beta"]) and np.isnan(out["alpha"])
