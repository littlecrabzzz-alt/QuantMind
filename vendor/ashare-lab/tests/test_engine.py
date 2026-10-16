import math

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.strategy import month_end_dates

from synth import ZERO_COST, FixedStrategy, make_data, refresh_limits

DATES = pd.bdate_range("2023-08-21", periods=10)  # 2023-08-21 ... 2023-09-01，含印花税切换日 08-28
D = [d.strftime("%Y-%m-%d") for d in DATES]


def cfg(**cost):
    return BacktestConfig(start=D[0], end=D[-1], initial_cash=1e7, costs=CostModel(**cost))


def buys(res, code=None):
    t = res.trades[res.trades.side == "buy"]
    return t if code is None else t[t.code == code]


def sells(res, code=None):
    t = res.trades[res.trades.side == "sell"]
    return t if code is None else t[t.code == code]


# ---------- 执行时点与前视 ----------

def test_signal_at_close_executes_next_open_at_open_price():
    data = make_data(D, ["A"], open_=10.0, close=12.0)
    data = refresh_limits(data)
    data.up_limit[:] = 100.0
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}}), data, cfg())
    b = buys(res, "A")
    assert len(b) == 1
    assert pd.Timestamp(b.iloc[0].date) == DATES[1]
    assert b.iloc[0].price == pytest.approx(10.0 * 1.001)
    assert res.positions.loc[DATES[0], "A"] == 0 if "A" in res.positions else True


def test_strategy_never_sees_future_data():
    data = make_data(D, ["A", "B"])
    strat = FixedStrategy({D[2]: {"A": 0.5, "B": 0.5}, D[5]: {"A": 1.0}})
    run_backtest(strat, data, cfg())
    assert strat.seen_max_dates, "strategy was never called"
    for t, seen in strat.seen_max_dates:
        assert seen == t


def test_future_price_change_does_not_change_past_trades():
    d1 = make_data(D, ["A"])
    d2 = make_data(D, ["A"])
    d2.close.iloc[6:] = 20.0
    d2.open.iloc[6:] = 20.0
    d2 = refresh_limits(d2)
    d1 = refresh_limits(d1)
    s = {D[0]: {"A": 1.0}}
    r1 = run_backtest(FixedStrategy(s), d1, cfg())
    r2 = run_backtest(FixedStrategy(s), d2, cfg())
    pd.testing.assert_series_equal(r1.nav.iloc[:6], r2.nav.iloc[:6])


# ---------- 成本、手数、记账 ----------

def test_buy_cost_and_lot_rounding():
    data = make_data(D, ["A"], open_=10.0, close=10.0)
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}}), data, cfg())
    b = buys(res, "A").iloc[0]
    px = 10.0 * 1.001
    expected_shares = math.floor(1e7 / (px * (1 + 0.00025 + 0.00001)) / 100) * 100
    assert b.shares == expected_shares
    assert b.shares % 100 == 0
    assert b.value == pytest.approx(expected_shares * px)
    assert b.fee == pytest.approx(expected_shares * px * 0.00026)
    assert res.cash.loc[DATES[1]] == pytest.approx(1e7 - b.value - b.fee)
    assert res.cash.min() >= -1e-6


def test_accounting_identity_every_day():
    data = make_data(D, ["A", "B"])
    rng = np.random.default_rng(0)
    data.close = data.close * np.exp(np.cumsum(rng.normal(0, 0.01, data.close.shape), axis=0))
    data.open = data.close.shift(1).fillna(10.0)
    data = refresh_limits(data)
    strat = FixedStrategy({D[0]: {"A": 0.5, "B": 0.5}, D[4]: {"A": 0.2, "B": 0.7}})
    res = run_backtest(strat, data, cfg())
    pos = res.positions.reindex(columns=["A", "B"], fill_value=0.0)
    mv = (pos * data.close.ffill()).sum(axis=1)
    pd.testing.assert_series_equal((res.cash + mv), res.nav, check_names=False, rtol=1e-9)
    assert (res.cash >= -1e-6).all()


def test_stamp_duty_switches_on_2023_08_28():
    # 08-24 收盘出信号 -> 08-25 卖（旧税率）；08-25 收盘出信号 -> 08-28 卖（新税率）
    for sig, exp_stamp in [("2023-08-23", 0.001), ("2023-08-25", 0.0005)]:
        data = make_data(D, ["A"])
        strat = FixedStrategy({D[0]: {"A": 1.0}, sig: {}})
        res = run_backtest(strat, data, cfg(slippage=0.0))
        s = sells(res, "A").iloc[0]
        assert s.fee == pytest.approx(s.value * (0.00025 + 0.00001 + exp_stamp))


def test_dividend_adjustment_keeps_nav_continuous():
    data = make_data(D, ["A"])
    # 第 5 天除权：价格 10 -> 10/1.1，复权因子 1 -> 1.1
    data.close.iloc[5:] = 10.0 / 1.1
    data.open.iloc[5:] = 10.0 / 1.1
    data.adj.iloc[5:] = 1.1
    data = refresh_limits(data)
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}}), data, cfg(**ZERO_COST))
    assert res.nav.iloc[-1] == pytest.approx(res.nav.iloc[2], rel=1e-9)
    assert res.positions["A"].iloc[5] == pytest.approx(res.positions["A"].iloc[4] * 1.1)


# ---------- 涨跌停与停牌 ----------

