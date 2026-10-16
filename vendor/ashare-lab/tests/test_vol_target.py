"""B2 波动率目标仓位的验收测试。"""
import math

import numpy as np
import pandas as pd
import pytest

from ashare_lab.engine import BacktestConfig, CostModel, run_backtest
from ashare_lab.strategies.lowvol_trend import LowVolTrend
from ashare_lab.strategies.vol_target import VolTarget
from ashare_lab.strategy import Strategy

from synth import make_data, refresh_limits, ZERO_COST

DATES = pd.bdate_range("2024-01-01", periods=120)
CODES = ["A", "B", "C"]


class Fixed(Strategy):
    """按日期给出固定基础权重。"""

    name = "fixed"

    def __init__(self, schedule):
        self.schedule = {pd.Timestamp(k): pd.Series(v, dtype=float) for k, v in schedule.items()}
        self.calls = []

    def rebalance_dates(self, calendar):
        return pd.DatetimeIndex(sorted(d for d in self.schedule if d in calendar))

    def target_weights(self, t, data):
        self.calls.append((t, data.calendar.max()))
        return self.schedule[t]


def build(seed=0, scale=None):
    rng = np.random.default_rng(seed)
    data = make_data(DATES, CODES)
    scale = scale or {"A": 0.01, "B": 0.02, "C": 0.03}
    for c, s in scale.items():
        data.close[c] = 10 * np.exp(np.cumsum(rng.normal(0, s, len(DATES))))
    data.open = data.close.copy()
    data.amount[:] = 1e8
    return refresh_limits(data)


def expected_sigma(data, weights, t, window):
    stop = data.calendar.get_loc(t) + 1
    px = data.adj_close().iloc[stop - window - 1:stop]
    r = np.log(px).diff().iloc[1:].fillna(0.0)
    w = pd.Series(weights, dtype=float)
    port = (r[w.index] * (w / w.sum())).sum(axis=1)
    return port.std(ddof=1) * math.sqrt(252)


def vt(schedule, **kw):
    base = dict(target_vol=0.10, window=20, step=0.1)
    base.update(kw)
    return VolTarget(base=Fixed(schedule), **base)


R0 = str(DATES[30].date())
T = DATES[60]


def test_exposure_formula_floor_to_step():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    s = vt({R0: w})
    sigma = expected_sigma(data, w, T, 20)
    raw = min(1.0, 0.10 / sigma)
    want = math.floor(raw / 0.1 + 1e-9) * 0.1
    got = s.exposure(T, data.truncate(T))
    assert got == pytest.approx(want, abs=1e-12)
    assert 0 < got < 1  # 该组合年化波动约 25%，应降仓


def test_step_zero_means_continuous_and_cap():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    sigma = expected_sigma(data, w, T, 20)
    got = vt({R0: w}, step=0.0).exposure(T, data.truncate(T))
    assert got == pytest.approx(min(1.0, 0.10 / sigma), rel=1e-10)
    # 目标波动远高于实际：封顶 max_exposure
    assert vt({R0: w}, target_vol=5.0).exposure(T, data.truncate(T)) == pytest.approx(1.0)
    assert vt({R0: w}, target_vol=5.0, max_exposure=0.8).exposure(T, data.truncate(T)) == pytest.approx(0.8)


def test_weights_normalised_by_sum():
    data = build()
    a = vt({R0: {"A": 0.25, "C": 0.25}}, step=0.0).exposure(T, data.truncate(T))
    b = vt({R0: {"A": 0.5, "C": 0.5}}, step=0.0).exposure(T, data.truncate(T))
    assert a == pytest.approx(b, rel=1e-12)


def test_window_changes_estimate():
    data = build()
    w = {"B": 1.0}
    for window in (10, 40):
        sigma = expected_sigma(data, w, T, window)
        got = vt({R0: w}, step=0.0, window=window).exposure(T, data.truncate(T))
        assert got == pytest.approx(min(1.0, 0.10 / sigma), rel=1e-10)


