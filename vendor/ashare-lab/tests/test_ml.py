import numpy as np
import pandas as pd
import pytest

from ashare_lab.factors import FACTOR_NAMES, compute_factors
from ashare_lab.ml.dataset import make_labels, rank_normalize
from ashare_lab.ml.evaluate import ic_series, ic_summary, quantile_returns
from ashare_lab.ml.models import Ridge, SignedAverage
from ashare_lab.ml.walkforward import walk_forward
from ashare_lab.strategies.lowvol_trend import LowVolTrend
from ashare_lab.strategies.score import ScoreStrategy
from ashare_lab.universe import eligible

from synth import make_data

DATES = pd.bdate_range("2020-01-01", periods=320)
CODES = [f"S{i}" for i in range(8)]


def build(seed=0):
    rng = np.random.default_rng(seed)
    d = make_data(DATES, CODES)
    idx_r = rng.normal(0, 0.01, len(DATES))
    for k, c in enumerate(CODES):
        r = 0.5 * (k + 1) / len(CODES) * idx_r * 2 + rng.normal(0, 0.005 * (k + 1), len(DATES))
        d.close[c] = 10 * np.exp(np.cumsum(r))
    d.close["S0"] = 10 * np.exp(np.cumsum(idx_r))  # S0 与指数同步：beta=1
    d.index_close = pd.DataFrame({"000906.SH": 1000 * np.exp(np.cumsum(idx_r))}, index=DATES)
    d.open = d.close.shift(1).fillna(10.0)
    d.amount = pd.DataFrame(rng.uniform(1e8, 2e8, d.close.shape), index=DATES, columns=CODES)
    d.members = {"000906.SH": pd.DataFrame(True, index=DATES, columns=CODES)}
    d.list_date[:] = pd.Timestamp("2000-01-01")
    full = lambda v: pd.DataFrame(v, index=DATES, columns=CODES, dtype=float)
    d.extra = {
        "total_mv": full(1e6) * np.arange(1, 9),
        "circ_mv": full(1e6),
        "pe_ttm": full(10.0),
        "pb": full(2.0),
        "dv_ttm": full(np.nan),
        "turnover_rate_f": full(1.5),
    }
    d.extra["pe_ttm"]["S3"] = -5.0
    return d


T = DATES[300]


def test_factor_values():
    d = build()
    f = compute_factors(d, [T]).loc[T]
    assert list(f.columns) == FACTOR_NAMES
    lr = np.log(d.close).diff()
    assert f.loc["S2", "rev_20"] == pytest.approx(np.log(d.close.loc[T, "S2"] / d.close["S2"].iloc[280]))
    assert f.loc["S2", "mom_12_1"] == pytest.approx(np.log(d.close["S2"].iloc[280] / d.close["S2"].iloc[50]))
    assert f.loc["S2", "vol_20"] == pytest.approx(lr["S2"].iloc[281:301].std(ddof=1))
    assert f.loc["S0", "beta_250"] == pytest.approx(1.0, abs=1e-9)
    assert f.loc["S4", "log_mv"] == pytest.approx(np.log(5e6))
    assert np.isnan(f.loc["S3", "ep"]) and f.loc["S2", "ep"] == pytest.approx(0.1)
    assert f.loc["S2", "bp"] == pytest.approx(0.5)
    assert f.loc["S2", "dy"] == 0.0
    assert f.loc["S2", "turn_20"] == pytest.approx(1.5)
    simple = np.exp(lr["S2"].iloc[281:301]) - 1
    assert f.loc["S2", "max_20"] == pytest.approx(simple.max())
    illiq = (simple.abs() / d.amount["S2"].iloc[281:301]).mean() * 1e8
    assert f.loc["S2", "illiq_20"] == pytest.approx(illiq)
    ratio = d.amount["S2"].iloc[296:301].mean() / d.amount["S2"].iloc[241:301].mean()
    assert f.loc["S2", "amt_ratio"] == pytest.approx(ratio)


def test_factors_no_lookahead():
    d1, d2 = build(), build()
    d2.close.iloc[301:] *= 3.0
    d2.amount.iloc[301:] *= 0.01
    d2.extra["total_mv"].iloc[301:] *= 5
    d2.index_close.iloc[301:] *= 0.5
    pd.testing.assert_frame_equal(compute_factors(d1, [T]), compute_factors(d2, [T]))