def test_limit_up_open_blocks_buy_then_retries():
    data = make_data(D, ["A"])
    data.open.iloc[1] = data.up_limit.iloc[1]  # 第二天一字涨停开盘
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}}), data, cfg())
    b = buys(res, "A")
    assert len(b) == 1
    assert pd.Timestamp(b.iloc[0].date) == DATES[2]


def test_limit_down_open_blocks_sell_then_retries():
    data = make_data(D, ["A"])
    data.open.iloc[4] = data.down_limit.iloc[4]
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}, D[3]: {}}), data, cfg())
    s = sells(res, "A")
    assert len(s) == 1
    assert pd.Timestamp(s.iloc[0].date) == DATES[5]


def test_suspended_cannot_trade_and_nan_open_cannot_trade():
    data = make_data(D, ["A", "B"])
    data.suspended.loc[DATES[1], "A"] = True
    data.open.loc[DATES[1], "B"] = np.nan
    res = run_backtest(FixedStrategy({D[0]: {"A": 0.5, "B": 0.5}}), data, cfg())
    assert pd.Timestamp(buys(res, "A").iloc[0].date) == DATES[2]
    assert pd.Timestamp(buys(res, "B").iloc[0].date) == DATES[2]


def test_retry_only_touches_pending_codes():
    data = make_data(D, ["A", "B"])
    data.open.loc[DATES[1], "B"] = data.up_limit.loc[DATES[1], "B"]
    data.close.iloc[1:, 0] = 11.0  # A 价格变化，若重试时误动 A 会产生额外成交
    data = refresh_limits(data)
    data.open.loc[DATES[1], "B"] = data.up_limit.loc[DATES[1], "B"]
    res = run_backtest(FixedStrategy({D[0]: {"A": 0.5, "B": 0.5}}), data, cfg())
    assert len(buys(res, "A")) == 1
    assert len(res.trades[res.trades.code == "A"]) == 1
    assert pd.Timestamp(buys(res, "B").iloc[0].date) == DATES[2]


def test_new_target_cancels_pending():
    data = make_data(D, ["A", "B"])
    data.suspended.loc[DATES[1]:, "B"] = True
    strat = FixedStrategy({D[0]: {"B": 1.0}, D[3]: {"A": 1.0}})
    res = run_backtest(strat, data, cfg())
    assert len(buys(res, "B")) == 0
    assert pd.Timestamp(buys(res, "A").iloc[0].date) == DATES[4]


# ---------- 择时 exposure ----------

def test_exposure_zero_liquidates_then_rebuys():
    data = make_data(D, ["A"])
    strat = FixedStrategy({D[0]: {"A": 1.0}}, exposure_map={D[3]: 0.0, D[6]: 1.0})
    res = run_backtest(strat, data, cfg())
    assert pd.Timestamp(sells(res, "A").iloc[0].date) == DATES[4]
    assert res.positions["A"].loc[DATES[4]] == 0
    assert len(buys(res, "A")) == 2
    assert pd.Timestamp(buys(res, "A").iloc[1].date) == DATES[7]
    assert res.exposure.loc[DATES[5]] == 0.0


def test_partial_exposure_scales_weights():
    data = make_data(D, ["A"])
    strat = FixedStrategy({D[0]: {"A": 1.0}}, exposure_map={D[0]: 0.3})
    res = run_backtest(strat, data, cfg(**ZERO_COST))
    w = res.positions["A"].loc[DATES[2]] * 10.0 / res.nav.loc[DATES[2]]
    assert w == pytest.approx(0.3, abs=0.001)


# ---------- 退市 ----------

def test_delisted_position_converted_to_cash_at_last_close():
    data = make_data(D, ["A"], delist={"A": D[6]})
    data.close.loc[DATES[5], "A"] = 8.0
    data.close.loc[DATES[6]:, "A"] = np.nan
    data.open.loc[DATES[6]:, "A"] = np.nan
    data = refresh_limits(data)
    data.up_limit.iloc[:] = 100.0
    data.down_limit.iloc[:] = 0.0
    res = run_backtest(FixedStrategy({D[0]: {"A": 1.0}}), data, cfg())
    sh = res.positions["A"].loc[DATES[5]]
    d = res.trades[res.trades.side == "delist"]
    assert len(d) == 1 and pd.Timestamp(d.iloc[0].date) == DATES[6]
    assert d.iloc[0].value == pytest.approx(sh * 8.0)
    assert res.positions["A"].loc[DATES[6]] == 0
    assert res.nav.loc[DATES[6]] == pytest.approx(res.nav.loc[DATES[5]])


# ---------- 其他 ----------

def test_truncate():
    data = make_data(D, ["A"])
    t = data.truncate(DATES[4])
    assert t.calendar.max() == DATES[4]
    assert t.members["IDX"].index.max() == DATES[4]
    assert t.index_close.index.max() == DATES[4]
    assert data.calendar.max() == DATES[-1]


def test_month_end_dates():
    cal = pd.bdate_range("2024-01-01", "2024-03-31")
    me = month_end_dates(cal)
    assert list(me) == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29"), pd.Timestamp("2024-03-29")]


def test_no_trades_before_first_rebalance_and_cash_constant():
    data = make_data(D, ["A"])
    res = run_backtest(FixedStrategy({D[5]: {"A": 1.0}}), data, cfg())
    assert (res.nav.iloc[:6] == 1e7).all()
    assert pd.Timestamp(buys(res, "A").iloc[0].date) == DATES[6]
