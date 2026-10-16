"""社区第 2、7 条：指数择时规则与模拟器的验收测试。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.index_timing import (
    index_ep, ma_rule, rule_182_pe, rule_ma_dip_buy, rule_ma_dip_exit, rel_underperf_years,
    simulate, trade_stats,
)

IDX = pd.bdate_range("2020-01-01", periods=6)


def test_simulate_switch_at_next_open_with_cost():
    open_ = pd.Series([10, 10, 11, 12, 12, 13.0], index=IDX)
    close = pd.Series([10, 10.5, 11.5, 12, 12.5, 13.0], index=IDX)
    signal = pd.Series([0, 1, 1, 0, 0, 0], index=IDX)    # t=1 收盘出买入信号
    out = simulate(open_, close, signal, cost=0.001)
    pos = out["position"]
    assert list(pos) == [0, 0, 1, 1, 0, 0]                # 次日开盘才持有
    nav = out["nav"]
    assert nav.iloc[1] == pytest.approx(1.0)
    # t=2：开盘买入付 0.1%，盘中 11 -> 11.5
    assert nav.iloc[2] == pytest.approx((1 - 0.001) * 11.5 / 11)
    # t=3：隔夜 11.5 -> 12（开盘），全天持有到收盘 12
    assert nav.iloc[3] == pytest.approx(nav.iloc[2] * 12 / 11.5)
    # t=4：隔夜持有 12 -> 12，开盘卖出付费，之后空仓
    assert nav.iloc[4] == pytest.approx(nav.iloc[3] * (1 - 0.001))
    assert nav.iloc[5] == pytest.approx(nav.iloc[4])


def test_simulate_cash_rate():
    o = pd.Series(10.0, index=IDX)
    out = simulate(o, o, pd.Series(0, index=IDX), cost=0.0, cash_rate=0.0252)
    assert out["nav"].iloc[-1] == pytest.approx((1 + 0.0252 / 252) ** 5)


def test_ma_rule_uses_closes_up_to_t():
    c = pd.Series([1, 2, 3, 2, 1, 5.0], index=IDX)
    s = ma_rule(c, 3)
    # MA3: nan nan 2 2.333 2 2.667
    assert list(s) == [0, 0, 1, 0, 0, 1]


def test_rule_182_pe_state_machine():
    idx = pd.bdate_range("2020-01-01", periods=8)
    close = pd.Series([10, 9, 8, 9, 10, 11, 10, 9.0], index=idx)
    ma = pd.Series(10.0, index=idx)
    pe = pd.Series([15, 25, 15, 15, 15, 15, 15, 15.0], index=idx)
    s = rule_182_pe(close, pe, n=None, band=0.07, pe_max=20, ma=ma)
    # t0 收盘 10 不低于均线；t1 低于均线但 PE 25；t2 买入；t5 收盘 11 > 10.7 卖出；t7 再买
    assert list(s) == [0, 0, 1, 1, 1, 0, 0, 1]


def test_rule_ma_dip_exit_and_buy():
    idx = pd.bdate_range("2020-01-01", periods=8)
    close = pd.Series([100, 101, 97, 96, 95, 99, 100, 101.0], index=idx)
    above = pd.Series([1, 1, 1, 1, 0, 0, 1, 1], index=idx)
    ex = rule_ma_dip_exit(close, a1=0.03, a2=0.05, trend=above)
    # t2 单日 -3.96% 触发；t3 两日 -4.95% 不触发、单日 -1% 不触发
    assert list(ex) == [1, 1, 0, 1, 0, 0, 1, 1]
    buy = rule_ma_dip_buy(close, a1=0.03, a2=0.05, hold=3, trend=above)
    # t4 两日 (95/97-1=-2.1%) 不触发；t2 触发，持有 t2..t4
    assert list(buy) == [1, 1, 1, 1, 1, 0, 1, 1]


def test_trade_stats_round_trips():
    idx = pd.bdate_range("2020-01-01", periods=8)
    pos = pd.Series([0, 1, 1, 0, 1, 1, 1, 0], index=idx)
    nav = pd.Series([1, 1, 1.1, 1.1, 1.1, 1.0, 0.99, 0.99], index=idx)
    st = trade_stats(pos, nav)
    assert st["n_trades"] == 2
    assert st["win_rate"] == pytest.approx(0.5)
    assert st["payoff"] == pytest.approx(0.1 / 0.1)       # 平均盈利 10% / 平均亏损 10%


def test_index_ep_weighted_with_missing():
    w = pd.Series({"A": 50.0, "B": 30.0, "C": 20.0})
    ep = pd.Series({"A": 0.10, "B": -0.05, "C": np.nan})
    assert index_ep(w, ep) == pytest.approx((50 * 0.10 + 30 * -0.05) / 80)


def test_rel_underperf_years():
    idx = pd.bdate_range("2020-01-01", periods=505)
    hold = pd.Series(np.linspace(1, 2, 505), index=idx)
    strat = hold.copy()
    strat.iloc[100:352] = strat.iloc[100]                # 252 天不动，之后追上
    strat.iloc[352:] = hold.iloc[352:] * strat.iloc[100] / hold.iloc[100]
    yrs = rel_underperf_years(strat, hold)
    assert yrs == pytest.approx(251 / 252, abs=0.01)            # 第 101..351 天相对持有处于水下
