"""Publication checks: replay, revision, interruption, corruption and time gaps."""

import json
from datetime import date

import pandas as pd
import pytest

from backend.scripts import blockchain_sync as sync
from backend.services.engine.rd_agent.data_pipeline import crypto_data as fetch
from backend.tests.test_binance_data_fetch import bar


def frame(
    symbol="BTCUSDT", days=("2026-09-22", "2026-09-23", "2026-09-24"), close="105"
):
    return fetch._parse_klines(
        [bar(d, close=close) for d in days],
        symbol,
        "1d",
        {
            "request": {"url": "https://data-api.binance.vision/api/v3/klines"},
            "sha256": "a" * 64,
            "collected_at": "2026-09-25T00:01:00Z",
        },
    )


@pytest.fixture
def intake(monkeypatch, tmp_path):
    monkeypatch.setenv("QM_QUANTBC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        fetch,
        "get_binance_exchange_info",
        lambda symbols, **kwargs: {
            "symbols": [
                {
                    "symbol": s,
                    "baseAsset": s[:-4],
                    "quoteAsset": "USDT",
                    "status": "TRADING",
                    "isSpotTradingAllowed": True,
                    "filters": [],
                }
                for s in symbols
            ],
            "provenance": {"collected_at": "2026-09-25T00:01:00Z"},
        },
    )
    monkeypatch.setattr(
        fetch, "download_binance_klines", lambda symbol, **kwargs: frame(symbol)
    )
    monkeypatch.setattr(
        fetch,
        "get_binance_first_kline",
        lambda symbol, **kwargs: frame(symbol).iloc[:1],
    )
    return {
        "symbols": "BTCUSDT,ETHUSDT",
        "start_date": "2026-09-22",
        "end_date": "2026-09-25",
    }


def test_publication_replay_revision_and_old_input_unchanged(
    intake, tmp_path, monkeypatch
):
    first = sync.run(**intake)
    path, manifest, stored = sync._previous(tmp_path)
    old_manifest = (path / "manifest.json").read_bytes()
    assert len(stored) == 6
    assert stored.amount.eq(stored.quote_volume).all()
    assert manifest["quality"]["symbols"]["BTCUSDT"]["gaps"] == 0
    assert sync.run(**intake)["release_id"] == first["release_id"]
    assert len(list((tmp_path / "releases").iterdir())) == 1
    monkeypatch.setattr(
        fetch,
        "download_binance_klines",
        lambda symbol, **kwargs: frame(symbol, close="106"),
    )
    revised = sync.run(**intake)
    assert revised["release_id"] != first["release_id"]
    assert revised["revised_rows"] == 6
    assert (path / "manifest.json").read_bytes() == old_manifest
    assert len(sync._previous(tmp_path)[2]) == 6


def test_gap_failure_does_not_publish_or_advance_checkpoint(
    intake, tmp_path, monkeypatch
):
    first = sync.run(**intake)
    pointer = (tmp_path / "CURRENT.json").read_bytes()
    # The requested final closed day is absent; old data must not masquerade as current.
    with pytest.raises(ValueError, match="Daily gaps"):
        sync.run(**{**intake, "end_date": "2026-09-26"})
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    attempt = json.loads((tmp_path / "last_attempt.json").read_text())
    assert attempt["status"] == "failed"
    assert sync._previous(tmp_path)[1]["release_id"] == first["release_id"]


def test_unchanged_release_returns_its_published_quality(intake, monkeypatch):
    first = sync.run(**intake)
    validate = sync.validate_daily

    def check(*args, **kwargs):
        return {
            **validate(*args, **kwargs),
            "source_revisions": [{"check": "new provenance"}],
        }

    monkeypatch.setattr(sync, "validate_daily", check)
    replay = sync.run(**intake)
    assert replay["release_id"] == first["release_id"]
    assert replay["quality"] == first["quality"]
    assert replay["checked_quality"] != replay["quality"]


def test_corrupt_published_file_rejected(intake, tmp_path):
    result = sync.run(**intake)
    path = sync.Path(result["data_dir"]) / "quality.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        sync.run(**intake)


def test_current_commit_failure_preserves_old_reader(intake, tmp_path, monkeypatch):
    first = sync.run(**intake)
    monkeypatch.setattr(
        fetch,
        "download_binance_klines",
        lambda symbol, **kwargs: frame(symbol, close="106"),
    )
    write_json = sync._json

    def fail_commit(path, value):
        if path.name == "CURRENT.json":
            raise OSError("simulated interruption at publication")
        return write_json(path, value)

    monkeypatch.setattr(sync, "_json", fail_commit)
    with pytest.raises(OSError, match="interruption"):
        sync.run(**intake)
    assert sync._previous(tmp_path)[1]["release_id"] == first["release_id"]


