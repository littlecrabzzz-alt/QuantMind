"""全收益基准真实数据验收：需要先运行 `PYTHONPATH=src python3 -m ashare_lab.benchmark --panel data/panel --out data/benchmarks`。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ashare_lab.benchmark import load_benchmarks

OUT = Path(__file__).resolve().parents[1] / "data" / "benchmarks"
pytestmark = pytest.mark.skipif(not (OUT / "csi800_tr.parquet").exists(), reason="benchmark not built")


@pytest.fixture(scope="module")
def tr():
    df = pd.read_parquet(OUT / "csi800_tr.parquet")
    return df.assign(date=pd.to_datetime(df.date)).set_index("date")


def test_columns_and_range(tr):
    for c in ("price_close", "recon_price_ret", "div_contrib", "tr_close", "official_tr_close"):
        assert c in tr.columns
    assert tr.index.min() <= pd.Timestamp("2010-01-05")
    assert tr.index.max() >= pd.Timestamp("2026-10-09")
    assert tr.tr_close.notna().all()


def test_reconstructed_price_tracks_official(tr):
    t = tr.loc["2011-01-01":]
    off = t.price_close.pct_change()
    ok = off.notna() & t.recon_price_ret.notna()
    assert np.corrcoef(off[ok], t.recon_price_ret[ok])[0, 1] > 0.995
    yo = (1 + off[ok]).groupby(off[ok].index.year).prod() - 1
    yr = (1 + t.recon_price_ret[ok]).groupby(off[ok].index.year).prod() - 1
    diff = (yr - yo).abs()
    assert diff.mean() < 0.005, diff
    assert diff.max() < 0.015, diff


def test_annual_dividend_yield(tr):
    d = tr.loc["2011-01-01":"2025-12-31", "div_contrib"].fillna(0)
    y = d.groupby(d.index.year).sum()
    assert (y > 0.01).all() and (y < 0.035).all(), y
    assert 0.015 < y.mean() < 0.028, y


def test_overlap_with_official_h00906(tr):
    o = tr.loc["2026-09-02":"2026-10-09"].dropna(subset=["official_tr_close"])
    assert len(o) >= 20
    off_div = o.official_tr_close.pct_change() - o.price_close.pct_change()
    ours = o.div_contrib
    ok = off_div.notna()
    assert abs(off_div[ok].sum() - ours[ok].sum()) < 0.0003
    assert np.corrcoef(off_div[ok], ours[ok])[0, 1] > 0.8
    rel = o.tr_close / o.tr_close.iloc[0] / (o.official_tr_close / o.official_tr_close.iloc[0]) - 1
    assert rel.abs().max() < 0.0005


def test_load_benchmarks():
    b = load_benchmarks(OUT)
    assert list(b.columns) == ["000906.SH", "000906.SH_TR"]
    assert isinstance(b.index, pd.DatetimeIndex)
    ann = (b.iloc[-1] / b.loc["2011-01-04":].iloc[0]) ** (252 / (len(b.loc["2011-01-04":]) - 1)) - 1
    assert 0.012 < ann["000906.SH_TR"] - ann["000906.SH"] < 0.03