def test_uses_latest_rebalance_on_or_before_t():
    data = build()
    r1 = str(DATES[50].date())
    s = vt({R0: {"A": 1.0}, r1: {"C": 1.0}}, step=0.0)
    got = s.exposure(T, data.truncate(T))
    assert got == pytest.approx(min(1.0, 0.10 / expected_sigma(data, {"C": 1.0}, T, 20)), rel=1e-10)
    early = DATES[45]
    got_early = s.exposure(early, data.truncate(early))
    assert got_early == pytest.approx(
        min(1.0, 0.10 / expected_sigma(data, {"A": 1.0}, early, 20)), rel=1e-10)


def test_rebalance_day_uses_new_basket_without_lookahead():
    data = build()
    r1 = DATES[50]
    base = Fixed({R0: {"A": 1.0}, str(r1.date()): {"C": 1.0}})
    s = VolTarget(base=base, target_vol=0.10, window=20, step=0.0)
    got = s.exposure(r1, data.truncate(r1))
    assert got == pytest.approx(min(1.0, 0.10 / expected_sigma(data, {"C": 1.0}, r1, 20)), rel=1e-10)
    assert all(seen <= t for t, seen in base.calls)


def test_no_lookahead_future_prices_ignored():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    s1 = vt({R0: w})
    full = s1.exposure(T, data)
    shocked = build()
    shocked.close.loc[DATES[61]:, "A"] *= 3.0
    s2 = vt({R0: w})
    assert s2.exposure(T, shocked) == pytest.approx(full)
    assert vt({R0: w}).exposure(T, data.truncate(T)) == pytest.approx(full)


def test_suspended_day_contributes_zero_return():
    data = build()
    data.close.loc[DATES[55], "A"] = np.nan
    data.suspended.loc[DATES[55], "A"] = True
    w = {"A": 0.5, "C": 0.5}
    sigma = expected_sigma(data, w, T, 20)
    got = vt({R0: w}, step=0.0).exposure(T, data.truncate(T))
    assert got == pytest.approx(min(1.0, 0.10 / sigma), rel=1e-10)


def test_insufficient_history_or_no_basket_gives_max():
    data = build()
    s = vt({str(DATES[5].date()): {"A": 1.0}})
    assert s.exposure(DATES[10], data.truncate(DATES[10])) == pytest.approx(1.0)  # 不足 20 个收益
    s2 = vt({R0: {"A": 1.0}}, max_exposure=0.9)
    assert s2.exposure(DATES[20], data.truncate(DATES[20])) == pytest.approx(0.9)  # 还没有篮子
    empty = vt({R0: {}})
    assert empty.exposure(T, data.truncate(T)) == pytest.approx(1.0)


def test_passthrough_and_name():
    base = LowVolTrend(universe="IDX", vol_window=20, top_n=2, min_list_days=10, timing_index=None)
    s = VolTarget(base=base, target_vol=0.12, window=40, step=0.1)
    assert s.name == "lowvol_W20_N2_vt12_L40_s0.1"
    cal = DATES
    assert s.rebalance_dates(cal).equals(base.rebalance_dates(cal))
    data = build()
    t = s.rebalance_dates(cal)[2]
    pd.testing.assert_series_equal(s.target_weights(t, data.truncate(t)),
                                   base.target_weights(t, data.truncate(t)))
    with pytest.raises(ValueError):
        VolTarget(base=base, target_vol=0.0)
    with pytest.raises(ValueError):
        VolTarget(base=base, window=1)


def test_engine_integration_exposure_on_grid():
    data = build()
    base = LowVolTrend(universe="IDX", vol_window=20, top_n=2, min_list_days=10, timing_index=None)
    s = VolTarget(base=base, target_vol=0.10, window=20, step=0.1)
    res = run_backtest(s, data, BacktestConfig(start=str(DATES[25].date()), end=str(DATES[-1].date()),
                                               costs=CostModel(**ZERO_COST)))
    e = res.exposure
    assert ((e >= 0) & (e <= 1)).all()
    np.testing.assert_allclose(np.round(e / 0.1) * 0.1, e, atol=1e-9)
    assert e.min() < 1  # 波动约 15–30%，应出现降仓
    assert np.isfinite(res.nav).all()


# ---------- B2 追加：延迟减仓、减半、下行波动（默认关闭，行为不变） ----------

