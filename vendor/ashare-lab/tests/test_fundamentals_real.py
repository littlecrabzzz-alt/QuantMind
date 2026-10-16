"""财务 PIT 真实数据验收：需要先运行 `PYTHONPATH=src python3 -m ashare_lab.data.fundamentals --out data/fundamentals`。

已知值来自 Tushare 归档（income_vip），更正类案例的日期另行与公告标题核对。
"""
from pathlib import Path

import pandas as pd
import pytest

from ashare_lab.data.fundamentals import Fundamentals

FIN = Path(__file__).resolve().parents[1] / "data" / "fundamentals"
pytestmark = pytest.mark.skipif(not (FIN / "fin_income.parquet").exists(), reason="fundamentals not built")
D = pd.Timestamp


@pytest.fixture(scope="module")
def fund():
    return Fundamentals.load(FIN)


def _v(fund, code, end, date, field="n_income_attr_p", statement="income"):
    return fund.asof(statement, date).loc[(code, D(end)), field]


def test_correction_300041(fund):
    # 回天新材 2010Q1：原值 2010-04-28，2011-04-21 更正
    assert _v(fund, "300041.SZ", "2010-03-31", "2010-06-01") == pytest.approx(1.863254e7, rel=1e-5)
    assert _v(fund, "300041.SZ", "2010-03-31", "2011-05-01") == pytest.approx(1.865876e7, rel=1e-5)


def test_correction_300055(fund):
    # 万邦达 2018 年报：原值 2019-04-26，2020-04-29 随 2019 年报调整
    assert _v(fund, "300055.SZ", "2018-12-31", "2019-06-01") == pytest.approx(-7.934958e7, rel=1e-5)
    assert _v(fund, "300055.SZ", "2018-12-31", "2020-05-06") == pytest.approx(-9.035251e7, rel=1e-5)
    assert _v(fund, "300055.SZ", "2019-09-30", "2020-01-02") == pytest.approx(1.675205e8, rel=1e-5)


def test_pingan_bank_2018(fund):
    assert fund.latest("income", "2019-03-06").loc["000001.SZ", "end_date"] == D("2018-09-30")
    lat = fund.latest("income", "2019-03-07")
    assert lat.loc["000001.SZ", "end_date"] == D("2018-12-31")
    assert lat.loc["000001.SZ", "n_income_attr_p"] == pytest.approx(2.4818e10, rel=1e-4)


def test_coverage(fund):
    lat = fund.latest("income", "2024-06-28")
    assert len(lat) > 4800
    # 只看当日在市且 2024-03-31 前上市的股票（已退市股票的最新报告期自然更早）
    s = pd.read_parquet(FIN.parent / "panel" / "stocks.parquet").set_index("code")
    alive = s[(pd.to_datetime(s.list_date) <= D("2024-03-31")) &
              (s.delist_date.isna() | (pd.to_datetime(s.delist_date) > D("2024-06-28")))].index
    lat = lat.reindex(alive).dropna(subset=["end_date"])
    assert len(lat) > 4800
    assert (lat.end_date >= D("2024-03-31")).mean() > 0.99
    roe = fund.roe_ttm("2024-06-28")
    assert roe.notna().sum() > 4500
    assert 0.03 < roe.median() < 0.12
