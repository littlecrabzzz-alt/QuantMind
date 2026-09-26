"""Offline native ZIP/CHECKSUM to immutable derivative release acceptance."""

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import requests

from backend.scripts import equity_perpetual_archive as intake
from backend.tests.test_binance_data_fetch import bar, response


@pytest.fixture
def archives(monkeypatch):
    state = {
        "missing": set(),
        "denied": {},
        "checksum_bad": False,
        "close": "105",
        "calls": [],
    }

    def get(url, **kwargs):
        state["calls"].append(url)
        match = re.fullmatch(
            r"https://data\.binance\.vision/data/futures/um/(monthly|daily)/klines/"
            r"(CXMTUSDT|UNITREEUSDT)/1d/([^/]+\.zip)(\.CHECKSUM)?",
            url,
        )
        assert match, f"Only the explicit public archive host/path is permitted: {url}"
        period, symbol, filename, checksum = match.groups()
        status = state["denied"].get(
            filename, 404 if filename in state["missing"] else 200
        )
        if status != 200:
            result = response(b"not available", status=status)
        else:
            day = pd.Timestamp(
                filename.removeprefix(symbol + "-1d-").removesuffix(".zip"), tz="UTC"
            )
            end = day + (
                pd.offsets.MonthBegin(1)
                if period == "monthly"
                else pd.Timedelta(days=1)
            )
            listing = intake.source._utc(intake.REGISTRY[symbol]["listing_time"])
            days = pd.date_range(max(day, listing.normalize()), end, inclusive="left")
            csv_text = io.StringIO()
            writer = csv.writer(csv_text)
            writer.writerow(
                [
                    "count" if field == "trades" else field
                    for field in intake.source._RAW_COLUMNS
                ]
            )
            for value in days:
                writer.writerow(bar(str(value.date()), close=state["close"]))
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as zipped:
                # Fixed ZIP timestamps make identical offline replays byte-identical.
                entry = zipfile.ZipInfo(
                    filename.removesuffix(".zip") + ".csv",
                    date_time=(2026, 9, 1, 0, 0, 0),
                )
                zipped.writestr(entry, csv_text.getvalue())
            body = data.getvalue()
            if checksum:
                digest = (
                    "0" * 64
                    if state["checksum_bad"]
                    else hashlib.sha256(body).hexdigest()
                )
                body = f"{digest}  {filename}\n".encode()
            result = response(body)
        result.url = url
        return result

    monkeypatch.setattr(requests, "get", get)
    return state


def run(root, **kwargs):
    return intake.run(
        data_dir=root,
        start_date="2010-01-01",
        end_date="2026-09-03",
        now="2026-09-26T12:00:00Z",
        max_retries=0,
        **kwargs,
    )


def stored(result):
    release = Path(result["data_dir"])
    manifest = json.loads((release / "manifest.json").read_text())
    parts = sorted(release.glob("1_kline_data/daily_forward/dt=*/data.parquet"))
    return (
        release,
        manifest,
        pd.concat([pd.read_parquet(path) for path in parts], ignore_index=True),
    )


def test_complete_archive_native_semantics_replay_and_revision(tmp_path, archives):
    first = run(tmp_path)
    release, manifest, data = stored(first)
    original = (release / "manifest.json").read_bytes()
    assert first["status"] == "completed"
    assert len(data) == 31 and manifest["quality"]["history_complete"] is True
    assert (
        manifest["research_ready"] is False
        and manifest["point_in_time_verified"] is False
    )
    assert manifest["missing_datasets"] == [
        "funding_rate",
        "mark_price",
        "index_price",
        "corporate_actions",
    ]
    assert manifest["price_adjustment"] == "none"
    assert set(data.product_type) == {"equity_perpetual"}
    assert set(data.underlying_symbol) == {"688825.SH", "688836.SH"}
    assert data.quote_asset.eq("USDT").all() and data.settlement_asset.eq("USDT").all()
    assert data.amount.eq(1025).all() and data.amount.eq(data.quote_volume).all()
    assert str(data.open_time.dt.tz) == "UTC" and str(data.collected_at.dt.tz) == "UTC"
    assert (data.available_at == data.open_time + pd.Timedelta(days=1)).all()
    partial = data[data.partial_listing_bar]
    assert len(partial) == 2
    assert partial[partial.symbol == "CXMTUSDT"].iloc[
        0
    ].trading_start_lower_bound == pd.Timestamp("2026-08-18T05:00:00Z")
    assert partial[partial.symbol == "UNITREEUSDT"].iloc[
        0
    ].trading_start_lower_bound == pd.Timestamp("2026-08-19T02:45:00Z")
    assert manifest["raw_files"] and all(
        (tmp_path / path).is_file() for path in manifest["raw_files"]
    )
    assert any("/monthly/" in url for url in archives["calls"])
    assert any("/daily/" in url for url in archives["calls"])
    replay = run(tmp_path)
    assert replay["unchanged"] is True and replay["release_id"] == first["release_id"]
    archives["close"] = "106"
    revised = run(tmp_path)
    assert revised["release_id"] != first["release_id"]
    assert (release / "manifest.json").read_bytes() == original


