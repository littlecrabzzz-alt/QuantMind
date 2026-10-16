"""S4 参数集成与年度重选。"""

import numpy as np
import pandas as pd
import pytest

from ashare_lab import metrics
from ashare_lab.strategies.ensemble import AnnualReselect, EnsembleVolTarget, neighbourhood
from synth import FixedStrategy, make_data


DATES = pd.bdate_range("2020-01-01", periods=40)


def test_ensemble_weights_and_exposure():
    t = DATES[20]
    m1 = FixedStrategy({str(t.date()): {"A": 1.0}}, {str(t.date()): 0.5})
    m2 = FixedStrategy({str(t.date()): {"B": 1.0}}, {str(t.date()): 1.0})
    data = make_data(DATES, ["A", "B"])
    ensemble = EnsembleVolTarget(members=[m1, m2])
    assert list(ensemble.rebalance_dates(DATES)) == [t]
    weights = ensemble.target_weights(t, data.truncate(t))
    assert weights.to_dict() == pytest.approx({"A": 1 / 3, "B": 2 / 3})
    assert ensemble.exposure(t, data.truncate(t)) == pytest.approx(0.75)


def test_ensemble_all_zero_exposure_uses_plain_average():
    t = DATES[20]
    m1 = FixedStrategy({str(t.date()): {"A": 1.0}}, {str(t.date()): 0.0})
    m2 = FixedStrategy({str(t.date()): {"B": 0.5, "A": 0.5}}, {str(t.date()): 0.0})
    data = make_data(DATES, ["A", "B"])
    ensemble = EnsembleVolTarget(members=[m1, m2])
    ensemble.rebalance_dates(DATES)
    weights = ensemble.target_weights(t, data.truncate(t))
    assert weights.to_dict() == pytest.approx({"A": 0.75, "B": 0.25})
    assert ensemble.exposure(t, data.truncate(t)) == 0.0


def test_ensemble_requires_same_rebalance_dates():
    m1 = FixedStrategy({"2020-01-10": {"A": 1.0}})
    m2 = FixedStrategy({"2020-01-13": {"A": 1.0}})
    with pytest.raises(ValueError):
        EnsembleVolTarget(members=[m1, m2]).rebalance_dates(DATES)


def test_neighbourhood_definition():
    coords = {"a": (0, 0), "b": (0, 1), "c": (1, 0), "d": (1, 1), "e": (0, 2)}
    assert set(neighbourhood("a", coords)) == {"a", "b", "c"}
    assert set(neighbourhood("b", coords)) == {"a", "b", "d", "e"}


def _grid_nav(n=1100, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2016-01-01", periods=n)
    drift = {"p0": 0.0002, "p1": 0.0006, "p2": 0.0009, "p3": 0.0001}
    vol = {"p0": 0.01, "p1": 0.008, "p2": 0.02, "p3": 0.01}
    return pd.DataFrame({k: np.exp(np.cumsum(rng.normal(drift[k], vol[k], n))) for k in drift},
                        index=index)


def _expected(nav, coords, t, lookback=756):
    window = nav.loc[:t].iloc[-(lookback + 1):]
    calmar = {k: metrics.calmar(window[k]) for k in nav}
    score = {k: np.mean([calmar[j] for j in neighbourhood(k, coords)]) for k in nav}
    return max(nav.columns, key=lambda k: (score[k], -list(nav.columns).index(k)))


def test_annual_reselect_choice_and_no_lookahead():
    nav = _grid_nav()
    coords = {"p0": (0,), "p1": (1,), "p2": (2,), "p3": (3,)}
    members = {k: FixedStrategy({}) for k in nav}
    strategy = AnnualReselect(members=members, grid_nav=nav, coords=coords, default="p3")
    strategy.rebalance_dates(nav.index)
    year_ends = nav.index[~nav.index.year.duplicated(keep="last")][:-1]
    for t in year_ends:
        enough = len(nav.loc[:t]) >= 757
        expected = _expected(nav, coords, t) if enough else "p3"
        assert strategy.selection(t) == expected
        # 年内（年末之后）沿用该选择。
        later = nav.index[nav.index > t][:5]
        assert all(strategy.selection(d) == expected for d in later)
    shocked = nav.copy()
    cut = year_ends[-1]
    shocked.loc[shocked.index > cut] *= 0.1
    other = AnnualReselect(members=members, grid_nav=shocked, coords=coords, default="p3")
    other.rebalance_dates(nav.index)
    assert other.selection(cut) == strategy.selection(cut)


def test_annual_reselect_delegates_to_selected_member():
    dates = pd.bdate_range("2020-12-01", periods=40)
    t = dates[dates.year == 2020][-1]
    jan = dates[dates.year == 2021][-1]
    schedule = {str(t.date()): {"A": 1.0}, str(jan.date()): {"A": 1.0}}
    m_a = FixedStrategy(schedule, {str(t.date()): 0.4})
    schedule_b = {str(t.date()): {"B": 1.0}, str(jan.date()): {"B": 1.0}}
    m_b = FixedStrategy(schedule_b, {str(t.date()): 0.9})
    nav = pd.DataFrame({"a": 1.0, "b": 1.0}, index=dates)
    strategy = AnnualReselect(members={"a": m_a, "b": m_b}, grid_nav=nav,
                              coords={"a": (0,), "b": (1,)}, default="b")
    rebalances = strategy.rebalance_dates(dates)
    assert t in rebalances
    data = make_data(dates, ["A", "B"])
    assert strategy.target_weights(t, data.truncate(t)).to_dict() == {"B": 1.0}
    assert strategy.exposure(t, data.truncate(t)) == pytest.approx(0.9)
