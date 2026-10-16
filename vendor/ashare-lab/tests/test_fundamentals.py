"""财务数据 point-in-time 查询：合成数据单元测试（见 docs/09-财务数据PIT约定.md）。"""
import numpy as np
import pandas as pd
import pytest

from ashare_lab.data.fundamentals import Fundamentals

D = pd.Timestamp


def vt(rows, fields):
    """rows: (code, end_date, report_type, update_flag, ann_date, effective_date, *values)"""
    cols = ["code", "end_date", "report_type", "update_flag", "ann_date", "effective_date", *fields]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("end_date", "ann_date", "effective_date"):
        df[c] = pd.to_datetime(df[c])
    df["report_type"] = df["report_type"].astype(int)
    df["update_flag"] = df["update_flag"].astype(int)
    for f in fields:
        df[f] = df[f].astype(float)
    return df


@pytest.fixture
def corrected():
    # A: 2020Q1 原值 100（4/28 公告），9/1 更正为 90，次年年报把上年同期调整为 95
    inc = vt([
        ("A.SZ", "2020-03-31", 5, 0, "2020-04-28", "2020-04-28", 100.0),
        ("A.SZ", "2020-03-31", 1, 1, "2020-04-28", "2020-09-01", 90.0),
        ("A.SZ", "2020-03-31", 4, 0, "2021-04-28", "2021-04-28", 95.0),
    ], ["n_income_attr_p"])
    return Fundamentals({"income": inc})


@pytest.mark.parametrize("date,expected", [
    ("2020-04-28", 100.0), ("2020-08-31", 100.0), ("2020-09-01", 90.0),
    ("2021-04-27", 90.0), ("2021-04-28", 95.0), ("2030-01-01", 95.0),
])
def test_version_timeline(corrected, date, expected):
    snap = corrected.asof("income", date)
    assert snap.loc[("A.SZ", D("2020-03-31")), "n_income_attr_p"] == expected


def test_nothing_before_announcement(corrected):
    snap = corrected.asof("income", "2020-04-27")
    assert ("A.SZ", D("2020-03-31")) not in snap.index
    assert len(snap) == 0


def test_asof_columns_and_index(corrected):
    snap = corrected.asof("income", "2020-09-01")
    assert list(snap.index.names) == ["code", "end_date"]
    assert snap.loc[("A.SZ", D("2020-03-31")), "effective_date"] == D("2020-09-01")
    assert snap.loc[("A.SZ", D("2020-03-31")), "report_type"] == 1


def test_naive_uses_final_version_from_end_date(corrected):
    assert len(corrected.asof("income", "2020-03-30", naive=True)) == 0
    snap = corrected.asof("income", "2020-03-31", naive=True)
    assert snap.loc[("A.SZ", D("2020-03-31")), "n_income_attr_p"] == 95.0


def test_same_day_tie_prefers_original_then_consolidated():
    inc = vt([
        ("A.SZ", "2020-12-31", 1, 1, "2021-03-01", "2021-03-01", 11.0),
        ("A.SZ", "2020-12-31", 5, 0, "2021-03-01", "2021-03-01", 10.0),
        ("B.SZ", "2019-12-31", 4, 0, "2021-03-01", "2021-03-01", 7.0),
        ("B.SZ", "2019-12-31", 1, 1, "2020-03-01", "2021-03-01", 8.0),
        ("C.SZ", "2020-12-31", 1, 0, "2021-03-01", "2021-03-01", 3.0),
        ("C.SZ", "2020-12-31", 1, 1, "2021-03-01", "2021-03-01", 4.0),
    ], ["x"])
    snap = Fundamentals({"income": inc}).asof("income", "2021-03-01")
    assert snap.loc[("A.SZ", D("2020-12-31")), "x"] == 10.0   # 5 优先于 1
    assert snap.loc[("B.SZ", D("2019-12-31")), "x"] == 8.0    # 1 优先于 4
    assert snap.loc[("C.SZ", D("2020-12-31")), "x"] == 4.0    # 同类型 update_flag=1 优先


