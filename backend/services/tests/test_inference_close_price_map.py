"""QuantDB close price map for inference persist (no remote Redis)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.services.engine.inference import script_runner as sr


def test_load_close_price_map_from_quantdb_partition(tmp_path: Path, monkeypatch):
    day = "2026-09-10"
    part = tmp_path / "1_kline_data" / "daily_unadjusted" / "dt=20260910"
    part.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["600036.SH", "000001.SZ", "bad"],
            "close": [42.5, 11.0, float("nan")],
        }
    ).to_parquet(part / "data.parquet", index=False)

    monkeypatch.setattr(sr, "_resolve_quantdb_data_dir", lambda: str(tmp_path))
    prices = sr._load_close_price_map(day)
    assert prices["600036"] == 42.5
    assert prices["000001"] == 11.0
    assert "bad" not in prices


def test_load_close_price_map_missing_dir(monkeypatch):
    monkeypatch.setattr(sr, "_resolve_quantdb_data_dir", lambda: "/no/such/quantdb")
    assert sr._load_close_price_map("2026-09-10") == {}


def test_adjusted_prices_are_not_trade_reference_prices(tmp_path, monkeypatch):
    part = tmp_path / "1_kline_data/daily_forward/dt=20260910"
    part.mkdir(parents=True)
    pd.DataFrame({"symbol": ["600036.SH"], "close": [12.3]}).to_parquet(part / "data.parquet", index=False)
    monkeypatch.setattr(sr, "_resolve_quantdb_data_dir", lambda: str(tmp_path))
    assert sr._load_close_price_map("2026-09-10") == {}
