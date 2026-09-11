"""Current page generation, failed publication and historical input regressions."""

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.scripts.market_snapshot import compute
from backend.services.api.market_analysis import quantdb_snapshot as reader


def generation(root, day):
    payload = {
        "trade_date": day,
        "breadth": {"trade_date": day},
        "indices": [{"close": 12}],
        "heatmap": {"shenwan": [{"name": "test"}]},
    }
    for name in ("latest.json", day + ".json"):
        (root / name).write_text(json.dumps(payload))
    for name in ("latest.db", day + ".db"):
        with sqlite3.connect(root / name) as db:
            db.execute("CREATE TABLE meta(key TEXT,value TEXT)")
            db.execute("INSERT INTO meta VALUES(?,?)", ("trade_date", day))


def test_stale_latest_is_rejected_but_historical_date_is_kept(tmp_path):
    raw = tmp_path / "raw"
    (raw / "1_kline_data/daily_unadjusted/dt=20260911").mkdir(parents=True)
    out = tmp_path / "view"
    out.mkdir()
    generation(out, "2026-09-04")
    with patch.dict(
        os.environ, QM_MARKET_SNAPSHOT_DIR=str(out), QM_QUANTDB_DATA_DIR=str(raw)
    ):
        assert reader.full() is None
        assert reader._open_tags_db(None) is None
        assert not reader.has_snapshot()
        assert reader.full("2026-09-04")["trade_date"] == "2026-09-04"


def test_refresh_failure_preserves_old_view_then_publishes_and_skips_same_day(tmp_path):
    raw = tmp_path / "raw"
    (raw / "1_kline_data/daily_unadjusted/dt=20260911").mkdir(parents=True)
    out = tmp_path / "view"
    out.mkdir()
    generation(out, "2026-09-04")
    old = (out / "latest.json").read_bytes()
    import pytest

    with patch(
        "subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="failure")
    ):
        with pytest.raises(RuntimeError):
            compute.refresh_snapshot(raw, out)
    assert (out / "latest.json").read_bytes() == old

    def run(args, **kwargs):
        generation(Path(args[args.index("--out") + 1]), "2026-09-11")
        return SimpleNamespace(returncode=0, stderr="")

    with patch("subprocess.run", side_effect=run) as call:
        assert not compute.refresh_snapshot(raw, out)["unchanged"]
        assert compute.refresh_snapshot(raw, out)["unchanged"]
        assert call.call_count == 1
        (raw / "1_kline_data/daily_unadjusted/dt=20260911/data.parquet").write_bytes(b"correction")
        assert not compute.refresh_snapshot(raw, out)["unchanged"]
        assert call.call_count == 2
    assert (out / "2026-09-04.json").read_bytes() == old
    with patch.dict(
        os.environ, QM_MARKET_SNAPSHOT_DIR=str(out), QM_QUANTDB_DATA_DIR=str(raw)
    ):
        assert reader.breadth()["trade_date"] == "2026-09-11"
        with reader._open_tags_db(None) as db:
            assert db.execute("SELECT value FROM meta").fetchone()[0] == "2026-09-11"


def test_repeated_flow_values_do_not_crash_namedtuple_date(tmp_path):
    import pandas as pd

    symbols = [f"{i:06}.SZ" for i in range(1, 27)]
    hist = pd.DataFrame(
        {
            "symbol": symbols,
            "dt": ["20260911"] * 26,
            "flow_net_amount": [10.0] * 26,
            "flow_buy_amount": [20.0] * 26,
            "flow_sell_amount": [10.0] * 26,
            "flow_super_net": [5.0] * 26,
            "flow_large_net": [5.0] * 26,
            "flow_medium_net": [0.0] * 26,
            "flow_small_net": [0.0] * 26,
        }
    )
    prices = pd.DataFrame(
        {"symbol": symbols, "close": [12.0] * 26, "pct_change": [1.0] * 26}
    )
    with (
        patch.object(compute, "_latest_l2_date", return_value="20260911"),
        patch.object(compute, "_trading_days", return_value=["20260911"]),
        patch.object(compute, "_load_l2_flow", return_value=hist),
        patch.object(compute, "_load_prices", return_value=prices),
        patch.object(compute, "_instrument_names", return_value={}),
    ):
        items = compute.get_stock_money_flow(None, tmp_path)
    assert items == []
