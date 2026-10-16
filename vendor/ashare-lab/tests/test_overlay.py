"""S1 分仓配置：成交时点、成本、漂移、逆波动率与组合层波动率目标。"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab.expansion.overlay import inverse_vol_weights, run_allocation


def _prices(values, start="2020-01-01"):
    frame = pd.DataFrame(values, dtype=float)
    frame.index = pd.bdate_range(start, periods=len(frame))
    return frame


def _fixed(weights):
    return lambda t, returns: pd.Series(weights, dtype=float)


def test_signal_executes_next_close_with_cost():
    prices = _prices({"a": [1, 1, 1.1, 1.21], "b": [1, 1, 0.9, 0.9]})
    out = run_allocation(prices, prices.index[:1], _fixed({"a": 0.5, "b": 0.5}), cost=0.0005)
    nav = out["nav"]
    assert nav.iloc[0] == pytest.approx(1.0)
    # 第 1 日收盘成交：从全现金到 50/50，Σ|Δw| = 1，成本 5bp。
    v1 = 1 - 0.0005
    assert nav.iloc[1] == pytest.approx(v1)
    v2 = v1 * (0.5 * 1.1 + 0.5 * 0.9)
    assert nav.iloc[2] == pytest.approx(v2)
    v3 = v1 * (0.5 * 1.21 + 0.5 * 0.9)  # 无再平衡，权重漂移
    assert nav.iloc[3] == pytest.approx(v3)
    assert list(out["target"].index) == [prices.index[1]]


def test_rebalance_cost_uses_drifted_weights():
    prices = _prices({"a": [1, 1, 2, 2, 2], "b": [1, 1, 1, 1, 1]})
    out = run_allocation(prices, prices.index[[0, 2]], _fixed({"a": 0.5, "b": 0.5}), cost=0.001)
    v1 = 1 - 0.001
    h_a, h_b = 0.5 * v1 * 2, 0.5 * v1
    v2 = h_a + h_b
    assert out["nav"].iloc[2] == pytest.approx(v2)
    # 第 3 日收盘按漂移后的持仓再平衡到 50/50。
    traded = abs(0.5 * v2 - h_a) + abs(0.5 * v2 - h_b)
    v3 = v2 - 0.001 * traded
    assert out["nav"].iloc[3] == pytest.approx(v3)
    assert out["nav"].iloc[4] == pytest.approx(v3)


def test_weight_function_sees_only_data_up_to_signal():
    rng = np.random.default_rng(1)
    prices = _prices({"a": np.exp(np.cumsum(rng.normal(0, 0.01, 120))),
                      "b": np.exp(np.cumsum(rng.normal(0, 0.02, 120)))})
    seen = []

    def weights(t, returns):
        seen.append((t, returns.index.max()))
        return inverse_vol_weights(returns, t, window=60)

    signals = prices.index[[70, 90]]
    base = run_allocation(prices, signals, weights)
    assert all(last <= t for t, last in seen)
    shocked = prices.copy()
    shocked.iloc[91:] *= np.linspace(1, 3, len(shocked) - 91)[:, None]
    other = run_allocation(shocked, signals, weights)
    pd.testing.assert_frame_equal(base["target"], other["target"])
    pd.testing.assert_series_equal(base["nav"].iloc[:92], other["nav"].iloc[:92])


def test_inverse_vol_weights_window_inclusive():
    rng = np.random.default_rng(2)
    returns = pd.DataFrame({"a": rng.normal(0, 0.01, 100), "b": rng.normal(0, 0.03, 100)},
                           index=pd.bdate_range("2020-01-01", periods=100))
    t = returns.index[79]
    w = inverse_vol_weights(returns, t, window=60)
    sigma = returns.loc[:t].iloc[-60:].std(ddof=1)
    expected = (1 / sigma) / (1 / sigma).sum()
    pd.testing.assert_series_equal(w.sort_index(), expected.sort_index(), check_names=False)
    assert w.sum() == pytest.approx(1.0)


def test_inverse_vol_weights_short_history_equal_weight():
    returns = pd.DataFrame({"a": [0.01] * 10, "b": [0.02] * 10},
                           index=pd.bdate_range("2020-01-01", periods=10))
    w = inverse_vol_weights(returns, returns.index[-1], window=60)
    assert w.to_dict() == pytest.approx({"a": 0.5, "b": 0.5})


def test_vol_target_scales_exposure_and_trades_next_day():
    n = 100
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    # 高波动资产：日收益 ±3%，年化约 48%；目标 16% → 仓位 floor(0.33/0.1)*0.1 = 0.3。
    a = np.cumprod(1 + 0.03 * sign)
    prices = _prices({"a": a})
    out = run_allocation(prices, prices.index[:1], _fixed({"a": 1.0}), cost=0.0,
                         vol_target={"target_vol": 0.16, "window": 60, "step": 0.1})
    exposure = out["exposure"]
    assert exposure.iloc[-1] == pytest.approx(0.3)
    first = exposure.index[exposure.round(9) == 0.3][0]
    position = prices.index.get_loc(first)
    # 仓位在信号日下一交易日收盘生效：之后一日的净值收益 = 0.3 × 资产收益。
    nav = out["nav"]
    r_nav = nav.iloc[position + 2] / nav.iloc[position + 1] - 1
    r_a = prices.a.iloc[position + 2] / prices.a.iloc[position + 1] - 1
    assert r_nav == pytest.approx(0.3 * r_a, rel=1e-6, abs=1e-9)
    assert exposure.max() <= 1.0


def test_turnover_reported():
    prices = _prices({"a": [1, 1, 2, 2, 2], "b": [1, 1, 1, 1, 1]})
    out = run_allocation(prices, prices.index[[0, 2]], _fixed({"a": 0.5, "b": 0.5}), cost=0.0)
    assert out["turnover"] > 0
    assert np.isfinite(out["turnover"])