def test_invalid_boundary_missing_native_amount_and_wrong_product(intake):
    raw = frame()
    with pytest.raises(ValueError, match="Missing original"):
        sync._normalise_kline(raw.drop(columns="quote_volume"), "BTCUSDT")
    normal = sync._normalise_kline(raw, "BTCUSDT")
    with pytest.raises(ValueError, match="Unclosed"):
        sync.validate_daily(normal, ["BTCUSDT"], date(2026, 9, 24))
    with pytest.raises(ValueError, match="derivatives"):
        sync.run(**intake, product_type="equity_perpetual")


def test_backfill_earlier_history_then_use_overlap(intake, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        fetch,
        "get_binance_first_kline",
        lambda symbol, **kw: frame(symbol, ("2026-09-01",)),
    )

    def download(symbol, **kwargs):
        calls.append(kwargs["start_date"])
        days = pd.date_range(kwargs["start_date"], "2026-09-24").strftime("%Y-%m-%d")
        return frame(symbol, days)

    monkeypatch.setattr(fetch, "download_binance_klines", download)
    limited = sync.run(**{**intake, "start_date": "2026-09-10"})
    assert limited["quality"]["history_complete"] is False
    complete = sync.run(**{**intake, "start_date": "2010-01-01"})
    assert complete["quality"]["history_complete"] is True
    assert complete["quality"]["rows"] == 48
    replay = sync.run(**{**intake, "start_date": "2010-01-01"})
    assert calls[-2:] == ["2026-09-17", "2026-09-17"]
    assert replay["release_id"] == complete["release_id"]
    refreshed = sync.run(**intake, refresh_history=True)
    assert calls[-2:] == ["2026-09-01", "2026-09-01"]
    assert refreshed["release_id"] == complete["release_id"]


def test_unlisted_payload_is_rejected(intake, tmp_path):
    result = sync.run(**intake)
    path = sync.Path(result["data_dir"])
    (path / "unlisted.json").write_text("{}")
    with pytest.raises(ValueError, match="inventory"):
        sync.run(**intake)


def test_committed_release_survives_attempt_journal_failure(
    intake, tmp_path, monkeypatch
):
    write_json = sync._json

    def fail_journal(path, value):
        if path.name == "last_attempt.json" and value.get("status") == "completed":
            raise OSError("journal unavailable")
        return write_json(path, value)

    monkeypatch.setattr(sync, "_json", fail_journal)
    result = sync.run(**intake)
    assert result["status"] == "completed"
    assert result["journal_warning"] == "journal unavailable"
    assert sync._previous(tmp_path)[1]["release_id"] == result["release_id"]


def test_short_scheduler_window_recovers_more_than_two_weeks_offline(
    intake, tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        fetch,
        "get_binance_first_kline",
        lambda symbol, **kwargs: frame(symbol, ("2026-08-01",)),
    )

    def download(symbol, **kwargs):
        calls.append((kwargs["start_date"], kwargs["end_date"]))
        days = pd.date_range(
            kwargs["start_date"], kwargs["end_date"], inclusive="left"
        ).strftime("%Y-%m-%d")
        return frame(symbol, days)

    monkeypatch.setattr(fetch, "download_binance_klines", download)
    initial = sync.run(
        symbols=intake["symbols"], start_date="2026-08-01", end_date="2026-09-09"
    )
    initial_path = sync.Path(initial["data_dir"])
    initial_manifest = (initial_path / "manifest.json").read_bytes()

    # Last stored bar is September 8; resume 17 days later with scheduler days=5.
    recovered = sync.run(symbols=intake["symbols"], days=5, end_date="2026-09-26")
    assert calls[-2:] == [("2026-09-01", "2026-09-26")] * 2
    assert recovered["release_id"] != initial["release_id"]
    assert recovered["quality"]["history_complete"] is True
    assert recovered["quality"]["rows"] == 112
    _, _, stored = sync._previous(tmp_path)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows = stored[stored.symbol == symbol]
        assert rows.time.min() == date(2026, 8, 1)
        assert rows.time.max() == date(2026, 9, 25)
        assert len(rows) == 56
        assert recovered["quality"]["symbols"][symbol]["gaps"] == 0
    assert (initial_path / "manifest.json").read_bytes() == initial_manifest

    replay = sync.run(symbols=intake["symbols"], days=5, end_date="2026-09-26")
    assert calls[-2:] == [("2026-09-18", "2026-09-26")] * 2
    assert replay["unchanged"] is True
    assert replay["release_id"] == recovered["release_id"]