def test_latest_picks_newest_announced_period():
    inc = vt([
        ("A.SZ", "2019-12-31", 1, 0, "2020-04-28", "2020-04-28", 40.0),
        ("A.SZ", "2020-03-31", 1, 0, "2020-04-28", "2020-04-28", 12.0),
        ("A.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", 25.0),
        ("B.SZ", "2019-09-30", 1, 0, "2019-10-30", "2019-10-30", 7.0),
    ], ["n_income_attr_p"])
    f = Fundamentals({"income": inc})
    lat = f.latest("income", "2020-08-19")
    assert lat.index.name == "code"
    assert lat.loc["A.SZ", "end_date"] == D("2020-03-31")
    assert lat.loc["A.SZ", "n_income_attr_p"] == 12.0
    assert lat.loc["B.SZ", "end_date"] == D("2019-09-30")
    lat = f.latest("income", "2020-08-20")
    assert lat.loc["A.SZ", "end_date"] == D("2020-06-30")
    assert "A.SZ" not in f.latest("income", "2020-04-27").index


@pytest.fixture
def ttm_data():
    # 累计值口径。2020H1 TTM = H1_2020 + FY2019 - H1_2019
    inc = vt([
        ("A.SZ", "2019-06-30", 1, 0, "2019-08-20", "2019-08-20", 30.0),
        ("A.SZ", "2019-12-31", 1, 0, "2020-04-20", "2020-04-20", 70.0),
        ("A.SZ", "2019-12-31", 4, 0, "2021-04-20", "2021-04-20", 60.0),  # 次年调整
        ("A.SZ", "2020-03-31", 1, 0, "2020-04-28", "2020-04-28", 15.0),
        ("A.SZ", "2019-03-31", 1, 0, "2019-04-28", "2019-04-28", 14.0),
        ("A.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", 34.0),
        ("A.SZ", "2020-12-31", 1, 0, "2021-04-20", "2021-04-20", 80.0),
        ("B.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", 5.0),   # 缺上年数据
    ], ["n_income_attr_p"])
    bal = vt([
        ("A.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", 370.0),
        ("A.SZ", "2020-12-31", 1, 0, "2021-04-20", "2021-04-20", 400.0),
        ("A.SZ", "2020-03-31", 1, 0, "2020-04-28", "2020-04-28", 300.0),
        ("B.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", -10.0),
    ], ["total_hldr_eqy_exc_min_int"])
    return Fundamentals({"income": inc, "balance": bal})


def test_ttm_values(ttm_data):
    s = ttm_data.ttm("n_income_attr_p", "2020-08-20")
    assert s["A.SZ"] == pytest.approx(34 + 70 - 30)
    assert np.isnan(s["B.SZ"])
    assert ttm_data.ttm("n_income_attr_p", "2020-05-01")["A.SZ"] == pytest.approx(15 + 70 - 14)
    assert ttm_data.ttm("n_income_attr_p", "2021-04-20")["A.SZ"] == pytest.approx(80.0)


def test_ttm_uses_restated_component_only_after_restatement():
    inc = vt([
        ("A.SZ", "2020-06-30", 1, 0, "2020-08-20", "2020-08-20", 30.0),
        ("A.SZ", "2020-12-31", 1, 0, "2021-04-20", "2021-04-20", 70.0),
        ("A.SZ", "2020-06-30", 4, 0, "2021-08-20", "2021-08-20", 20.0),
        ("A.SZ", "2021-03-31", 1, 0, "2021-04-28", "2021-04-28", 10.0),
        ("A.SZ", "2020-03-31", 1, 0, "2020-04-28", "2020-04-28", 8.0),
        ("A.SZ", "2020-03-31", 4, 0, "2021-04-28", "2021-04-28", 9.0),
        ("A.SZ", "2021-06-30", 1, 0, "2021-08-20", "2021-08-20", 33.0),
    ], ["n_income_attr_p"])
    f = Fundamentals({"income": inc})
    assert f.ttm("n_income_attr_p", "2021-05-01")["A.SZ"] == pytest.approx(10 + 70 - 9)
    assert f.ttm("n_income_attr_p", "2021-08-20")["A.SZ"] == pytest.approx(33 + 70 - 20)


