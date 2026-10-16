"""B3 多因子：PIT 质量/价值因子、合成打分、缓冲选股的验收测试。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.data.fundamentals import Fundamentals
from ashare_lab.multifactor import (
    GROUPS, BufferScoreStrategy, composite, compute_b3_factors, gm_std, value_factors,
)
from ashare_lab.strategies.lowvol_trend import LowVolTrend

from synth import make_data

D = pd.Timestamp


def table(rows, fields):
    cols = ["code", "end_date", "report_type", "update_flag", "ann_date", "effective_date", *fields]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("end_date", "ann_date", "effective_date"):
        df[c] = pd.to_datetime(df[c])
    for f in fields:
        df[f] = df[f].astype(float)
    return df


QUARTERS = pd.date_range("2018-03-31", periods=12, freq="QE")  # 2018Q1 .. 2020Q4


def income_rows(code, margins, revenue_q=100.0, lag_days=30, ni_q=10.0):
    """按单季毛利率构造累计口径的利润表；每期报告期后 lag_days 天公告。"""
    rows, cum_rev, cum_cost, cum_ni = [], 0.0, 0.0, 0.0
    for e, m in zip(QUARTERS, margins):
        if e.month == 3:
            cum_rev = cum_cost = cum_ni = 0.0
        cum_rev += revenue_q
        cum_cost += revenue_q * (1 - m)
        cum_ni += ni_q
        ann = e + pd.Timedelta(days=lag_days)
        rows.append((code, e, 1, 1, ann, ann, cum_rev, cum_rev, cum_cost, cum_ni))
    return rows


INC_FIELDS = ["total_revenue", "revenue", "oper_cost", "n_income_attr_p"]


def ttm_margin_path(margins):
    """单季毛利率 -> 每个报告期的 TTM 毛利率（单季收入相同时即近 4 季均值）。"""
    s = pd.Series(margins, index=QUARTERS)
    return s.rolling(4).mean()


def fund_with(margins_by_code, equity=200.0, lag_days=30):
    inc = []
    for code, m in margins_by_code.items():
        inc += income_rows(code, m, lag_days=lag_days)
    bal = [(code, e, 1, 1, e + pd.Timedelta(days=lag_days), e + pd.Timedelta(days=lag_days), equity)
           for code in margins_by_code for e in QUARTERS]
    return Fundamentals({
        "income": table(inc, INC_FIELDS),
        "balance": table(bal, ["total_hldr_eqy_exc_min_int"]),
    })


STABLE = [0.30] * 12
WAVY = [0.20, 0.40, 0.25, 0.35, 0.10, 0.50, 0.30, 0.30, 0.20, 0.45, 0.15, 0.60]  # 首末 TTM 不同，PIT 与对照窗口可区分


# ---------- gm_std ----------

def test_gm_std_uses_last_8_visible_ttm_margins():
    f = fund_with({"S.SZ": STABLE, "W.SZ": WAVY})
    d = D("2021-03-01")  # 2020Q4 已公告（2021-01-30）
    got = gm_std(f, d)
    path = ttm_margin_path(WAVY).dropna()            # 2018Q4 .. 2020Q4 共 9 期
    want = path.iloc[-8:].std(ddof=1)
    assert got["W.SZ"] == pytest.approx(want, rel=1e-9)
    assert got["S.SZ"] == pytest.approx(0.0, abs=1e-12)


def test_gm_std_point_in_time():
    f = fund_with({"W.SZ": WAVY})
    before = gm_std(f, D("2021-01-29"))["W.SZ"]       # 2020Q4 尚未公告
    path = ttm_margin_path(WAVY).dropna()
    assert before == pytest.approx(path.iloc[-9:-1].std(ddof=1), rel=1e-9)
    naive = gm_std(f, D("2021-01-29"), naive=True)["W.SZ"]  # 对照组：报告期一到就可见
    assert naive == pytest.approx(path.iloc[-8:].std(ddof=1), rel=1e-9)


def test_gm_std_requires_min_obs_and_revenue():
    f = fund_with({"W.SZ": WAVY})
    # 2019-08-01 时可见 2018Q1..2019Q2，TTM 只有 2018Q4..2019Q2 三期 (< 4)
    assert np.isnan(gm_std(f, D("2019-08-01"))["W.SZ"])
    assert not np.isnan(gm_std(f, D("2019-11-01"))["W.SZ"])  # 加上 2019Q3 共 4 期
    bank = table([("B.SH", e, 1, 1, e + pd.Timedelta(days=30), e + pd.Timedelta(days=30),
                   100.0, 100.0, np.nan, 10.0) for e in QUARTERS], INC_FIELDS)
    fb = Fundamentals({"income": bank})
    assert np.isnan(gm_std(fb, D("2021-03-01")).get("B.SH", np.nan))


# ---------- value_factors ----------

def test_value_factors_units_and_pit():
    f = fund_with({"S.SZ": STABLE}, equity=200.0)
    mv = pd.Series({"S.SZ": 0.1})                    # total_mv 单位万元 -> 1000 元
    d = D("2021-03-01")
    v = value_factors(f, d, mv)
    assert v.loc["S.SZ", "ep"] == pytest.approx(40.0 / 1000.0)   # TTM 净利 4 季 × 10
    assert v.loc["S.SZ", "bp"] == pytest.approx(200.0 / 1000.0)
    early = value_factors(f, D("2018-04-15"), mv)    # 还没有任何报告
    assert "S.SZ" not in early.index or early.loc["S.SZ"].isna().all()


def test_value_factors_keeps_negative_earnings_and_drops_missing_mv():
    rows = income_rows("L.SZ", STABLE, ni_q=-5.0)
    f = Fundamentals({"income": table(rows, INC_FIELDS)})
    v = value_factors(f, D("2021-03-01"), pd.Series({"L.SZ": 0.1, "M.SZ": np.nan}))
    assert v.loc["L.SZ", "ep"] == pytest.approx(-20.0 / 1000.0)
    assert np.isnan(v.loc["L.SZ", "bp"])            # 无资产负债表
    assert "M.SZ" not in v.index or v.loc["M.SZ"].isna().all()


# ---------- composite ----------

def factor_frame():
    idx = pd.MultiIndex.from_product([[D("2020-01-31")], list("ABCD")], names=["date", "code"])
    return pd.DataFrame({
        "vol_250": [0.01, 0.02, 0.03, 0.04],         # 低波 A 最好
        "roe_ttm": [0.05, 0.20, 0.10, np.nan],
        "gm_std": [np.nan, 0.01, 0.05, 0.02],
        "ep": [0.10, 0.05, 0.08, 0.02],
        "bp": [1.0, 0.5, 0.8, 0.2],
        "dy": [3.0, 0.0, 2.0, 1.0],
    }, index=idx)


def test_groups_definition():
    assert GROUPS["lowvol"] == {"vol_250": -1}
    assert GROUPS["quality"] == {"roe_ttm": 1, "gm_std": -1}
    assert GROUPS["value"] == {"ep": 1, "bp": 1, "dy": 1}


def test_composite_rank_average_within_and_across_groups():
    s = composite(factor_frame(), ["lowvol", "quality", "value"]).loc[D("2020-01-31")]
    # 低波排名（越大越好）：A 1, B .75, C .5, D .25
    # 质量：roe 在 A,B,C 中 A 1/3 B 1 C 2/3；gm_std 在 B,C,D 中取负：B 1 C 1/3 D 2/3
    #   A=1/3, B=1, C=(2/3+1/3)/2=.5, D=2/3
    # 价值：ep A 1 B .5 C .75 D .25；bp 同 ep；dy A 1 B .25 C .75 D .5
    #   A 1, B 5/12, C .75, D 1/3
    want = {"A": (1 + 1 / 3 + 1) / 3, "B": (0.75 + 1 + 5 / 12) / 3,
            "C": (0.5 + 0.5 + 0.75) / 3, "D": (0.25 + 2 / 3 + 1 / 3) / 3}
    for k, v in want.items():
        assert s[k] == pytest.approx(v, rel=1e-12)


def test_composite_requires_every_group_and_single_group_order():
    ff = factor_frame()
    ff.loc[(D("2020-01-31"), "D"), ["ep", "bp", "dy"]] = np.nan
    s = composite(ff, ["lowvol", "quality", "value"]).loc[D("2020-01-31")]
    assert np.isnan(s["D"]) or "D" not in s.index
    lv = composite(factor_frame(), ["lowvol"]).loc[D("2020-01-31")]
    assert list(lv.sort_values(ascending=False).index) == list("ABCD")


def test_composite_ranks_per_date():
    a = factor_frame()
    b = factor_frame().rename(index={D("2020-01-31"): D("2020-02-28")}, level="date")
    b["vol_250"] = b["vol_250"] * 100  # 截面排名不变
    s = composite(pd.concat([a, b]), ["lowvol"])
    np.testing.assert_allclose(s.loc[D("2020-01-31")].sort_index(), s.loc[D("2020-02-28")].sort_index())


# ---------- compute_b3_factors ----------

DATES = pd.bdate_range("2020-06-01", periods=300)
CODES = ["S.SZ", "W.SZ", "X.SZ"]


def market():
    rng = np.random.default_rng(0)
    data = make_data(DATES, CODES)
    for i, c in enumerate(CODES):
        data.close[c] = 10 * np.exp(np.cumsum(rng.normal(0, 0.01 * (i + 1), len(DATES))))
    data.open = data.close.copy()
    data.amount[:] = 1e8
    data.extra["total_mv"] = pd.DataFrame(0.1, index=DATES, columns=CODES)
    data.extra["dv_ttm"] = pd.DataFrame(1.5, index=DATES, columns=CODES)
    data.extra["dv_ttm"].loc[:, "X.SZ"] = np.nan
    return data


def test_compute_factors_matches_components_and_lowvol():
    data = market()
    f = fund_with({"S.SZ": STABLE, "W.SZ": WAVY})
    t = DATES[280]
    out = compute_b3_factors(data, f, [t], universe="IDX", vol_window=250, min_list_days=10)
    snap = out.loc[t]
    lv = LowVolTrend(universe="IDX", vol_window=250, min_list_days=10, timing_index=None)
    vol = lv.candidate_volatility(t, data.truncate(t))
    np.testing.assert_allclose(snap["vol_250"].reindex(vol.index), vol)
    assert snap.loc["S.SZ", "roe_ttm"] == pytest.approx(f.roe_ttm(t)["S.SZ"])
    assert snap.loc["W.SZ", "gm_std"] == pytest.approx(gm_std(f, t)["W.SZ"])
    assert snap.loc["S.SZ", "ep"] == pytest.approx(40.0 / 1000.0)
    assert snap.loc["X.SZ", "dy"] == 0.0                # 缺失股息率记 0（不分红）
    assert np.isnan(snap.loc["X.SZ", "roe_ttm"])        # 没有财报
    assert set(out.columns) >= {"vol_250", "roe_ttm", "gm_std", "ep", "bp", "dy"}


def test_compute_factors_no_lookahead():
    t = DATES[280]
    base = compute_b3_factors(market(), fund_with({"S.SZ": STABLE, "W.SZ": WAVY}), [t],
                              universe="IDX", vol_window=250, min_list_days=10)
    shocked = market()
    shocked.close.loc[DATES[281]:, :] *= 2
    shocked.extra["total_mv"].loc[DATES[281]:, :] = 99.0
    late = fund_with({"S.SZ": STABLE, "W.SZ": WAVY}, lag_days=30)
    extra = table([("S.SZ", D("2021-03-31"), 1, 1, t + pd.Timedelta(days=1), t + pd.Timedelta(days=1),
                    1e6, 1e6, 0.0, 1e6)], INC_FIELDS)
    late = Fundamentals({"income": pd.concat([table(sum((income_rows(c, m) for c, m in
                                                         {"S.SZ": STABLE, "W.SZ": WAVY}.items()), []),
                                                    INC_FIELDS), extra]),
                         "balance": table([(c, e, 1, 1, e + pd.Timedelta(days=30), e + pd.Timedelta(days=30), 200.0)
                                           for c in ("S.SZ", "W.SZ") for e in QUARTERS],
                                          ["total_hldr_eqy_exc_min_int"])})
    got = compute_b3_factors(shocked, late, [t], universe="IDX", vol_window=250, min_list_days=10)
    pd.testing.assert_frame_equal(base, got)


def test_compute_factors_naive_flag_changes_visibility():
    data = market()
    f = fund_with({"S.SZ": STABLE, "W.SZ": WAVY}, lag_days=60)
    t = D("2021-02-15")  # 2020Q4 报告期已过、尚未公告（2021-03-01）
    t = DATES[DATES.searchsorted(t)]
    pit = compute_b3_factors(data, f, [t], universe="IDX", vol_window=250, min_list_days=10)
    naive = compute_b3_factors(data, f, [t], universe="IDX", vol_window=250, min_list_days=10, naive=True)
    assert pit.loc[(t, "W.SZ"), "gm_std"] != pytest.approx(naive.loc[(t, "W.SZ"), "gm_std"])


# ---------- BufferScoreStrategy ----------

def scores(rows):
    idx = pd.MultiIndex.from_tuples([(D(d), c) for d, c, _ in rows], names=["date", "code"])
    return pd.Series([v for *_, v in rows], index=idx)


def test_buffer_keeps_holdings_within_keep_rank():
    dates = pd.bdate_range("2024-01-01", periods=40)
    data = make_data(dates, list("ABCDE"))
    data.amount[:] = 1e8
    t1, t2 = dates[20], dates[30]
    sc = scores([(t1, c, v) for c, v in zip("ABCDE", [5, 4, 3, 2, 1])] +
                [(t2, c, v) for c, v in zip("ABCDE", [3, 1, 5, 4, 2])])
    s = BufferScoreStrategy(scores=sc, top_n=2, keep_rank=3, universe="IDX", min_list_days=10)
    assert list(s.rebalance_dates(dates)) == [t1, t2]
    w1 = s.target_weights(t1, data.truncate(t1))
    assert sorted(w1[w1 > 0].index) == ["A", "B"]
    w2 = s.target_weights(t2, data.truncate(t2))
    # t2 排名：C D A E B；A 排第 3 (<= keep_rank) 保留，B 掉出；补入最高的 C
    assert sorted(w2[w2 > 0].index) == ["A", "C"]
    np.testing.assert_allclose(w2[w2 > 0], 0.5)


def test_buffer_with_keep_equal_top_is_plain_top_n_and_respects_eligibility():
    dates = pd.bdate_range("2024-01-01", periods=40)
    data = make_data(dates, list("ABCDE"))
    data.amount[:] = 1e8
    t1, t2 = dates[20], dates[30]
    sc = scores([(t1, c, v) for c, v in zip("ABCDE", [5, 4, 3, 2, 1])] +
                [(t2, c, v) for c, v in zip("ABCDE", [3, 1, 5, 4, 2])])
    s = BufferScoreStrategy(scores=sc, top_n=2, keep_rank=2, universe="IDX", min_list_days=10)
    s.target_weights(t1, data.truncate(t1))
    w2 = s.target_weights(t2, data.truncate(t2))
    assert sorted(w2[w2 > 0].index) == ["C", "D"]
    data.is_st.loc[t2, "C"] = True
    s2 = BufferScoreStrategy(scores=sc, top_n=2, keep_rank=3, universe="IDX", min_list_days=10)
    s2.target_weights(t1, data.truncate(t1))
    w = s2.target_weights(t2, data.truncate(t2))
    assert sorted(w[w > 0].index) == ["A", "D"]      # C 不可选；可选排名 D A E B