def test_factors_only_eligible_rows():
    d = build()
    d.is_st.loc[T, "S5"] = True
    d.members["000906.SH"].loc[T, "S6"] = False
    f = compute_factors(d, [T])
    codes = set(f.loc[T].index)
    assert "S5" not in codes and "S6" not in codes and len(codes) == 6


def test_eligible_consistent_with_lowvol():
    d = build()
    d.suspended.loc[T, "S1"] = True
    e = eligible(T, d)
    assert not e["S1"] and e.sum() == 7
    w = LowVolTrend(universe="000906.SH", select="all", timing_index=None).target_weights(T, d.truncate(T))
    assert set(w.index) == set(e[e].index)


def test_rank_normalize():
    idx = pd.MultiIndex.from_product([[DATES[0], DATES[1]], ["a", "b", "c", "d"]], names=["date", "code"])
    df = pd.DataFrame({"x": [1, 2, 3, np.nan, 4, 3, 2, 1], "ep": [np.nan, 1, 2, 3, 1, 1, 1, 1]}, index=idx)
    out = rank_normalize(df, fill={"ep": 0.0})
    np.testing.assert_allclose(out["x"].values, [1 / 3, 2 / 3, 1, 0.5, 1, 0.75, 0.5, 0.25])
    assert out["ep"].iloc[0] == 0.0
    assert out["ep"].iloc[4] == pytest.approx(0.625)


def test_labels():
    d = build()
    d.open["S1"] = np.linspace(10, 20, len(DATES))
    d.adj.loc[DATES[110]:, "S1"] = 2.0
    lab = make_labels(d, [DATES[100], DATES[310]], horizon=20)
    r = lab.loc[(DATES[100], "S1")]
    assert r.label_end == DATES[121]
    assert r.ret == pytest.approx(d.open["S1"].iloc[121] * 2.0 / d.open["S1"].iloc[101] - 1)
    assert np.isnan(lab.loc[(DATES[310], "S1")].ret) and pd.isna(lab.loc[(DATES[310], "S1")].label_end)


# ---------- 滚动训练：防泄露 ----------

def synth_ds(seed=0):
    rng = np.random.default_rng(seed)
    cal = pd.bdate_range("2010-01-01", "2019-12-31")
    me = cal[~cal.to_period("M").duplicated(keep="last")]
    codes = [f"c{i}" for i in range(40)]
    idx = pd.MultiIndex.from_product([me, codes], names=["date", "code"])
    X = pd.DataFrame(rng.uniform(0, 1, (len(idx), len(FACTOR_NAMES))), index=idx, columns=FACTOR_NAMES)
    ds = X.copy()
    ds["y"] = (0.3 * X["vol_250"] + rng.normal(0, 0.3, len(idx))).groupby(level=0).rank(pct=True)
    ds["ret"] = ds["y"] - 0.5
    pos = cal.get_indexer(ds.index.get_level_values(0))
    ds["label_end"] = cal[np.minimum(pos + 21, len(cal) - 1)]
    return ds


class Recorder:
    calls = []

    def __init__(self):
        self.info = {}

    def fit(self, Xt, yt, Xv, yv):
        Recorder.calls.append((Xt.index.get_level_values(0), Xv.index.get_level_values(0)))
        self.mean = float(yt.mean())
        return self

    def predict(self, X):
        return np.full(len(X), self.mean) + X["vol_250"].to_numpy() * 1e-9


def test_walk_forward_windows_and_no_leakage():
    ds = synth_ds()
    Recorder.calls = []
    scores, diag = walk_forward(ds, Recorder, years=range(2015, 2020), train_years=4)
    assert len(Recorder.calls) == 5
    for year, (tr, va) in zip(range(2015, 2020), Recorder.calls):
        t_star = ds.index.get_level_values(0)[ds.index.get_level_values(0).year == year].min()
        tr_end = ds.loc[ds.index.get_level_values(0).isin(tr), "label_end"].max()
        va_end = ds.loc[ds.index.get_level_values(0).isin(va), "label_end"].max()
        assert tr.year.min() == year - 5 and tr.year.max() == year - 2
        assert set(va.year) == {year - 1}
        assert va_end <= t_star and tr_end < va.min()
    pred_dates = scores.index.get_level_values(0)
    assert pred_dates.year.min() == 2015 and pred_dates.year.max() == 2019
    assert len(scores) == (ds.index.get_level_values(0).year >= 2015).sum()
    assert {"year", "n_train", "n_valid", "train_ic", "valid_ic", "train_end", "valid_end"} <= set(diag.columns)


