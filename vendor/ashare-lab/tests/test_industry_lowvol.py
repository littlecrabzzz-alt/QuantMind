"""B1 行业中性低波动：行业归属、行业内选股、行业倾斜组合的验收测试。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.industry import UNCLASSIFIED, industry_at
from ashare_lab.strategies.industry_lowvol import IndustryLowVol
from ashare_lab.strategies.lowvol_trend import LowVolTrend

from synth import make_data

DATES = pd.bdate_range("2024-01-01", periods=80)
T = DATES[60]
# 波动从低到高：A B G C D E F H I J K
AMPS = {"A": 0.001, "B": 0.002, "C": 0.003, "D": 0.004, "E": 0.005, "F": 0.006,
        "G": 0.0025, "H": 0.02, "I": 0.03, "J": 0.04, "K": 0.05}
IND = {"A": "X", "B": "X", "C": "X", "D": "X", "E": "X", "F": "X",
       "G": "Y", "H": "Y", "I": "Y", "J": "Y", "K": "Z"}


def table(mapping, start="2000-01-01"):
    return pd.DataFrame({
        "code": list(mapping),
        "l1_code": [f"{v}.SI" for v in mapping.values()],
        "l1_name": list(mapping.values()),
        "in_date": [start] * len(mapping),
        "out_date": [None] * len(mapping),
    })


def build(codes):
    data = make_data(DATES, codes)
    sign = np.where(np.arange(len(DATES)) % 2 == 0, 1.0, -1.0)
    for c in codes:
        data.close[c] = 10 * np.exp(np.cumsum(sign * AMPS[c]))
    data.open = data.close.copy()
    data.amount[:] = 1e8
    data.extra["circ_mv"] = pd.DataFrame(1.0, index=DATES, columns=codes)
    return data


def strat(industry, **kw):
    base = dict(universe="IDX", vol_window=20, top_n=5, min_list_days=10,
                industry=industry)
    base.update(kw)
    return IndustryLowVol(**base)


def weights(s, data, t=T):
    w = s.target_weights(t, data.truncate(t))
    assert w.index.is_unique and (w >= 0).all()
    return w[w > 0].sort_index()


TEN = list("ABCDEFGHIJ")


# ---------- industry_at ----------

def test_industry_at_boundaries_gaps_and_future():
    tbl = pd.DataFrame({
        "code": ["A", "A", "A", "B", "L"],
        "l1_code": ["X.SI", "X.SI", "Y.SI", "X.SI", "Y.SI"],
        "l1_name": ["X", "X", "Y", "X", "Y"],
        "in_date": ["2000-01-01", "2024-01-15", "2024-02-15", "2000-01-01", "2025-01-01"],
        "out_date": ["2024-01-10", "2024-02-14", None, None, None],
    })
    codes = ["A", "B", "L", "M"]
    at = lambda d: industry_at(pd.Timestamp(d), tbl, codes)
    assert at("2024-02-14")["A"] == "X"
    assert at("2024-02-15")["A"] == "Y"           # 生效日当天即切换
    assert at("2024-01-12")["A"] == "X"           # 记录间的空档沿用最近一条
    got = at("2024-03-01")
    assert list(got.index) == codes
    assert got["B"] == "X"
    assert got["L"] == UNCLASSIFIED               # 未来才有的分类不能提前用
    assert got["M"] == UNCLASSIFIED               # 没有记录
    assert at("2025-01-01")["L"] == "Y"


def test_industry_at_accepts_datetime_columns():
    tbl = table({"A": "X"})
    tbl["in_date"] = pd.to_datetime(tbl["in_date"])
    tbl["out_date"] = pd.to_datetime(tbl["out_date"])
    assert industry_at(T, tbl, ["A"])["A"] == "X"


# ---------- neutral, count weighting ----------

def test_neutral_count_picks_within_industry():
    data = build(TEN)
    w = weights(strat(table({c: IND[c] for c in TEN})), data)
    # X 占 6/10 -> 3 只，Y 占 4/10 -> 2 只；全局最低波的前 5 只里只有 1 只 Y
    assert list(w.index) == ["A", "B", "C", "G", "H"]
    np.testing.assert_allclose(w.to_numpy(), 0.2)
    assert w.sum() == pytest.approx(1.0)


def test_neutral_at_least_one_per_industry_and_weights_follow_share():
    codes = TEN + ["K"]
    data = build(codes)
    w = weights(strat(table({c: IND[c] for c in codes})), data)
    # X 6/11*5=2.73->3，Y 4/11*5=1.82->2，Z 0.45->0 但至少 1
    assert list(w.index) == ["A", "B", "C", "G", "H", "K"]
    np.testing.assert_allclose(w[["A", "B", "C"]], 6 / 11 / 3)
    np.testing.assert_allclose(w[["G", "H"]], 4 / 11 / 2)
    assert w["K"] == pytest.approx(1 / 11)
    assert w.sum() == pytest.approx(1.0)


def test_neutral_round_half_up_and_capped_by_count():
    data = build(TEN)
    # top_n=15：X 9 只但只有 6 只可选，Y 6 只但只有 4 只 -> 全选
    w = weights(strat(table({c: IND[c] for c in TEN}), top_n=15), data)
    assert list(w.index) == TEN
    np.testing.assert_allclose(w[list("ABCDEF")], 0.6 / 6)
    # top_n=5 时 X=3.0、Y=2.0；top_n=3 时 X=1.8->2、Y=1.2->1
    w3 = weights(strat(table({c: IND[c] for c in TEN}), top_n=3), data)
    assert list(w3.index) == ["A", "B", "G"]
    # top_n=1 时 X=0.6->1、Y=0.4->0 但至少 1
    w1 = weights(strat(table({c: IND[c] for c in TEN}), top_n=1), data)
    assert list(w1.index) == ["A", "G"]
    assert w1["A"] == pytest.approx(0.6) and w1["G"] == pytest.approx(0.4)


def test_unclassified_is_its_own_group():
    data = build(TEN)
    tbl = table({c: IND[c] for c in TEN if c != "J"})  # J 没有行业记录
    w = weights(strat(tbl), data)
    # X 6/10->3，Y 3/10->2 (1.5 四舍五入)，未分类 1/10->0.5->1
    assert list(w.index) == ["A", "B", "C", "G", "H", "J"]
    assert w["J"] == pytest.approx(0.1)
    assert w.sum() == pytest.approx(1.0)


# ---------- neutral, cap weighting ----------

def test_neutral_cap_uses_circ_mv_share():
    data = build(TEN)
    data.extra["circ_mv"].loc[:, list("GHIJ")] = 6.0   # Y 市值占 24/30 = 0.8
    w = weights(strat(table({c: IND[c] for c in TEN}), top_n=4, weighting="cap"), data)
    # X 0.2*4=0.8->1 只，Y 0.8*4=3.2->3 只
    assert list(w.index) == ["A", "G", "H", "I"]
    assert w["A"] == pytest.approx(0.2)
    np.testing.assert_allclose(w[["G", "H", "I"]], 0.8 / 3)


def test_neutral_cap_reads_market_value_at_t_not_later():
    data = build(TEN)
    data.extra["circ_mv"].loc[DATES[61]:, list("GHIJ")] = 100.0  # t 之后才变
    s = strat(table({c: IND[c] for c in TEN}), top_n=4, weighting="cap")
    w = s.target_weights(T, data)  # 故意传入完整数据
    assert w[w > 0].sum() == pytest.approx(1.0)
    assert w["A"] == pytest.approx(0.6 / 2)  # X 0.6*4=2.4->2 只
    assert list(w[w > 0].sort_index().index) == ["A", "B", "G", "H"]


# ---------- tilt ----------

def test_tilt_copies_lowvol_industry_weights_equal_within():
    data = build(TEN)
    tbl = table({c: IND[c] for c in TEN})
    w = weights(strat(tbl, top_n=4, mode="tilt"), data)
    # 全局低波前 4：A B G C -> X 3/4，Y 1/4；行业内所有可选股票等权
    assert list(w.index) == TEN
    np.testing.assert_allclose(w[list("ABCDEF")], 0.75 / 6)
    np.testing.assert_allclose(w[list("GHIJ")], 0.25 / 4)
    w5 = weights(strat(tbl, top_n=5, mode="tilt"), data)
    np.testing.assert_allclose(w5[list("ABCDEF")], 0.8 / 6)
    np.testing.assert_allclose(w5[list("GHIJ")], 0.2 / 4)


def test_tilt_selection_matches_plain_lowvol():
    data = build(TEN)
    plain = LowVolTrend(universe="IDX", vol_window=20, top_n=4, min_list_days=10,
                        timing_index=None).target_weights(T, data.truncate(T))
    assert sorted(plain[plain > 0].index) == ["A", "B", "C", "G"]


# ---------- filters, look-ahead, naming ----------

def test_filters_and_suspension_respected():
    data = build(TEN)
    data.is_st.loc[:, "A"] = True
    data.suspended.loc[T, "G"] = True
    data.close.loc[T, "G"] = np.nan
    w = weights(strat(table({c: IND[c] for c in TEN})), data)
    assert "A" not in w.index and "G" not in w.index
    # 剩 X 5 只、Y 3 只：X 5/8*5=3.125->3，Y 1.875->2
    assert list(w.index) == ["B", "C", "D", "H", "I"]


def test_future_reclassification_and_future_prices_ignored():
    data = build(TEN)
    tbl = table({c: IND[c] for c in TEN})
    future = pd.DataFrame({"code": ["A"], "l1_code": ["Y.SI"], "l1_name": ["Y"],
                           "in_date": [str(DATES[70].date())], "out_date": [None]})
    tbl.loc[tbl.code == "A", "out_date"] = str(DATES[69].date())
    tbl2 = pd.concat([tbl, future], ignore_index=True)
    s = strat(tbl2)
    full = s.target_weights(T, data).sort_index()
    cut = s.target_weights(T, data.truncate(T)).sort_index()
    pd.testing.assert_series_equal(full, cut)
    assert list(full[full > 0].index) == ["A", "B", "C", "G", "H"]


def test_names_and_no_timing_by_default():
    tbl = table({"A": "X"})
    assert strat(tbl, vol_window=250, top_n=50).name == "indneutral_count_W250_N50"
    assert strat(tbl, vol_window=250, top_n=50, weighting="cap").name == "indneutral_cap_W250_N50"
    assert strat(tbl, vol_window=250, top_n=50, mode="tilt").name == "indtilt_W250_N50"
    s = strat(tbl)
    assert s.exposure(T, build(TEN)) == 1.0
    with pytest.raises(ValueError):
        strat(tbl, mode="bogus").target_weights(T, build(TEN).truncate(T))
    with pytest.raises(ValueError):
        strat(tbl, weighting="bogus").target_weights(T, build(TEN).truncate(T))
