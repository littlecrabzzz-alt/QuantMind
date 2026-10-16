"""真实数据面板验收：需要先运行 `PYTHONPATH=src python3 -m ashare_lab.data.build --out data/panel`。"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from ashare_lab.data.market import load_market_data

PANEL = Path(__file__).resolve().parents[1] / "data" / "panel"
QUANTDB_IDX = Path.home() / "Documents/ChatGPT/投资/QuantMind/data/quantdb/1_kline_data/index_daily/000906.SH.parquet"

pytestmark = pytest.mark.skipif(not (PANEL / "daily.parquet").exists(), reason="panel not built")


@pytest.fixture(scope="module")
def md():
    return load_market_data(PANEL, "2012-01-01", "2026-09-30", universe="000906.SH")


@pytest.fixture(scope="module")
def daily():
    df = duckdb.sql(f"select * from '{PANEL}/daily.parquet'").df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_files_exist():
    for f in ["daily", "stocks", "index_members", "index_daily", "industry", "calendar"]:
        assert (PANEL / f"{f}.parquet").exists(), f
    assert (PANEL / "build_meta.json").exists()


def test_unique_keys(daily):
    assert not daily.duplicated(["date", "code"]).any()
    assert daily.code.str.match(r"^(60|68|000|001|002|003|300|301)\d+\.(SH|SZ)$").all()


def test_known_values(md):
    t = pd.Timestamp("2024-01-05")
    assert md.close.loc[t, "000001.SZ"] == pytest.approx(9.27)
    assert md.amount.loc[t, "000001.SZ"] == pytest.approx(1852659.692 * 1000, rel=1e-6)
    assert md.volume.loc[t, "000001.SZ"] == pytest.approx(199162208.0, rel=1e-3)


def test_delisted_stock_present(md):
    assert "600005.SH" in md.close.columns  # 武钢股份，2017-02-14 退市
    assert md.delist_date["600005.SH"] == pd.Timestamp("2017-02-14")
    assert md.close.loc["2016-01-04":"2016-06-30", "600005.SH"].notna().sum() > 50
    assert md.members["000906.SH"].loc["2016-03-01", "600005.SH"]
    assert md.close.loc["2017-03-01":, "600005.SH"].isna().all()


def test_csi800_membership_counts(md):
    cnt = md.members["000906.SH"].sum(axis=1)
    assert cnt.min() >= 790 and cnt.max() <= 810, cnt.describe()


def test_suspension_on_2015_07_08(md, daily):
    d = daily[daily.date == pd.Timestamp("2015-07-08")]
    assert d.suspended.sum() >= 1300
    assert md.suspended.loc["2015-07-08"].sum() >= 200


def test_limit_ratios_by_board(daily):
    def ratio(code, date):
        r = daily[(daily.code == code) & (daily.date == pd.Timestamp(date))].iloc[0]
        return r.up_limit / r.pre_close - 1

    assert ratio("300750.SZ", "2021-03-01") == pytest.approx(0.20, abs=0.006)
    assert ratio("300015.SZ", "2019-06-03") == pytest.approx(0.10, abs=0.006)
    assert ratio("600000.SH", "2020-06-01") == pytest.approx(0.10, abs=0.006)


def test_st_share_reasonable(daily):
    d = daily[(daily.date == pd.Timestamp("2020-06-01")) & daily.close.notna()]
    assert 80 <= d.is_st.sum() <= 300
    assert not d[d.code == "600000.SH"].is_st.iloc[0]


def test_adjusted_returns_match_pct_chg(daily):
    d = daily[(daily.date >= pd.Timestamp("2019-01-01")) & (daily.date <= pd.Timestamp("2019-12-31"))]
    d = d.sort_values(["code", "date"])
    d = d[d.close.notna()]
    adj_close = d.close * d.adj
    r = adj_close.groupby(d.code).pct_change()
    ok = (r - d.pct_chg / 100).abs() < 0.002
    mask = r.notna() & d.pct_chg.notna() & (d.groupby("code").date.diff() <= pd.Timedelta(days=5))
    assert ok[mask].mean() > 0.99


def test_index_close_matches_quantdb(md):
    ic = md.index_close["000906.SH"]
    assert ic.loc["2012-01-04":].notna().all()
    q = duckdb.sql(f"select time, close from '{QUANTDB_IDX}'").df().set_index("time")["close"]
    q.index = pd.to_datetime(q.index)
    common = ic.index.intersection(q.index)
    assert len(common) > 2000
    assert ((ic.loc[common] / q.loc[common] - 1).abs() < 0.005).mean() > 0.99


def test_shapes_and_alignment(md):
    for name in ["open", "close", "up_limit", "down_limit", "adj", "volume", "amount", "suspended", "is_st"]:
        f = getattr(md, name)
        assert f.index.equals(md.calendar), name
        assert list(f.columns) == list(md.close.columns), name
    assert md.members["000906.SH"].index.equals(md.calendar)
    assert md.calendar[0] >= pd.Timestamp("2012-01-01") and md.calendar[-1] <= pd.Timestamp("2026-09-30")
    assert 1500 < md.close.shape[1] < 3500
