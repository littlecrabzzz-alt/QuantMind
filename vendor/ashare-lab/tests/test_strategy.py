import numpy as np
import pandas as pd
import pytest

from ashare_lab.strategies.lowvol_trend import LowVolTrend

from synth import make_data

DATES = pd.bdate_range("2024-01-01", periods=80)
CODES = ["A", "B", "C", "D", "E", "F"]
AMPS = {"A": 0.010, "B": 0.005, "C": 0.020, "D": 0.002, "E": 0.030, "F": 0.015}  # 波动从低到高：D B A F C E


def build():
    data = make_data(DATES, CODES)
    sign = np.where(np.arange(len(DATES)) % 2 == 0, 1.0, -1.0)
    for c, a in AMPS.items():
        data.close[c] = 10 * np.exp(np.cumsum(sign * a))
    data.open = data.close.copy()
    data.amount[:] = 1e8
    data.list_date[:] = pd.Timestamp("2000-01-01")
    return data


def strat(**kw):
    base = dict(universe="IDX", vol_window=20, top_n=2, min_list_days=10, timing_index=None)
    base.update(kw)
    return LowVolTrend(**base)


T = DATES[60]


def picks(s, data, t=T):
    w = s.target_weights(t, data.truncate(t))
    return sorted(w[w > 0].index), w


def test_picks_lowest_vol_equal_weight():
    sel, w = picks(strat(), build())
    assert sel == ["B", "D"]
    assert w.sum() == pytest.approx(1.0)
    assert w["B"] == pytest.approx(0.5)


def test_highvol_and_all():
    assert picks(strat(select="highvol"), build())[0] == ["C", "E"]
    sel, w = picks(strat(select="all"), build())
    assert sel == CODES and w.iloc[0] == pytest.approx(1 / 6)


def test_random_deterministic_and_within_universe():
    d = build()
    a = picks(strat(select="random", seed=1), d)[0]
    b = picks(strat(select="random", seed=1), d)[0]
    assert a == b and len(a) == 2 and set(a) <= set(CODES)


@pytest.mark.parametrize("flag", ["st", "suspended", "nonmember", "noclose", "young", "illiquid"])
def test_filters_exclude_d(flag):
    d = build()
    if flag == "st":
        d.is_st.loc[T, "D"] = True
    elif flag == "suspended":
        d.suspended.loc[T, "D"] = True
    elif flag == "nonmember":
        d.members["IDX"].loc[T, "D"] = False
    elif flag == "noclose":
        d.close.loc[T, "D"] = np.nan
    elif flag == "young":
        d.list_date["D"] = DATES[55]
    elif flag == "illiquid":
        d.amount.loc[DATES[41]:T, "D"] = 1e6
    sel, _ = picks(strat(min_list_days=10), d)
    assert sel == ["A", "B"]


def test_insufficient_observations_excluded():
    d = build()
    d.close.loc[DATES[45]:DATES[59], "D"] = np.nan  # 窗口 20 内只剩约 5 个有效收益
    sel, _ = picks(strat(), d)
    assert "D" not in sel


def test_suspension_zero_returns_not_counted():
    d = build()
    # E 波动最大；让 E 在窗口内大部分天停牌（close NaN），只留下最后几天 → 有效数不足被剔除，而不是被 ffill 的 0 收益伪装成低波动
    d.close.loc[DATES[42]:DATES[58], "E"] = np.nan
    sel, _ = picks(strat(select="all"), d)
    assert "E" not in sel and len(sel) == 5


def test_no_lookahead_future_data_ignored():
    d1, d2 = build(), build()
    d2.close.loc[DATES[61]:, "D"] *= np.exp(np.cumsum(np.where(np.arange(19) % 2 == 0, 0.2, -0.2)))
    assert picks(strat(), d1)[0] == picks(strat(), d2)[0]


def test_exposure_trend_rule():
    d = build()
    s = strat(timing_index="IDX", ma_window=10, low_exposure=0.3)
    assert s.exposure(DATES[30], d.truncate(DATES[30])) == 1.0  # 上升趋势
    d.index_close.loc[DATES[31]:, "IDX"] = 50.0
    assert s.exposure(DATES[35], d.truncate(DATES[35])) == 0.3
    assert s.exposure(DATES[5], d.truncate(DATES[5])) == 1.0  # 历史不足
    assert strat().exposure(DATES[35], d.truncate(DATES[35])) == 1.0  # 不择时


def test_rebalance_dates():
    cal = pd.bdate_range("2024-01-01", "2024-03-31")
    assert list(strat().rebalance_dates(cal))[:2] == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")]
    mid = strat(rebalance="mid_month").rebalance_dates(cal)
    assert list(mid) == [pd.Timestamp("2024-01-15"), pd.Timestamp("2024-02-15"), pd.Timestamp("2024-03-15")]


def test_name():
    assert LowVolTrend().name == "lowvol_W120_N50_L120_e0"
    assert "L" not in LowVolTrend(timing_index=None).name.split("_")[-1]
