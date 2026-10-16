import math

import numpy as np
import pandas as pd
import pytest

from ashare_lab import metrics as m

IDX = pd.bdate_range("2024-01-01", periods=5)
NAV = pd.Series([1.0, 2.0, 1.0, 1.5, 2.5], index=IDX)


def test_max_drawdown_and_series():
    assert m.max_drawdown(NAV) == pytest.approx(-0.5)
    np.testing.assert_allclose(m.drawdown_series(NAV).values, [0, 0, -0.5, -0.25, 0])


def test_drawdown_duration():
    assert m.max_drawdown_duration(NAV) == 2
    assert m.max_drawdown_duration(pd.Series([1, 2, 3.0], index=IDX[:3])) == 0


def test_ulcer():
    assert m.ulcer_index(NAV) == pytest.approx(math.sqrt((0.25 + 0.0625) / 5))


def test_cagr_vol_sharpe_calmar():
    assert m.cagr(NAV) == pytest.approx(2.5 ** (252 / 4) - 1)
    r = NAV.pct_change().dropna()
    assert m.ann_vol(NAV) == pytest.approx(r.std(ddof=1) * math.sqrt(252))
    assert m.sharpe(NAV) == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(252))
    assert m.calmar(NAV) == pytest.approx(m.cagr(NAV) / 0.5)


def test_annual_returns_and_worst_month():
    idx = pd.DatetimeIndex(["2022-12-30", "2023-06-30", "2023-12-29", "2024-03-29", "2024-12-31"])
    nav = pd.Series([100, 90, 110, 99, 121], index=idx, dtype=float)
    ar = m.annual_returns(nav)
    assert ar.loc[2023] == pytest.approx(0.10)
    assert ar.loc[2024] == pytest.approx(0.10)
    assert m.worst_month(nav) == pytest.approx(-0.10)
