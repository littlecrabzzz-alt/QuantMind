"""扩展研究的公共指标表与自助法。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/expansion"))
from common import PERIODS, bootstrap_mdd, metrics_table  # noqa: E402


def _nav(seed, n=900):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))), index=index)


def test_periods_fixed():
    assert PERIODS == {"IS": ("2012-01-01", "2019-12-31"),
                       "OOS": ("2020-01-01", "2026-09-30"),
                       "FULL": ("2012-01-01", "2026-09-30")}


def test_metrics_table_slices_and_normalizes():
    nav = pd.DataFrame({"x": _nav(0), "y": _nav(1)})
    bench = pd.DataFrame({"000906.SH": _nav(2), "000906.SH_TR": _nav(3)})
    lowvol = _nav(4)
    table = metrics_table(nav, bench, lowvol, turnover={"x": 1.5})
    row = table[(table.name == "x") & (table.period == "OOS")].iloc[0]
    sliced = nav.x.loc["2020-01-01":"2026-09-30"]
    sliced = sliced / sliced.iloc[0]
    assert row.cagr == pytest.approx((sliced.iloc[-1]) ** (252 / (len(sliced) - 1)) - 1)
    returns = sliced.pct_change().dropna()
    assert row.ann_vol == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert row.max_drawdown == pytest.approx((sliced / sliced.cummax() - 1).min())
    assert row.turnover == 1.5
    other = lowvol.loc[sliced.index].pct_change().dropna()
    assert row.corr_lowvol == pytest.approx(returns.corr(other))
    for column in ("alpha_000906.SH", "beta_000906.SH", "alpha_000906.SH_TR",
                   "beta_000906.SH_TR", "sharpe", "calmar"):
        assert np.isfinite(row[column])
    assert set(table.period) == {"IS", "OOS", "FULL"}


def test_bootstrap_matches_b2_algorithm():
    nav = pd.DataFrame({"x": _nav(5, 300)})
    result = bootstrap_mdd(nav, draws=2000, block=20, seed=0)
    log_returns = np.log1p(nav.x.pct_change().dropna().to_numpy())
    n = len(log_returns)
    rng = np.random.default_rng(0)
    mdds = []
    for _ in range(20):
        starts = rng.integers(0, n, size=(100, (n + 19) // 20))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
        paths = np.cumsum(log_returns[indices], axis=1)
        peaks = np.maximum(0, np.maximum.accumulate(paths, axis=1))
        mdds.append(np.expm1((paths - peaks).min(axis=1)))
    q = np.quantile(np.concatenate(mdds), [0.05, 0.5, 0.95])
    row = result.set_index("name").loc["x"]
    assert [row.mdd_p05, row.mdd_p50, row.mdd_p95] == pytest.approx(list(q))
