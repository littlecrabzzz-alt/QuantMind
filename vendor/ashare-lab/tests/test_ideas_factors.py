"""I1–I6 FactorTopN 与 I7 日历效应的验收测试（docs/13）。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.strategies.factor_topn import FactorTopN, week_end_dates
from ashare_lab.ideas_calendar import calendar_holdings, calendar_nav

from synth import make_data

DATES = pd.bdate_range("2024-01-01", periods=300)
T = DATES[280]
BASE = dict(universe="IDX", min_amount=0.0, min_list_days=1)


def trend_data(codes, drifts):
    data = make_data(DATES, codes)
    for c in codes:
        data.close[c] = 10 * np.exp(np.arange(len(DATES)) * drifts[c])
    data.open = data.close.copy()
    return data


def picked(weights):
    return sorted(weights.index[weights > 0])


# ---------- I1 / I2：J 日收益 ----------

def test_momentum_skip_uses_offset_window():
    codes = ["A", "B", "C", "D"]
    data = trend_data(codes, {"A": 0.001, "B": 0.002, "C": 0.003, "D": 0.0})
    # D：最近 21 日暴涨，但 skip=21 时不应计入
    i = DATES.get_loc(T)
    data.close.loc[DATES[i - 10]:, "D"] = 1000.0
    s = FactorTopN(factor="ret", lookback=63, skip=21, highest=True, top_n=2, **BASE)
    w = s.target_weights(T, data.truncate(T))
    assert picked(w) == ["B", "C"]
    assert w.sum() == pytest.approx(1.0)
    assert w["B"] == pytest.approx(0.5)


def test_return_score_value():
    codes = ["A", "B"]
    data = trend_data(codes, {"A": 0.001, "B": 0.002})
    s = FactorTopN(factor="ret", lookback=63, skip=21, **BASE)
    score = s.scores(T, data.truncate(T))
    i = DATES.get_loc(T)
    expect = data.close["A"].iloc[i - 21] / data.close["A"].iloc[i - 21 - 63] - 1
    assert score["A"] == pytest.approx(expect)


def test_return_requires_valid_observations():
    codes = ["A", "B", "C"]
    data = trend_data(codes, {"A": 0.001, "B": 0.002, "C": 0.003})
    i = DATES.get_loc(T)
    # C 在窗口内停牌超过 20%（63 日窗口中 15 日无收盘价）
    data.close.iloc[i - 40:i - 25, 2] = np.nan
    s = FactorTopN(factor="ret", lookback=63, skip=0, **BASE)
    score = s.scores(T, data.truncate(T))
    assert np.isnan(score.get("C", np.nan))
    assert score["B"] > score["A"]


def test_reversal_picks_lowest_and_week_end():
    codes = ["A", "B", "C"]
    data = trend_data(codes, {"A": 0.001, "B": -0.002, "C": 0.003})
    s = FactorTopN(factor="ret", lookback=5, skip=0, highest=False, top_n=1,
                   rebalance="week_end", **BASE)
    assert picked(s.target_weights(T, data.truncate(T))) == ["B"]
    cal = pd.DatetimeIndex(["2024-01-01", "2024-01-03", "2024-01-05", "2024-01-08",
                            "2024-01-10", "2024-01-15"])
    assert list(week_end_dates(cal)) == list(pd.DatetimeIndex(["2024-01-05", "2024-01-10", "2024-01-15"]))
    assert list(s.rebalance_dates(cal)) == list(week_end_dates(cal))


# ---------- I3 小市值 ----------

def test_small_cap_all_universe_ignores_members_and_no_lookahead():
    codes = ["A", "B", "C"]
    data = make_data(DATES, codes)
    data.members["IDX"].loc[:, "A"] = False
    mv = pd.DataFrame({"A": 1.0, "B": 3.0, "C": 2.0}, index=DATES)
    i = DATES.get_loc(T)
    mv.iloc[i + 1:, 1] = 0.5  # 未来 B 变成最小，不能被看到
    data.extra["total_mv"] = mv
    s = FactorTopN(factor="total_mv", highest=False, top_n=2, universe="all",
                   min_amount=0.0, min_list_days=1)
    w = s.target_weights(T, data.truncate(T))
    assert picked(w) == ["A", "C"]
    # 指数池时 A 被排除
    s2 = FactorTopN(factor="total_mv", highest=False, top_n=2, **BASE)
    assert picked(s2.target_weights(T, data.truncate(T))) == ["B", "C"]


def test_eligibility_filters_still_apply():
    codes = ["A", "B", "C"]
    data = make_data(DATES, codes)
    data.extra["total_mv"] = pd.DataFrame({"A": 1.0, "B": 3.0, "C": 2.0}, index=DATES)
    data.is_st.loc[T, "A"] = True
    data.suspended.loc[T, "C"] = True
    s = FactorTopN(factor="total_mv", highest=False, top_n=2, universe="all",
                   min_amount=0.0, min_list_days=1)
    assert picked(s.target_weights(T, data.truncate(T))) == ["B"]


# ---------- I4 资金流 ----------

def test_moneyflow_ratio():
    codes = ["A", "B", "C"]
    data = make_data(DATES, codes)  # amount = 1e7 元/日
    flow = pd.DataFrame({"A": 100.0, "B": -100.0, "C": 50.0}, index=DATES)  # 万元
    i = DATES.get_loc(T)
    flow.iloc[i - 19:i - 14, 2] = np.nan  # C 只有 15 日数据 → 无分数
    data.extra["net_mf_amount"] = flow
    s = FactorTopN(factor="moneyflow", top_n=3, **BASE)
    score = s.scores(T, data.truncate(T))
    assert score["A"] == pytest.approx(20 * 100 * 1e4 / (20 * 1e7))
    assert score["B"] == pytest.approx(-0.1)
    assert np.isnan(score.get("C", np.nan))
    assert picked(s.target_weights(T, data.truncate(T))) == ["A", "B"]
    low = FactorTopN(factor="moneyflow", highest=False, top_n=1, **BASE)
    assert picked(low.target_weights(T, data.truncate(T))) == ["B"]


# ---------- I5 红利低波 ----------

def test_dividend_lowvol_two_stage():
    codes = list("ABCDEF")
    data = make_data(DATES, codes)
    sign = np.where(np.arange(len(DATES)) % 2 == 0, 1.0, -1.0)
    amps = {"A": 0.001, "B": 0.002, "C": 0.003, "D": 0.004, "E": 0.0005, "F": 0.0001}
    for c in codes:
        data.close[c] = 10 * np.exp(np.cumsum(sign * amps[c]))
    data.open = data.close.copy()
    # 股息：F 为 0（排除），E 最低正值；div_top=4 → 取 A B C D，再取波动最低 2 只 → A B
    data.extra["dv_ttm"] = pd.DataFrame({"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0, "F": 0.0},
                                        index=DATES)
    s = FactorTopN(factor="div_lowvol", div_top=4, vol_window=250, top_n=2, **BASE)
    assert picked(s.target_weights(T, data.truncate(T))) == ["A", "B"]


# ---------- I6 行业轮动 ----------

def test_industry_rotation_weights():
    groups = {"X": list("ABCDE"), "Y": list("FGHIJ"), "Z": list("KLMNO"), "W": list("PQRST"), "V": list("UVW")}
    drift = {"X": 0.004, "Y": 0.003, "Z": 0.002, "W": 0.001, "V": 0.01}
    codes = [c for g in groups.values() for c in g]
    data = trend_data(codes, {c: drift[g] for g, cs in groups.items() for c in cs})
    table = pd.DataFrame({
        "code": codes,
        "l1_code": [f"{g}.SI" for g, cs in groups.items() for _ in cs],
        "l1_name": [g for g, cs in groups.items() for _ in cs],
        "in_date": "2000-01-01", "out_date": None})
    # X 中 E 停牌：X 仍有 4 只？不足 5 只 → X 不参与
    data.suspended.loc[T, "E"] = True
    s = FactorTopN(factor="industry_ret", lookback=63, industry_table=table, top_k=3, **BASE)
    w = s.target_weights(T, data.truncate(T))
    # V 只有 3 只、X 可选只剩 4 只，都不参与 → 选 Y Z W
    assert picked(w) == sorted(groups["Y"] + groups["Z"] + groups["W"])
    assert w.sum() == pytest.approx(1.0)
    assert w["F"] == pytest.approx(1 / 3 / 5)


def test_names_are_distinct():
    a = FactorTopN(factor="ret", lookback=63, skip=21, **BASE).name
    b = FactorTopN(factor="ret", lookback=126, skip=21, **BASE).name
    c = FactorTopN(factor="ret", lookback=63, skip=21, highest=False, **BASE).name
    assert len({a, b, c}) == 3


# ---------- I7 日历效应 ----------

CAL = pd.DatetimeIndex([
    "2024-01-25", "2024-01-26", "2024-01-29", "2024-01-30", "2024-01-31",
    "2024-02-01", "2024-02-02", "2024-02-05", "2024-02-06", "2024-02-07", "2024-02-08",
    # 春节：02-09..02-18 休市
    "2024-02-19", "2024-02-20", "2024-02-21",
])


def test_turn_of_month_holdings():
    h = calendar_holdings(CAL, "tom").loc[:"2024-02-19"]  # 日历末月不完整，不检查
    # 持有 1 月最后 1 日（01-31）+ 2 月前 3 日（02-01、02-02、02-05）的收益
    expect = {"2024-01-31", "2024-02-01", "2024-02-02", "2024-02-05"}
    assert set(h.index[h].strftime("%Y-%m-%d")) == expect


def test_pre_holiday_holdings():
    h = calendar_holdings(CAL, "preholiday").loc[:"2024-02-19"]
    # d = 02-08（下一交易日 02-19，相隔 11 天）：持有 02-07、02-08 两日收益
    # 普通周末（周五→周一相隔 3 天）不算
    assert set(h.index[h].strftime("%Y-%m-%d")) == {"2024-02-07", "2024-02-08"}
    u = calendar_holdings(CAL, "union").loc[:"2024-02-19"]
    assert u.sum() == 6


def test_calendar_nav_close_to_close_and_costs():
    cal = CAL[:6]
    close = pd.Series([10, 11, 12, 13, 14, 15.0], index=cal)
    open_ = close - 0.5
    hold = pd.Series([False, False, True, True, False, False], index=cal)
    nav = calendar_nav(open_, close, hold, cost=0.0)
    # 持有第 3、4 日收益：12/11 * 13/12 = 13/11
    assert nav.iloc[-1] == pytest.approx(13 / 11)
    nav_c = calendar_nav(open_, close, hold, cost=0.001)
    assert nav_c.iloc[-1] == pytest.approx(13 / 11 * (1 - 0.001) ** 2)


def test_overnight_nav():
    cal = CAL[:4]
    close = pd.Series([10, 11, 12, 13.0], index=cal)
    open_ = pd.Series([9, 10.5, 11.5, 12.0], index=cal)
    nav = calendar_nav(open_, close, None, cost=0.0, overnight=True)
    expect = (10.5 / 10) * (11.5 / 11) * (12.0 / 12)
    assert nav.iloc[-1] == pytest.approx(expect)
