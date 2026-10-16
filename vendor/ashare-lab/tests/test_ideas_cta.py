"""I9 商品期货趋势 + 期限结构的验收测试（docs/13）。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.ideas_cta import (continuous_returns, trend_signal, carry_signal, roll_yield,
                                  size_positions, run_futures_portfolio)

D = pd.bdate_range("2024-01-01", periods=8)


def test_continuous_returns_use_held_contract_and_flag_rolls():
    prices = pd.DataFrame({"X01": [100, 101, 102, 103, 104, 105, 106, 107.0],
                           "X05": [90, 92, 94, 96, 98, 100, 102, 104.0]}, index=D)
    mapping = pd.Series(["X01", "X01", "X01", "X05", "X05", "X05", "X05", "X05"], index=D)
    ret, rolled = continuous_returns(prices, mapping)
    assert np.isnan(ret.iloc[0])
    assert ret.iloc[1] == pytest.approx(101 / 100 - 1)
    # D[3]：主力在 D[3] 收盘切到 X05，D[3] 当天收益仍按 D[2] 收盘持有的 X01
    assert ret.iloc[3] == pytest.approx(103 / 102 - 1)
    assert ret.iloc[4] == pytest.approx(98 / 96 - 1)
    assert list(rolled[rolled].index) == [D[3]]


def test_continuous_returns_missing_close_uses_settle_upstream_and_nan_gap():
    prices = pd.DataFrame({"X01": [100, np.nan, 102, 103.0]}, index=D[:4])
    mapping = pd.Series("X01", index=D[:4])
    ret, _ = continuous_returns(prices, mapping)
    # 价格缺失日收益为 NaN；下一日按最近有效价计算
    assert np.isnan(ret.iloc[1])
    assert ret.iloc[2] == pytest.approx(102 / 100 - 1)


def test_trend_signal():
    idx = pd.bdate_range("2023-01-02", periods=300)
    up = pd.Series(0.001, index=idx)
    mixed = pd.Series(0.001, index=idx)
    mixed.iloc[-30:] = -0.002          # 近 20、60 日为负，120、250 日为正
    short = pd.Series(0.001, index=idx)
    short.iloc[:100] = np.nan          # 有效收益不足 250 个
    ret = pd.DataFrame({"UP": up, "MIX": mixed, "SHORT": short})
    s = trend_signal(ret, idx[-1])
    assert s["UP"] == pytest.approx(1.0)
    assert s["MIX"] == pytest.approx(0.0)
    assert "SHORT" not in s.index or np.isnan(s["SHORT"])
    # 无前视：只用 <= t 的数据
    s_mid = trend_signal(ret, idx[-31])
    assert s_mid["MIX"] == pytest.approx(1.0)


def test_roll_yield_and_carry_thirds():
    # 近月 110、远月 100、相隔 365 天 → ln(1.1)
    assert roll_yield(110.0, 100.0, 365) == pytest.approx(np.log(1.1))
    assert roll_yield(100.0, 110.0, 182.5) == pytest.approx(-2 * np.log(1.1))
    ry = pd.Series({"A": 0.3, "B": 0.2, "C": 0.1, "D": 0.0, "E": -0.1, "F": -0.2, "G": np.nan})
    s = carry_signal(ry)
    assert s[["A", "B"]].tolist() == [1.0, 1.0]
    assert s[["C", "D"]].tolist() == [0.0, 0.0]
    assert s[["E", "F"]].tolist() == [-1.0, -1.0]
    assert "G" not in s.index or np.isnan(s["G"])


def test_size_positions():
    sig = pd.Series({"A": 1.0, "B": -0.5})
    vol = pd.Series({"A": 0.20, "B": 0.10})
    # 原始权重：A = 1*0.10/0.20/2 = 0.25；B = -0.5*0.10/0.10/2 = -0.25
    w = size_positions(sig, vol, port_vol=0.05, target=0.10, max_gross=3.0)
    # 组合层：min(3/0.5, 0.10/0.05) = 2
    assert w["A"] == pytest.approx(0.5) and w["B"] == pytest.approx(-0.5)
    w = size_positions(sig, vol, port_vol=0.01, target=0.10, max_gross=3.0)
    assert w.abs().sum() == pytest.approx(3.0)


def test_run_portfolio_timing_and_costs():
    ret = pd.DataFrame({"A": [0.0, 0.01, 0.02, 0.03, -0.01, 0.0, 0.0, 0.0]}, index=D)
    rolled = pd.DataFrame(False, index=D, columns=["A"])
    targets = {D[1]: pd.Series({"A": 2.0})}
    nav = run_futures_portfolio(ret, targets, rolled, cost=0.0)
    # D[1] 收盘信号 → D[2] 收盘建仓 → 从 D[3] 起赚收益
    assert nav.iloc[2] == pytest.approx(1.0)
    assert nav.iloc[3] == pytest.approx(1 + 2 * 0.03)
    nav_c = run_futures_portfolio(ret, targets, rolled, cost=0.001)
    assert nav_c.iloc[2] == pytest.approx(1 - 2 * 0.001)
    # 权重按"名义/权益"每日维持在目标（每日再平衡到目标权重的近似不计成本）
    assert nav.iloc[4] == pytest.approx((1 + 2 * 0.03) * (1 - 2 * 0.01))


def test_run_portfolio_roll_cost():
    ret = pd.DataFrame({"A": [0.0] * 8}, index=D)
    rolled = pd.DataFrame(False, index=D, columns=["A"])
    rolled.loc[D[5], "A"] = True
    targets = {D[1]: pd.Series({"A": -1.5})}
    nav = run_futures_portfolio(ret, targets, rolled, cost=0.001)
    # 建仓 1.5×c，移仓日两条腿 2×1.5×c
    assert nav.iloc[-1] == pytest.approx((1 - 1.5 * 0.001) * (1 - 3 * 0.001))