def test_walk_forward_predictions_ignore_same_year_labels():
    ds1, ds2 = synth_ds(), synth_ds()
    mask = ds2.index.get_level_values(0).year == 2018
    ds2.loc[mask, "y"] = 1.0 - ds2.loc[mask, "y"]
    s1, _ = walk_forward(ds1, Ridge, years=[2018])
    s2, _ = walk_forward(ds2, Ridge, years=[2018])
    pd.testing.assert_series_equal(s1, s2)


# ---------- 模型 ----------

def test_ridge_recovers_linear_signal():
    ds = synth_ds()
    tr = ds[ds.index.get_level_values(0).year < 2018]
    va = ds[ds.index.get_level_values(0).year == 2018]
    m = Ridge().fit(tr[FACTOR_NAMES], tr["y"], va[FACTOR_NAMES], va["y"])
    coef = pd.Series(m.info["coef"], index=FACTOR_NAMES)
    assert coef.abs().idxmax() == "vol_250" and coef["vol_250"] > 0
    assert m.info["lambda"] in (0.1, 1, 10, 100)
    assert np.corrcoef(m.predict(va[FACTOR_NAMES]), va["y"])[0, 1] > 0.2


def test_signed_average():
    ds = synth_ds()
    ds["mom_12_1"] = 1 - ds["y"] + np.random.default_rng(1).normal(0, 0.1, len(ds))
    m = SignedAverage().fit(ds[FACTOR_NAMES], ds["y"], ds[FACTOR_NAMES], ds["y"])
    signs = dict(zip(FACTOR_NAMES, m.info["signs"]))
    assert signs["vol_250"] == 1 and signs["mom_12_1"] == -1
    p = m.predict(ds[FACTOR_NAMES])
    assert p.shape == (len(ds),)


def test_lgbm_learns_nonlinear():
    pytest.importorskip("lightgbm")
    from ashare_lab.ml.models import LGBM

    ds = synth_ds()
    ds["y"] = ((ds["bp"] > 0.5) & (ds["vol_250"] < 0.5)).astype(float) + np.random.default_rng(2).normal(0, 0.3, len(ds))
    tr = ds[ds.index.get_level_values(0).year < 2018]
    va = ds[ds.index.get_level_values(0).year == 2018]
    m = LGBM().fit(tr[FACTOR_NAMES], tr["y"], va[FACTOR_NAMES], va["y"])
    assert np.corrcoef(m.predict(va[FACTOR_NAMES]), va["y"])[0, 1] > 0.5
    imp = m.info["importance_gain"]
    assert sorted(imp, key=imp.get)[-2:] in (["bp", "vol_250"], ["vol_250", "bp"])
    assert m.info["best_iteration"] >= 1


# ---------- 评估与策略 ----------

def test_ic_and_quantiles():
    idx = pd.MultiIndex.from_product([[DATES[0]], [f"c{i}" for i in range(20)]], names=["date", "code"])
    s = pd.Series(np.arange(20.0), index=idx)
    ic = ic_series(s, s * 2)
    assert ic.iloc[0] == pytest.approx(1.0)
    assert ic_series(s, -s).iloc[0] == pytest.approx(-1.0)
    summ = ic_summary(pd.Series([0.1, 0.0, 0.2, 0.1]))
    assert summ["mean"] == pytest.approx(0.1) and summ["hit"] == pytest.approx(0.75) and summ["n"] == 4
    q = quantile_returns(s, s / 100, q=5)
    assert list(q.columns) == [1, 2, 3, 4, 5]
    assert q.iloc[0, 0] < q.iloc[0, 4]


def test_score_strategy():
    d = build()
    idx = pd.MultiIndex.from_product([[T], CODES], names=["date", "code"])
    s = pd.Series(np.arange(8.0), index=idx)
    d.is_st.loc[T, "S7"] = True
    st = ScoreStrategy(scores=s, top_n=3, label="x")
    assert st.name == "x"
    assert list(st.rebalance_dates(DATES)) == [T]
    w = st.target_weights(T, d.truncate(T))
    assert sorted(w.index) == ["S4", "S5", "S6"] and w.sum() == pytest.approx(1.0)
