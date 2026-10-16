"""公告事件库真实数据验收：需要先运行 `PYTHONPATH=src python3 -m ashare_lab.data.events --panel data/panel --out data/events`。"""
import json
from pathlib import Path

import pandas as pd
import pytest

from ashare_lab.data.events import load_events

OUT = Path(__file__).resolve().parents[1] / "data" / "events"
pytestmark = pytest.mark.skipif(not (OUT / "events.parquet").exists(), reason="events not built")


@pytest.fixture(scope="module")
def ev():
    return load_events(OUT)


def test_schema_and_uniqueness(ev):
    for c in ("code", "ann_date", "effective_date", "event_type", "subtype", "title", "url",
              "fc_type", "fc_p_change_min", "fc_p_change_max", "fc_end_date"):
        assert c in ev.columns, c
    assert not ev.url.duplicated().any()
    assert ev.code.str.match(r"^(60|68|000|001|002|003|300|301)\d+\.(SH|SZ)$").all()
    assert (ev.effective_date > ev.ann_date).all()
    assert set(ev.event_type) == {"earnings_forecast", "buyback", "insider_increase",
                                  "insider_decrease", "regulatory"}


def test_volumes(ev):
    n = ev.groupby("event_type").size()
    assert n["earnings_forecast"] > 40000
    assert n["buyback"] > 30000
    assert n["insider_decrease"] > 40000
    assert n["insider_increase"] > 10000
    assert n["regulatory"] > 30000


def test_recall_meta():
    meta = json.loads((OUT / "events_meta.json").read_text())
    rec = meta["recall"]
    # 口径见 docs/11「召回统计」（2026-10-14 修订）
    assert rec["forecast_vip"] > 0.97, rec
    assert rec["repurchase"] > 0.97, rec
    for k in ("forecast_vip_raw", "repurchase_raw", "stk_holdertrade_in", "stk_holdertrade_de"):
        assert 0 < rec[k] <= 1, k
    assert 0.5 < meta["coverage"]["forecast_vip"] <= 1
    assert 0 < meta["fc_fill_rate"] <= 1


def test_known_events(ev):
    wbd = ev[(ev.code == "300055.SZ") & (ev.event_type == "regulatory")]
    assert len(wbd) > 0
    load = load_events(OUT, start="2020-01-01", end="2020-12-31", event_types=["buyback"])
    assert set(load.event_type) == {"buyback"}
    assert load.effective_date.min() >= pd.Timestamp("2020-01-01")
    assert load.effective_date.max() <= pd.Timestamp("2020-12-31")