def test_same_raw_decimal_response_is_idempotent_across_numeric_parsers(
    intake, tmp_path, monkeypatch
):
    from backend.tests.test_binance_data_fetch import (
        _REST_20260923_PRECISION,
        emulate_cloud_numeric_parser,
    )

    def download(symbol, **kwargs):
        return fetch._parse_klines(
            [_REST_20260923_PRECISION],
            symbol,
            "1d",
            {
                "request": {"url": fetch.BINANCE_KLINE_URLS[0]},
                "sha256": "b666e54043c7ebabd5024f390c1b5be19c3ea26687318f48ae097c150c7a3cec",
                "collected_at": "2026-09-26T03:12:18.855016Z",
            },
        )

    monkeypatch.setattr(fetch, "download_binance_klines", download)
    args = {"symbols": "BTCUSDT", "start_date": "2026-09-23", "end_date": "2026-09-24"}
    initial = sync.run(**args)
    pointer = (tmp_path / "CURRENT.json").read_bytes()
    emulate_cloud_numeric_parser(monkeypatch)
    replay = sync.run(**args)
    assert replay["release_id"] == initial["release_id"]
    assert replay["unchanged"] is True
    assert replay["revised_rows"] == 0
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    assert len(list((tmp_path / "releases").iterdir())) == 1
    stored = sync._previous(tmp_path)[2].iloc[0]
    assert float(stored.quote_volume).hex() == "0x1.c2125088a08fap+30"
    assert stored.amount == stored.quote_volume


@pytest.mark.parametrize("old_numeric_semantics", [None, "pandas_to_numeric"])
def test_numeric_contract_migration_replays_history_then_is_idempotent(
    intake, tmp_path, monkeypatch, old_numeric_semantics
):
    calls = []
    monkeypatch.setattr(
        fetch,
        "get_binance_first_kline",
        lambda symbol, **kwargs: frame(symbol, ("2026-09-01",)),
    )

    def download(symbol, **kwargs):
        calls.append(kwargs["start_date"])
        days = pd.date_range(
            kwargs["start_date"], kwargs["end_date"], inclusive="left"
        ).strftime("%Y-%m-%d")
        return frame(symbol, days)

    monkeypatch.setattr(fetch, "download_binance_klines", download)
    old_contract = dict(sync.MANIFEST_SEMANTICS)
    if old_numeric_semantics is None:
        old_contract.pop("numeric_semantics")
    else:
        old_contract["numeric_semantics"] = old_numeric_semantics
    with monkeypatch.context() as old_context:
        old_context.setattr(sync, "MANIFEST_SEMANTICS", old_contract)
        legacy = sync.run(**{**intake, "start_date": "2026-09-01"})
    legacy_path = sync.Path(legacy["data_dir"])
    legacy_bytes = (legacy_path / "manifest.json").read_bytes()
    legacy_manifest = json.loads(legacy_bytes)

    # A normal five-day scheduler run must not relabel untouched older rows.
    args = {"symbols": intake["symbols"], "days": 5, "end_date": "2026-09-25"}
    legacy_pointer = (tmp_path / "CURRENT.json").read_bytes()

    def incomplete_download(symbol, **kwargs):
        observations = download(symbol, **kwargs)
        return observations[observations.open_time.dt.date != date(2026, 9, 10)]

    with monkeypatch.context() as failed_context:
        failed_context.setattr(fetch, "download_binance_klines", incomplete_download)
        with pytest.raises(ValueError, match="Daily gaps"):
            sync.run(**args)
    assert calls[-2:] == ["2026-09-01"] * 2
    assert (tmp_path / "CURRENT.json").read_bytes() == legacy_pointer
    assert (legacy_path / "manifest.json").read_bytes() == legacy_bytes
    assert sync._previous(tmp_path)[1]["release_id"] == legacy["release_id"]

    migrated = sync.run(**args)
    assert calls[-2:] == ["2026-09-01"] * 2
    assert migrated["release_id"] != legacy["release_id"]
    assert migrated["unchanged"] is False
    assert (
        migrated["revised_rows"] == 0
    )  # Exact fixture values need only a contract upgrade.
    _, manifest, _ = sync._previous(tmp_path)
    assert manifest["numeric_semantics"] == "python_float_binary64_from_source_decimal"
    assert manifest["data_digest"] == legacy_manifest["data_digest"]
    assert manifest["previous_release_id"] == legacy["release_id"]
    assert (legacy_path / "manifest.json").read_bytes() == legacy_bytes
    pointer = (tmp_path / "CURRENT.json").read_bytes()

    replay = sync.run(**args)
    assert calls[-2:] == ["2026-09-17"] * 2
    assert replay["release_id"] == migrated["release_id"]
    assert replay["unchanged"] is True
    assert replay["revised_rows"] == 0
    assert (tmp_path / "CURRENT.json").read_bytes() == pointer
    assert len(list((tmp_path / "releases").iterdir())) == 2
