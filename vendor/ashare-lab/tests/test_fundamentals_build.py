"""财务版本表构建：用伪造的 Tushare 归档目录测试（见 docs/09-财务数据PIT约定.md）。"""
import json
from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ashare_lab.data.fundamentals import Fundamentals, build_fundamentals


def _write(root, name, rows):
    path = root / "parquet" / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return f"parquet/{name}.parquet"


def _row(code, end, rt, flag, ann, f_ann, fetched, **values):
    r = {"ts_code": code.split(".")[1] + code.split(".")[0], "source_ts_code": code,
         "end_date": end, "report_type": rt, "update_flag": flag, "ann_date": ann,
         "f_ann_date": f_ann, "comp_type": "1", "_fetched_at": fetched}
    r.update(values)
    return r


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "tushare"
    t1, t2 = "2026-09-18T22:00:00+00:00", "2026-09-19T02:00:00+00:00"
    inc_a = [
        _row("000001.SZ", "20200331", "1", "0", "20200428", "20200428", t1, n_income_attr_p=10.0, total_revenue=100.0),
        _row("000001.SZ", "20200331", "1", "0", "20200428", "20200428", t2, n_income_attr_p=10.5, total_revenue=100.0),  # 重抓，取 fetched 最新
        _row("000001.SZ", "20200331", "1", "1", "20200428", "20200428", t1, n_income_attr_p=10.7, total_revenue=100.0),  # 同日 flag=1 胜出
        _row("600000.SH", "20191231", "5", "0", "20200420", "20200420", t1, n_income_attr_p=50.0, total_revenue=500.0),
        _row("600000.SH", "20191231", "1", "1", "20200420", "20200815", t1, n_income_attr_p=45.0, total_revenue=500.0),
        _row("600000.SH", "20191231", "4", "0", "20210420", "20210420", t1, n_income_attr_p=46.0, total_revenue=500.0),
        _row("600000.SH", "20191231", "2", "0", "20200420", "20200420", t1, n_income_attr_p=9.0, total_revenue=90.0),   # 单季，丢弃
        _row("600000.SH", "20191231", "6", "0", "20200420", "20200420", t1, n_income_attr_p=7.0, total_revenue=70.0),   # 母公司，丢弃
    ]
    inc_b = [
        _row("300750.SZ", "20200630", "1", "0", "20200820", None, t1, n_income_attr_p=3.0, total_revenue=30.0),       # f_ann 缺失 -> ann
        _row("830799.BJ", "20200630", "1", "0", "20200820", "20200820", t1, n_income_attr_p=1.0, total_revenue=1.0),  # 北交所，丢弃
        _row("900901.SH", "20200630", "1", "0", "20200820", "20200820", t1, n_income_attr_p=1.0, total_revenue=1.0),  # B 股，丢弃
        _row("000002.SZ", "20051231", "1", "0", "20060420", "20060420", t1, n_income_attr_p=1.0, total_revenue=1.0),  # 早于 start，丢弃
        _row("000002.SZ", "20200630", "1", "0", None, None, t1, n_income_attr_p=1.0, total_revenue=1.0),              # 无日期，丢弃
    ]
    bal = [_row("000001.SZ", "20200331", "1", "0", "20200428", "20200428", t1, total_hldr_eqy_exc_min_int=200.0, total_assets=2000.0)]
    cf = [_row("000001.SZ", "20200331", "1", "0", "20200428", "20200428", t1, n_cashflow_act=5.0)]
    datasets = [
        {"api_name": "income_vip", "path": _write(src, "inc_a", inc_a), "bytes": 1, "sha256": "x", "quality_state": "ok"},
        {"api_name": "income_vip", "path": _write(src, "inc_b", inc_b), "bytes": 1, "sha256": "x", "quality_state": "ok"},
        {"api_name": "balancesheet_vip", "path": _write(src, "bal", bal), "bytes": 1, "sha256": "x", "quality_state": "ok"},
        {"api_name": "cashflow_vip", "path": _write(src, "cf", cf), "bytes": 1, "sha256": "x", "quality_state": "ok"},
        {"api_name": "daily", "path": "parquet/missing.parquet", "bytes": 1, "sha256": "x", "quality_state": "ok"},
    ]
    rid = "data-test"
    (src / "releases" / rid).mkdir(parents=True)
    (src / "releases" / rid / "manifest.json").write_text(json.dumps({"datasets": datasets}))
    (src / "CURRENT.json").write_text(json.dumps({"release_id": rid}))
    return src


def test_build_versions(source, tmp_path):
    out = tmp_path / "fin"
    build_fundamentals(out, source=source, start=date(2008, 1, 1))
    for name in ("fin_income", "fin_balance", "fin_cashflow"):
        assert (out / f"{name}.parquet").exists()
    meta = json.loads((out / "fin_meta.json").read_text())
    assert meta["release_id"] == "data-test"

    inc = pd.read_parquet(out / "fin_income.parquet")
    for col in ("code", "end_date", "report_type", "update_flag", "ann_date", "effective_date",
                "n_income_attr_p", "total_revenue"):
        assert col in inc.columns, col
    assert set(inc.code) == {"000001.SZ", "600000.SH", "300750.SZ"}
    assert set(inc.report_type) <= {1, 4, 5}
    assert not inc.duplicated(["code", "end_date", "report_type", "effective_date"]).any()

    a = inc[inc.code == "000001.SZ"]
    assert len(a) == 1 and a.n_income_attr_p.iloc[0] == 10.7 and a.update_flag.iloc[0] == 1
    b = inc[inc.code == "600000.SH"].sort_values("effective_date")
    assert list(b.report_type) == [5, 1, 4]
    assert list(pd.to_datetime(b.effective_date)) == [pd.Timestamp(x) for x in ("2020-04-20", "2020-08-15", "2021-04-20")]
    c = inc[inc.code == "300750.SZ"]
    assert pd.Timestamp(c.effective_date.iloc[0]) == pd.Timestamp("2020-08-20")


def test_build_then_query(source, tmp_path):
    out = tmp_path / "fin"
    build_fundamentals(out, source=source, start=date(2008, 1, 1))
    f = Fundamentals.load(out)
    s = f.asof("income", "2020-08-14")
    assert s.loc[("600000.SH", pd.Timestamp("2019-12-31")), "n_income_attr_p"] == 50.0
    s = f.asof("income", "2020-08-15")
    assert s.loc[("600000.SH", pd.Timestamp("2019-12-31")), "n_income_attr_p"] == 45.0
    lat = f.latest("balance", "2020-04-28")
    assert lat.loc["000001.SZ", "total_hldr_eqy_exc_min_int"] == 200.0
    assert f.latest("cashflow", "2020-04-28").loc["000001.SZ", "n_cashflow_act"] == 5.0
