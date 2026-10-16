"""S1 虚拟盘版：ETF 并入行情、逆波动率三分仓策略、引擎内撮合。"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.expansion.etf_market import with_etfs
from ashare_lab.strategies.allocation import InverseVolAllocation
from synth import ZERO_COST, FixedStrategy, make_data

DATES = pd.bdate_range("2020-01-01", periods=120)
SLEEVES = {"bond": "BND.SH", "gold": "GLD.SH"}


def _etf_frame(close, start=0):
    close = pd.Series(close, index=DATES, dtype=float)
    close.iloc[:start] = np.nan
    return pd.DataFrame({"open": close.shift(1).fillna(close), "close": close,
                         "adj": 1.0, "amount": 1e9, "volume": 1e7}, index=DATES)


def _market(seed=0, gold_start=0):
    rng = np.random.default_rng(seed)
    data = make_data(DATES, ["A", "B"])
    data.members["000906.SH"] = pd.DataFrame(True, index=DATES, columns=["A", "B"])
    for code, sigma in (("A", 0.02), ("B", 0.03)):
        path = 10 * np.exp(np.cumsum(rng.normal(0, sigma, len(DATES))))
        data.close[code] = path
        data.open[code] = pd.Series(path, index=DATES).shift(1).fillna(10.0).to_numpy()
    data.up_limit = data.close.shift(1).fillna(10.0) * 1.1
    data.down_limit = data.close.shift(1).fillna(10.0) * 0.9
    etfs = {
        "BND.SH": _etf_frame(100 * np.exp(np.cumsum(rng.normal(0, 0.002, len(DATES))))),
        "GLD.SH": _etf_frame(5 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DATES)))),
                             start=gold_start),
    }
    return with_etfs(data, etfs)


def test_with_etfs_adds_tradable_columns_outside_universe():
    data = _market(gold_start=30)
    for field in ("open", "close", "adj", "amount", "volume", "up_limit", "down_limit",
                  "suspended", "is_st"):
        assert {"BND.SH", "GLD.SH"} <= set(getattr(data, field).columns)
    assert not data.members["000906.SH"][["BND.SH", "GLD.SH"]].any().any()
    assert not data.is_st[["BND.SH", "GLD.SH"]].any().any()
    # 上市前无行情 → 停牌；之后可交易；涨跌停按前收 ±10%。
    assert data.suspended["GLD.SH"].iloc[:30].all()
    assert not data.suspended["GLD.SH"].iloc[31:].any()
    prev = data.close["BND.SH"].iloc[49]
    assert data.up_limit["BND.SH"].iloc[50] == pytest.approx(prev * 1.1)
    assert data.down_limit["BND.SH"].iloc[50] == pytest.approx(prev * 0.9)
    assert data.list_date["GLD.SH"] == DATES[30]
    assert pd.isna(data.delist_date["BND.SH"])


def _stock_strategy():
    return FixedStrategy({str(d.date()): {"A": 0.5, "B": 0.5} for d in DATES[[69, 89, 109]]})


def test_inverse_vol_weights_formula():
    data = _market()
    t = DATES[69]
    strategy = InverseVolAllocation(stock=_stock_strategy(), sleeves=SLEEVES, window=60)
    assert list(strategy.rebalance_dates(DATES)) == list(DATES[[69, 89, 109]])
    weights = strategy.target_weights(t, data.truncate(t))
    adj = data.adj_close().loc[:t]
    returns = adj.pct_change(fill_method=None).iloc[-60:]
    basket = returns[["A", "B"]] @ np.array([0.5, 0.5])
    sigma = pd.Series({"stock": basket.std(ddof=1), "bond": returns["BND.SH"].std(ddof=1),
                       "gold": returns["GLD.SH"].std(ddof=1)})
    w = (1 / sigma) / (1 / sigma).sum()
    assert weights["A"] == pytest.approx(0.5 * w["stock"])
    assert weights["B"] == pytest.approx(0.5 * w["stock"])
    assert weights["BND.SH"] == pytest.approx(w["bond"])
    assert weights["GLD.SH"] == pytest.approx(w["gold"])
    assert weights.sum() == pytest.approx(1.0)
    assert strategy.exposure(t, data.truncate(t)) == 1.0
    assert strategy.last_sleeve_weights.to_dict() == pytest.approx(w.to_dict())


def test_short_history_equal_weight():
    data = _market(gold_start=60)
    t = DATES[69]  # 黄金只有 9 个收益 < 20
    strategy = InverseVolAllocation(stock=_stock_strategy(), sleeves=SLEEVES, window=60)
    strategy.rebalance_dates(DATES)
    weights = strategy.target_weights(t, data.truncate(t))
    assert weights["BND.SH"] == pytest.approx(1 / 3)
    assert weights["GLD.SH"] == pytest.approx(1 / 3)
    assert weights["A"] + weights["B"] == pytest.approx(1 / 3)


def test_no_lookahead():
    data = _market()
    t = DATES[89]
    strategy = InverseVolAllocation(stock=_stock_strategy(), sleeves=SLEEVES, window=60)
    strategy.rebalance_dates(DATES)
    base = strategy.target_weights(t, data.truncate(t))
    shocked = _market()
    for field in ("close", "open"):
        frame = getattr(shocked, field)
        frame.iloc[90:] *= 3.0
    other = InverseVolAllocation(stock=_stock_strategy(), sleeves=SLEEVES, window=60)
    other.rebalance_dates(DATES)
    pd.testing.assert_series_equal(base.sort_index(), other.target_weights(t, shocked.truncate(t)).sort_index())


def test_engine_buys_etfs_next_open():
    data = _market()
    strategy = InverseVolAllocation(stock=_stock_strategy(), sleeves=SLEEVES, window=60)
    result = run_backtest(strategy, data, BacktestConfig(
        start=str(DATES[0].date()), end=str(DATES[-1].date()), initial_cash=1e7,
        costs=CostModel(**ZERO_COST)))
    buys = result.trades[result.trades.side == "buy"]
    assert set(buys[buys.date == DATES[70]].code) == {"A", "B", "BND.SH", "GLD.SH"}
    value = result.positions.loc[DATES[70], "BND.SH"] * data.close.loc[DATES[70], "BND.SH"]
    assert value / result.nav.loc[DATES[70]] == pytest.approx(
        result.target.loc[DATES[70], "BND.SH"], abs=0.01)