def test_missing_daily_archive_is_partial_and_preserves_current(tmp_path, archives):
    first = intake.run(
        data_dir=tmp_path,
        symbols="UNITREEUSDT",
        end_date="2026-09-02",
        now="2026-09-26",
        max_retries=0,
    )
    pointer = (tmp_path / "CURRENT.json").read_bytes()
    archives["missing"].add("UNITREEUSDT-1d-2026-09-02.zip")
    partial = run(tmp_path, symbols="UNITREEUSDT")
    assert partial["status"] == "partial" and partial["research_ready"] is False
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    release, manifest, _ = stored(partial)
    assert manifest["status"] == "partial"
    assert manifest["quality"]["history_complete"] is False
    assert manifest["quality"]["symbols"]["UNITREEUSDT"]["missing_days"] == [
        "2026-09-02"
    ]
    missing = json.loads((release / "missing.json").read_text())["files"]
    assert missing[0]["reason"] == "expected_archive_not_published"
    assert missing[0]["http_status"] == 404
    replay = run(tmp_path, symbols="UNITREEUSDT")
    assert replay["release_id"] == partial["release_id"] and replay["unchanged"]
    assert len(list((tmp_path / "releases").iterdir())) == 2
    assert first["release_id"] != partial["release_id"]


@pytest.mark.parametrize("status", [401, 403, 451])
def test_restrictions_stop_entire_run_without_fallback(tmp_path, archives, status):
    run(tmp_path)
    pointer = (tmp_path / "CURRENT.json").read_bytes()
    archives["calls"].clear()
    archives["denied"]["CXMTUSDT-1d-2026-08.zip"] = status
    with pytest.raises(requests.HTTPError):
        run(tmp_path)
    assert len(archives["calls"]) == 1
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    assert (
        json.loads((tmp_path / "last_attempt.json").read_text())["status"] == "failed"
    )


def test_bad_checksum_and_unclosed_window_fail_without_publication(tmp_path, archives):
    archives["checksum_bad"] = True
    with pytest.raises(ValueError, match="checksum"):
        run(tmp_path)
    assert not (tmp_path / "CURRENT.json").exists()
    with pytest.raises(ValueError, match="UTC midnight"):
        intake.run(data_dir=tmp_path, end_date="2026-09-27", now="2026-09-26")
    with pytest.raises(ValueError, match="reviewed listing"):
        run(tmp_path, symbols="BTCUSDT")


def test_first_missing_month_is_saved_without_current_or_false_history(
    tmp_path, archives
):
    archives["missing"].update(
        {"CXMTUSDT-1d-2026-08.zip", "UNITREEUSDT-1d-2026-08.zip"}
    )
    result = run(tmp_path)
    assert result["status"] == "partial"
    assert not (tmp_path / "CURRENT.json").exists()
    _, manifest, data = stored(result)
    assert len(data) == 4 and manifest["quality"]["history_complete"] is False
    assert manifest["quality"]["missing_archive_count"] == 2


def test_corrupt_raw_or_publication_failure_preserves_current(
    tmp_path, archives, monkeypatch
):
    first = run(tmp_path)
    pointer = (tmp_path / "CURRENT.json").read_bytes()
    archives["close"] = "106"
    write = intake.publication._json

    def fail_pointer(path, value):
        if path.name == "CURRENT.json":
            raise OSError("pointer interrupted")
        write(path, value)

    monkeypatch.setattr(intake.publication, "_json", fail_pointer)
    with pytest.raises(OSError, match="pointer interrupted"):
        run(tmp_path)
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    monkeypatch.setattr(intake.publication, "_json", write)
    _, manifest, _ = stored(first)
    raw = tmp_path / next(iter(manifest["raw_files"]))
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="raw archive checksum"):
        run(tmp_path)
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer


def test_partial_release_inventory_is_checked_before_reuse(tmp_path, archives):
    archives["missing"].add("UNITREEUSDT-1d-2026-09-02.zip")
    partial = run(tmp_path, symbols="UNITREEUSDT")
    (Path(partial["data_dir"]) / "unlisted.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="inventory"):
        run(tmp_path, symbols="UNITREEUSDT")
    assert not (tmp_path / "CURRENT.json").exists()