def test_roe_ttm(ttm_data):
    r = ttm_data.roe_ttm("2020-08-20")
    assert r["A.SZ"] == pytest.approx((34 + 70 - 30) / 370.0)
    assert np.isnan(r.get("B.SZ", np.nan))  # 净资产为负 -> NaN
    r = ttm_data.roe_ttm("2021-04-20")
    assert r["A.SZ"] == pytest.approx(80.0 / 400.0)


def test_roe_nan_when_balance_period_differs():
    inc = vt([("A.SZ", "2020-12-31", 1, 0, "2021-04-20", "2021-04-20", 80.0)], ["n_income_attr_p"])
    bal = vt([("A.SZ", "2020-09-30", 1, 0, "2020-10-30", "2020-10-30", 400.0)], ["total_hldr_eqy_exc_min_int"])
    r = Fundamentals({"income": inc, "balance": bal}).roe_ttm("2021-04-20")
    assert np.isnan(r.get("A.SZ", np.nan))


def test_roe_naive_sees_period_at_end_date(ttm_data):
    r = ttm_data.roe_ttm("2020-06-30", naive=True)
    # naive：期末当天就知道最终版数据（FY2019 用调整后的 60）
    assert r["A.SZ"] == pytest.approx((34 + 60 - 30) / 370.0)


def test_panel_shape(ttm_data):
    dates = pd.DatetimeIndex(["2020-05-01", "2020-08-20", "2021-04-20"])
    p = ttm_data.panel("roe_ttm", dates, codes=["A.SZ", "B.SZ", "Z.SZ"])
    assert list(p.index) == list(dates) and list(p.columns) == ["A.SZ", "B.SZ", "Z.SZ"]
    assert p.loc["2020-08-20", "A.SZ"] == pytest.approx((34 + 70 - 30) / 370.0)
    assert p["Z.SZ"].isna().all()
    q = ttm_data.panel("roe_ttm", dates, codes=["A.SZ"], naive=True)
    assert q.loc["2020-08-20", "A.SZ"] == pytest.approx((34 + 60 - 30) / 370.0)


def _random_table(seed, n_codes=30):
    rng = np.random.default_rng(seed)
    rows = []
    ends = pd.date_range("2015-03-31", "2020-12-31", freq="QE")
    for i in range(n_codes):
        code = f"{i:06d}.SZ"
        for e in ends:
            if rng.random() < 0.1:
                continue
            ann = e + pd.Timedelta(days=int(rng.integers(20, 120)))
            rt = 1
            if rng.random() < 0.15:  # 更正
                rows.append((code, e, 5, 0, ann, ann, rng.normal()))
                rows.append((code, e, 1, 1, ann, ann + pd.Timedelta(days=int(rng.integers(0, 300))), rng.normal()))
            else:
                rows.append((code, e, rt, int(rng.integers(0, 2)), ann, ann, rng.normal()))
            if rng.random() < 0.3:
                d4 = e + pd.Timedelta(days=365 + int(rng.integers(20, 120)))
                rows.append((code, e, 4, 0, d4, d4, rng.normal()))
    return vt(rows, ["n_income_attr_p"])


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_lookahead_invariant(seed):
    """任意日 d：用全量表查询 == 用只含 effective_date<=d 的表查询；且所有生效日 <= d。"""
    tab = _random_table(seed)
    full = Fundamentals({"income": tab})
    rng = np.random.default_rng(seed + 100)
    for d in pd.to_datetime(rng.integers(pd.Timestamp("2015-01-01").value // 10**9,
                                         pd.Timestamp("2022-06-30").value // 10**9, 12), unit="s").normalize():
        cut = Fundamentals({"income": tab[tab.effective_date <= d].copy()})
        a = full.asof("income", d)
        b = cut.asof("income", d)
        assert (a["effective_date"] <= d).all()
        pd.testing.assert_frame_equal(a.sort_index(), b.sort_index(), check_dtype=False)
        ta, tb = full.ttm("n_income_attr_p", d), cut.ttm("n_income_attr_p", d)
        pd.testing.assert_series_equal(ta.sort_index(), tb.sort_index(), check_dtype=False, check_names=False)