def raw_exposure(data, w, t, window=20, target=0.10, downside=False):
    stop = data.calendar.get_loc(t) + 1
    px = data.adj_close().iloc[stop - window - 1:stop]
    r = np.log(px).diff().iloc[1:].fillna(0.0)
    ws = pd.Series(w, dtype=float)
    port = (r[ws.index] * (ws / ws.sum())).sum(axis=1)
    if downside:
        sigma = math.sqrt(2) * math.sqrt((np.minimum(port, 0) ** 2).mean()) * math.sqrt(252)
    else:
        sigma = port.std(ddof=1) * math.sqrt(252)
    return min(1.0, target / sigma)


def test_new_options_default_off_and_name_unchanged():
    s = vt({R0: {"A": 1.0}})
    assert s.cut_delay == 0 and s.cut_scale == 1.0 and s.downside is False
    assert s.name == "fixed_vt10_L20_s0.1"
    s2 = vt({R0: {"A": 1.0}}, cut_delay=3, cut_scale=0.5, downside=True)
    assert s2.name == "fixed_vt10_L20_s0.1_d3_h0.5_dn"
    with pytest.raises(ValueError):
        vt({R0: {"A": 1.0}}, cut_delay=-1)
    with pytest.raises(ValueError):
        vt({R0: {"A": 1.0}}, cut_scale=0.0)


def test_cut_delay_takes_max_of_recent_raw_exposures():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    s = vt({R0: w}, step=0.0, cut_delay=3)
    for k in (55, 60):
        t = DATES[k]
        want = max(raw_exposure(data, w, DATES[j]) for j in range(k - 3, k + 1))
        assert s.exposure(t, data.truncate(t)) == pytest.approx(want, rel=1e-10)


def test_cut_delay_only_uses_days_with_a_basket():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    r = DATES[30]
    s = vt({R0: w}, step=0.0, cut_delay=5)
    t = DATES[32]
    # t-5..t-3 还没有篮子（返回 max_exposure=1）：取最大值应为 1
    assert s.exposure(t, data.truncate(t)) == pytest.approx(1.0)


def test_cut_scale_halves_the_cut_then_floors():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    raw = raw_exposure(data, w, T)
    got = vt({R0: w}, step=0.0, cut_scale=0.5).exposure(T, data.truncate(T))
    assert got == pytest.approx(1 - 0.5 * (1 - raw), rel=1e-10)
    got_q = vt({R0: w}, step=0.1, cut_scale=0.5).exposure(T, data.truncate(T))
    assert got_q == pytest.approx(math.floor((1 - 0.5 * (1 - raw)) / 0.1 + 1e-9) * 0.1)


def test_downside_volatility():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    got = vt({R0: w}, step=0.0, downside=True).exposure(T, data.truncate(T))
    assert got == pytest.approx(raw_exposure(data, w, T, downside=True), rel=1e-10)


def test_new_options_no_lookahead():
    data = build()
    w = {"A": 0.5, "C": 0.5}
    s = vt({R0: w}, cut_delay=3, cut_scale=0.5, downside=True)
    full = s.exposure(T, data)
    shocked = build()
    shocked.close.loc[DATES[61]:, "A"] *= 0.3
    assert vt({R0: w}, cut_delay=3, cut_scale=0.5, downside=True).exposure(T, shocked) == pytest.approx(full)


@pytest.mark.parametrize("seed", [0, 17])
def test_original_paper_neutral_modes_match_original_symmetric_formula(seed):
    data = build(seed=seed)
    first, second = {"A": .5, "C": .5}, {"A": .2, "B": .3, "C": .5}
    changed = DATES[85]
    strategy = VolTarget(base=Fixed({DATES[30]: first, changed: second}),
        target_vol=.16, window=60, step=.1, max_exposure=1.,
        cut_delay=0, cut_scale=1., downside=False)
    strategy.rebalance_dates(DATES)
    for date in DATES[61:]:
        weights = second if date >= changed else first
        # Archived VolTarget: symmetric sample standard deviation, no delay or
        # cut scaling, then the unchanged exposure grid floor.
        sigma = expected_sigma(data, weights, date, 60)
        raw = min(1., .16 / sigma) if sigma else 1.
        expected = math.floor(raw / .1 + 1e-9) * .1
        assert strategy.exposure(date, data.truncate(date)) == pytest.approx(expected, rel=1e-12, abs=1e-12)
