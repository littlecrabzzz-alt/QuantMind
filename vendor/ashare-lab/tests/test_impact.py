"""B5 冲击成本：平方根冲击与单日成交占比上限的验收测试。"""
import math

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest

from synth import FixedStrategy, make_data, refresh_limits

DATES = pd.bdate_range("2024-01-01", periods=60)
D = [d.strftime("%Y-%m-%d") for d in DATES]
SIG, EXE = 30, 31  # 信号日、执行日（行号）
FEE = 0.00025 + 0.00001


def build(amount=1e8, amp=0.01):
    data = make_data(D, ["A", "B"])
    sign = np.where(np.arange(len(D)) % 3 == 0, 1.0, -1.0)
    data.close["A"] = 10 * np.exp(np.cumsum(sign * amp))
    data.close["B"] = 20.0
    data.open = data.close.copy()
    data.amount[:] = amount
    return refresh_limits(data)


def sigma_adv(data, code, row, window=20):
    px = (data.close.ffill() * data.adj.ffill())[code].iloc[row - window - 1:row]
    sigma = np.log(px).diff().dropna().std(ddof=1)
    adv = data.amount[code].iloc[row - window:row].fillna(0).mean()
    return sigma, adv


def cfg(cash=1e7, **cost):
    return BacktestConfig(start=D[0], end=D[-1], initial_cash=cash, costs=CostModel(**cost))


def buys(res, code="A"):
    t = res.trades[(res.trades.side == "buy") & (res.trades.code == code)]
    return t.assign(date=pd.to_datetime(t.date))


def sells(res, code="A"):
    t = res.trades[(res.trades.side == "sell") & (res.trades.code == code)]
    return t.assign(date=pd.to_datetime(t.date))


def test_defaults_keep_impact_off():
    c = CostModel()
    assert c.impact_k == 0.0 and c.max_participation is None and c.impact_window == 20


def test_explicit_zero_impact_identical_to_default():
    data = build()
    s = {D[SIG]: {"A": 0.6, "B": 0.4}, D[45]: {"A": 0.2, "B": 0.8}}
    a = run_backtest(FixedStrategy(s), data, cfg())
    b = run_backtest(FixedStrategy(s), data, cfg(impact_k=0.0, max_participation=None))
    pd.testing.assert_series_equal(a.nav, b.nav)
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_buy_price_includes_sqrt_impact():
    data = build()
    res = run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), data, cfg(impact_k=1.0))
    b = buys(res)
    assert len(b) == 1 and b.date.iloc[0] == DATES[EXE]
    sigma, adv = sigma_adv(data, "A", EXE)
    assert sigma > 0 and adv == pytest.approx(1e8)
    want = data.open["A"].iloc[EXE] * (1 + 0.001 + 1.0 * sigma * math.sqrt(1e7 / adv))
    assert b.price.iloc[0] == pytest.approx(want, rel=1e-10)


def test_impact_scales_with_k_and_size():
    data = build()
    sigma, adv = sigma_adv(data, "A", EXE)
    open_ = data.open["A"].iloc[EXE]
    r = run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), data, cfg(cash=4e7, impact_k=0.5))
    want = open_ * (1 + 0.001 + 0.5 * sigma * math.sqrt(4e7 / adv))
    assert buys(r).price.iloc[0] == pytest.approx(want, rel=1e-10)


def test_impact_uses_only_days_before_execution():
    a = build()
    b = build()
    b.amount.iloc[EXE:, :] = 1e3          # 执行日及之后的成交额不能影响价格
    b.close.iloc[EXE, 0] *= 1.05
    b = refresh_limits(b)
    b.up_limit.iloc[EXE:, :] = 1e9
    b.down_limit.iloc[EXE:, :] = 0.0
    a.up_limit.iloc[EXE:, :] = 1e9
    a.down_limit.iloc[EXE:, :] = 0.0
    pa = buys(run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), a, cfg(impact_k=1.0))).price.iloc[0]
    pb = buys(run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), b, cfg(impact_k=1.0))).price.iloc[0]
    assert pa == pytest.approx(pb, rel=1e-12)


def test_participation_cap_spreads_fill_over_days():
    data = build()
    res = run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), data,
                       cfg(impact_k=1.0, max_participation=0.01))   # 上限 = 1% × 1 亿 = 100 万/天
    b = buys(res)
    assert b.date.iloc[0] == DATES[EXE]
    assert (b.value <= 1e6 + 1e-6).all()
    first = b.iloc[0]
    assert first.value > 1e6 * (1 - FEE) - first.price * 100 - 1
    sigma, adv = sigma_adv(data, "A", EXE)
    want = data.open["A"].iloc[EXE] * (1 + 0.001 + sigma * math.sqrt(1e6 / adv))
    assert first.price == pytest.approx(want, rel=1e-10)   # 冲击按实际可成交金额算
    assert b.date.nunique() >= 9                            # 约 10 天才能建完仓
    assert list(b.date) == sorted(b.date) and b.date.is_unique
    last = res.positions["A"].iloc[-1] * data.close["A"].iloc[-1]
    assert last > 0.9 * res.nav.iloc[-1]


def test_sell_side_symmetric_and_capped_exit():
    data = build()
    s = {D[SIG]: {"A": 1.0}, D[40]: {}}
    res = run_backtest(FixedStrategy(s), data, cfg(impact_k=1.0))
    sl = sells(res)
    assert sl.date.iloc[0] == DATES[41] and len(sl) == 1
    sigma, adv = sigma_adv(data, "A", 41)
    q = res.positions["A"].iloc[40] * data.open["A"].iloc[41]
    want = data.open["A"].iloc[41] * (1 - 0.001 - sigma * math.sqrt(q / adv))
    assert sl.price.iloc[0] == pytest.approx(want, rel=1e-10)
    assert res.positions["A"].iloc[-1] == 0
    capped = run_backtest(FixedStrategy(s), data, cfg(impact_k=1.0, max_participation=0.02))
    cs = sells(capped)
    assert (cs.value <= 2e6 + 1e-6).all() and cs.date.nunique() >= 4
    # 卖出也是分多天，直到清仓或回测结束
    assert cs.date.iloc[0] == DATES[41]


def test_zero_adv_blocks_trade_until_volume_returns():
    data = build()
    data.amount.iloc[:EXE, 0] = 0.0
    res = run_backtest(FixedStrategy({D[SIG]: {"A": 1.0}}), data, cfg(impact_k=1.0))
    b = buys(res)
    assert b.date.iloc[0] == DATES[EXE + 1]      # 执行日 ADV=0 不能成交，次日 ADV>0 重试
    sigma, adv = sigma_adv(data, "A", EXE + 1)
    assert adv == pytest.approx(1e8 / 20)
    assert b.price.iloc[0] > data.open["A"].iloc[EXE + 1] * (1 + 0.001)


def test_flat_price_means_zero_impact():
    data = build()
    res = run_backtest(FixedStrategy({D[SIG]: {"B": 1.0}}), data, cfg(impact_k=1.0))
    assert buys(res, "B").price.iloc[0] == pytest.approx(20.0 * 1.001, rel=1e-12)
