"""S3 公告事件：入选与去重叠、CAR、聚类 t 值、可交易组合的成交时点。"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.expansion.event_study import event_returns, select_events, summarize
from ashare_lab.strategies.event_portfolio import EventPortfolio
from synth import ZERO_COST, make_data

DATES = pd.bdate_range("2020-01-01", periods=60)


def _event(code, day, event_type, subtype, fc_type=None):
    eff = DATES[day]
    return {"code": code, "ann_date": eff - pd.Timedelta(days=1), "effective_date": eff,
            "event_type": event_type, "subtype": subtype, "title": "t", "url": f"{code}{day}{subtype}",
            "fc_type": fc_type, "fc_p_change_min": None, "fc_p_change_max": None,
            "fc_end_date": None}


def test_select_groups_and_subtypes():
    events = pd.DataFrame([
        _event("A", 1, "earnings_forecast", "initial", "预增"),
        _event("B", 1, "earnings_forecast", "initial", "首亏"),
        _event("C", 1, "earnings_forecast", "revision", "预增"),
        _event("D", 1, "earnings_forecast", "initial", "不确定"),
        _event("E", 1, "buyback", "plan"),
        _event("F", 1, "buyback", "progress"),
        _event("G", 1, "insider_increase", "complete"),
        _event("H", 1, "insider_increase", "terminate"),
        _event("I", 1, "insider_decrease", "plan"),
        _event("J", 1, "regulatory", "inquiry"),
        _event("K", 1, "regulatory", "penalty"),
    ])
    out = select_events(events, DATES)
    groups = dict(zip(out.code, out.group))
    assert groups == {"A": "fc_pos", "B": "fc_neg", "E": "buyback", "G": "increase",
                      "I": "decrease", "K": "regulatory"}


def test_dedupe_within_20_trading_days_of_last_kept():
    events = pd.DataFrame([
        _event("A", 0, "buyback", "plan"),
        _event("A", 20, "buyback", "first"),   # 第 20 个交易日：丢弃
        _event("A", 21, "buyback", "plan"),    # 第 21 个交易日：保留
        _event("A", 30, "buyback", "plan"),    # 距 21 只有 9 日：丢弃
        _event("A", 5, "insider_increase", "plan"),  # 不同事件组互不影响
    ])
    out = select_events(events, DATES)
    kept = out[out.group == "buyback"].effective_date.tolist()
    assert kept == [DATES[0], DATES[21]]
    assert (out.group == "increase").sum() == 1


def _market():
    data = make_data(DATES, ["A", "B", "C"], open_=10.0, close=10.0)
    data.amount.loc[:, :] = 1e8
    data.members["000906.SH"] = pd.DataFrame(True, index=DATES, columns=["A", "B", "C"])
    data.close.loc[DATES[5]:, "A"] = np.linspace(10.5, 13.0, len(DATES) - 5)
    data.close.loc[DATES[5]:, "B"] = 11.0  # 同行业对照：开盘 10 → 收盘 11
    data.up_limit = data.close.shift(1).fillna(10.0) * 1.1
    data.down_limit = data.close.shift(1).fillna(10.0) * 0.9
    return data


def _industry():
    return pd.DataFrame({"code": ["A", "B", "C"], "l1_code": ["x", "x", "y"],
                         "l1_name": ["X", "X", "Y"],
                         "in_date": [pd.Timestamp("2000-01-01")] * 3, "out_date": [None] * 3})


def test_car_vs_benchmark_and_industry():
    data = _market()
    bench = pd.Series(100.0, index=DATES)
    bench.loc[DATES[5]:] = 101.0
    selected = select_events(pd.DataFrame([_event("A", 5, "buyback", "plan")]), DATES)
    out = event_returns(selected, data, bench, _industry(), universe="csi800",
                        horizons=(1, 5, 60))
    row = out.iloc[0]
    assert row.skip is None or pd.isna(row.skip)
    a_close = data.close.A
    # h=1：effective_date 开盘到当日收盘；基准为前一日收盘到当日收盘。
    assert row.car_bench_1 == pytest.approx(a_close[DATES[5]] / 10.0 - 1 - 0.01)
    assert row.car_bench_5 == pytest.approx(a_close[DATES[9]] / 10.0 - 1 - 0.01)
    assert row.car_ind_5 == pytest.approx(a_close[DATES[9]] / 10.0 - 1 - 0.1)
    assert np.isnan(row.car_bench_60)  # 超出数据尾部


def test_skip_limit_up_and_universe():
    data = _market()
    data.open.loc[DATES[5], "A"] = data.up_limit.loc[DATES[5], "A"]
    data.members["000906.SH"].loc[DATES[6], "C"] = False
    bench = pd.Series(100.0, index=DATES)
    selected = select_events(pd.DataFrame([_event("A", 5, "buyback", "plan"),
                                           _event("C", 7, "buyback", "plan")]), DATES)
    out = event_returns(selected, data, bench, _industry(), universe="csi800", horizons=(1,))
    skips = dict(zip(out.code, out.skip))
    assert skips["A"] == "limit_up"
    assert skips["C"] == "not_in_universe"  # 用 effective_date 前一日的成分


def test_delisting_counts_zero_after_last_close():
    data = _market()
    data.delist_date["A"] = DATES[8]
    data.close.loc[DATES[8]:, "A"] = np.nan
    bench = pd.Series(100.0, index=DATES)
    selected = select_events(pd.DataFrame([_event("A", 5, "buyback", "plan")]), DATES)
    out = event_returns(selected, data, bench, _industry(), universe="csi800", horizons=(10,))
    row = out.iloc[0]
    assert bool(row.delisted)
    assert row.car_bench_10 == pytest.approx(data.close.A[DATES[7]] / 10.0 - 1)


def test_liquid_universe_threshold():
    data = _market()
    data.amount.loc[:, "B"] = 1e7
    bench = pd.Series(100.0, index=DATES)
    selected = select_events(pd.DataFrame([_event("B", 30, "buyback", "plan")]), DATES)
    out = event_returns(selected, data, bench, _industry(), universe="liquid", horizons=(1,))
    assert out.iloc[0].skip == "not_in_universe"


def test_summarize_clustered_t():
    per = pd.DataFrame({
        "group": ["buyback"] * 4,
        "effective_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04"]),
        "skip": [None] * 4,
        "car_bench_1": [0.01, 0.03, -0.01, 0.05],
    })
    stats = summarize(per, horizons=(1,), benchmark="bench",
                      periods={"FULL": ("2020-01-01", "2020-12-31")})
    row = stats.iloc[0]
    x = per.car_bench_1
    mean = x.mean()
    sums = (x - mean).groupby(per.effective_date.dt.to_period("M")).sum()
    se = np.sqrt(2 / 1 * (sums ** 2).sum()) / 4
    assert row.n == 4
    assert row["mean"] == pytest.approx(mean)
    assert row["median"] == pytest.approx(x.median())
    assert row.frac_pos == pytest.approx(0.75)
    assert row.t_stat == pytest.approx(mean / se)


def _portfolio_data():
    data = make_data(DATES, ["A", "B", "C", "D"], open_=10.0, close=10.0)
    data.members["000906.SH"] = pd.DataFrame(True, index=DATES, columns=list("ABCD"))
    return data


def _run(strategy, data):
    return run_backtest(strategy, data, BacktestConfig(
        start=str(DATES[0].date()), end=str(DATES[-1].date()), costs=CostModel(**ZERO_COST)))


def test_portfolio_buys_effective_open_and_sells_after_hold():
    data = _portfolio_data()
    events = select_events(pd.DataFrame([_event("A", 3, "buyback", "plan")]), DATES)
    result = _run(EventPortfolio(events=events, hold=20, max_names=50), data)
    trades = result.trades
    buys = trades[trades.side == "buy"]
    sells = trades[trades.side == "sell"]
    assert buys.date.tolist() == [DATES[3]] and buys.code.tolist() == ["A"]
    assert sells.date.tolist() == [DATES[23]]


def test_portfolio_skips_limit_up_without_retry():
    data = _portfolio_data()
    data.open.loc[DATES[5], "B"] = data.up_limit.loc[DATES[5], "B"]
    events = select_events(pd.DataFrame([_event("B", 5, "buyback", "plan")]), DATES)
    result = _run(EventPortfolio(events=events, hold=20, max_names=50), data)
    assert result.trades[result.trades.side == "buy"].empty


def test_portfolio_cap_ranks_by_adv_and_equal_weight():
    data = _portfolio_data()
    data.amount.loc[:, "A"] = 3e8
    data.amount.loc[:, "B"] = 1e8
    data.amount.loc[:, "C"] = 2e8
    events = select_events(pd.DataFrame([_event(c, 3, "buyback", "plan") for c in "ABC"]),
                           DATES)
    strategy = EventPortfolio(events=events, hold=20, max_names=2)
    result = _run(strategy, data)
    bought = set(result.trades[result.trades.side == "buy"].code)
    assert bought == {"A", "C"}
    target = result.target.loc[DATES[3]]
    assert target[target > 0].to_dict() == pytest.approx({"A": 0.5, "C": 0.5})
