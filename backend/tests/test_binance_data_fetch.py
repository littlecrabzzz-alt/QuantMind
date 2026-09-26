"""Offline contract checks for Binance public REST and monthly archive ingestion."""

import hashlib
import io
import json
import zipfile

import pandas as pd
import pytest
import requests

from backend.services.engine.rd_agent.data_pipeline import crypto_data as data


def bar(day, *, unit="ms", close="105"):
    opening = pd.Timestamp(day, tz="UTC").value // (
        1_000 if unit == "us" else 1_000_000
    )
    duration = 86_400_000_000 if unit == "us" else 86_400_000
    return [
        opening,
        "100",
        "110",
        "90",
        close,
        "10",
        opening + duration - 1,
        "1025",
        12,
        "4",
        "410",
        "0",
    ]


def response(payload, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers or {})
    result._content = (
        payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    )
    return result


def test_rest_closed_utc_native_fields_raw_cache(monkeypatch, tmp_path):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response([bar("2026-09-23"), bar("2026-09-24"), bar("2026-09-25")])

    monkeypatch.setattr(requests, "get", get)
    kwargs = {
        "start_date": "2026-09-23",
        "end_date": "2026-09-26",
        "now": "2026-09-25T12:00:00Z",
        "cache_dir": tmp_path,
    }
    frame = data.download_binance_klines("BTCUSDT", **kwargs)
    assert len(frame) == 2  # Today's still-open candle is never available.
    assert str(frame.datetime.dt.tz) == "UTC"
    assert frame.iloc[-1].available_at == pd.Timestamp("2026-09-25T00:00:00Z")
    assert frame.iloc[0].quote_volume == 1025  # Native turnover, not close * volume.
    assert frame.iloc[0].trades == 12
    assert frame.iloc[0].taker_buy_quote_volume == 410
    assert frame.iloc[0].source_timestamp_unit == "ms"
    assert len(frame.iloc[0].source_sha256) == 64
    assert (
        calls[0][1]["params"]["endTime"]
        == pd.Timestamp("2026-09-25T12:00:00Z").value // 1_000_000 - 1
    )
    assert len(list(tmp_path.glob("*.response"))) == 1
    pd.testing.assert_frame_equal(
        data.download_binance_klines("BTCUSDT", **kwargs), frame
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,expected_calls",
    [(451, 1), (403, 1), (418, 1), (400, 1), (500, 3), (429, 3)],
)
def test_bounded_retries_no_alternate_domains(monkeypatch, status, expected_calls):
    calls = []
    monkeypatch.setattr(data.time, "sleep", lambda _: None)

    def get(url, **kwargs):
        calls.append(url)
        return response({"msg": "blocked"}, status)

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(requests.HTTPError):
        data.download_binance_klines(
            "BTCUSDT", start_date="2026-01-01", end_date="2026-01-02", max_retries=2
        )
    assert len(calls) == expected_calls
    assert set(calls) == {"https://data-api.binance.vision/api/v3/klines"}


def test_pagination_nonadvancement_is_failure(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda _: None)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response([bar("2026-01-01")]))
    with pytest.raises(ValueError, match="forward progress"):
        data.download_binance_klines(
            "BTCUSDT", start_date="2026-01-01", end_date="2026-01-04", limit=1
        )


@pytest.mark.parametrize(
    "rows,error",
    [
        ([bar("2026-01-01", close="120")], "OHLCV"),
        ([bar("2026-01-01"), bar("2026-01-01", close="104")], "Conflicting duplicate"),
    ],
)
def test_rejects_invalid_or_conflicting_data(monkeypatch, rows, error):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response(rows))
    with pytest.raises(ValueError, match=error):
        data.download_binance_klines(
            "BTCUSDT", start_date="2026-01-01", end_date="2026-01-02"
        )


def test_archive_microseconds_checksum_and_public_validator(monkeypatch, tmp_path):
    filename = "BTCUSDT-1d-2025-01"
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            filename + ".csv", ",".join(map(str, bar("2025-01-01", unit="us"))) + "\n"
        )
    payload = content.getvalue()
    checksum = f"{hashlib.sha256(payload).hexdigest()}  {filename}.zip\n".encode()
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: response(checksum if url.endswith(".CHECKSUM") else payload),
    )
    frame = data.download_binance_klines(
        "BTCUSDT",
        start_date="2025-01-01",
        end_date="2025-02-01",
        source="archive",
        cache_dir=tmp_path,
    )
    assert frame.iloc[0].datetime == pd.Timestamp("2025-01-01T00:00:00Z")
    assert frame.iloc[0].available_at == pd.Timestamp("2025-01-02T00:00:00Z")
    assert frame.iloc[0].source_timestamp_unit == "us"
    data.validate_binance_klines(frame)
    broken = frame.copy()
    broken.loc[0, "low"] = 1000
    with pytest.raises(ValueError, match="OHLCV"):
        data.validate_binance_klines(broken)
    assert len(list(tmp_path.glob("*.zip"))) == 1
    assert len(list(tmp_path.glob("*.CHECKSUM"))) == 1
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: response(
            b"0" * 64 + f"  {filename}.zip".encode()
            if url.endswith(".CHECKSUM")
            else payload
        ),
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        data.download_binance_klines(
            "BTCUSDT", start_date="2025-01-01", end_date="2025-02-01", source="archive"
        )


def test_exchange_info_keeps_native_asset_metadata(monkeypatch, tmp_path):
    native = {
        "timezone": "UTC",
        "symbols": [
            {
                "symbol": "AAPLBUSDT",
                "baseAsset": "AAPLB",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.01"}],
            }
        ],
    }
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response(native))
    result = data.get_binance_exchange_info(["AAPLBUSDT"], cache_dir=tmp_path)
    assert result["symbols"] == native["symbols"]
    assert "asset_type" not in result["symbols"][0]
    assert result["provenance"]["request"]["url"].endswith("exchangeInfo")


@pytest.mark.parametrize("status", [404, 451])
def test_auto_archive_fallback_only_for_missing_object(monkeypatch, status):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith(".zip"):
            return response({"message": "archive unavailable"}, status=status)
        return response([bar("2025-01-01")])

    monkeypatch.setattr(requests, "get", get)
    args = {"start_date": "2025-01-01", "end_date": "2025-02-01", "source": "auto"}
    if status == 451:
        with pytest.raises(requests.HTTPError):
            data.download_binance_klines("BTCUSDT", **args)
        assert len(calls) == 1
    else:
        frame = data.download_binance_klines("BTCUSDT", **args)
        assert len(frame) == 1
        assert frame.iloc[0].source == data.BINANCE_KLINE_URLS[0]
        assert len(calls) == 2


def test_first_kline_is_single_utc_probe_with_raw_provenance(monkeypatch, tmp_path):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return response([bar("2017-08-17")])

    monkeypatch.setattr(requests, "get", get)
    first = data.get_binance_first_kline("BTCUSDT", cache_dir=tmp_path)
    assert len(first) == 1
    assert first.iloc[0].open_time == pd.Timestamp("2017-08-17T00:00:00Z")
    assert calls == [
        {"symbol": "BTCUSDT", "interval": "1d", "startTime": 0, "limit": 1}
    ]
    assert len(first.iloc[0].source_sha256) == 64
    assert len(list(tmp_path.glob("*.response"))) == 1


def test_exchange_info_serializes_multiple_symbols_without_spaces(monkeypatch):
    def get(url, **kwargs):
        assert kwargs["params"] == {"symbols": '["BTCUSDT","ETHUSDT"]'}
        return response({"symbols": [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]})

    monkeypatch.setattr(requests, "get", get)
    assert len(data.get_binance_exchange_info(["BTCUSDT", "ETHUSDT"])["symbols"]) == 2


# Real BTCUSDT 2018-02-08 discrepancy: REST retained a 00:28 close-time;
# the official 2018-02 archive closes at the UTC day end with identical values.
# Verified ZIP SHA256: 037b2a4846cde6fb748aeb556e9dd84d964c1418097b979a2a4063fa3e9321e3.
_REST_20180208 = [
    1518048000000,
    "7599.00000000",
    "7844.00000000",
    "7572.09000000",
    "7784.02000000",
    "1521.53731800",
    1518049694788,
    "11770168.04386595",
    12417,
    "844.25881300",
    "6532638.63751892",
    "0",
]


@pytest.mark.parametrize("different_price", [False, True])
def test_real_historical_close_time_requires_verified_identical_archive(
    monkeypatch, tmp_path, different_price
):
    archived = list(_REST_20180208)
    archived[6] = 1518134399999
    if different_price:
        archived[4] = "7784.03000000"
    filename = "BTCUSDT-1d-2018-02"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(filename + ".csv", ",".join(map(str, archived)) + "\n")
    payload = stream.getvalue()
    checksum = f"{hashlib.sha256(payload).hexdigest()}  {filename}.zip\n".encode()
    rest_payload = json.dumps([_REST_20180208]).encode()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            return response(checksum)
        if url.endswith(".zip"):
            return response(payload)
        return response(rest_payload)

    monkeypatch.setattr(requests, "get", get)
    kwargs = {
        "start_date": "2018-02-08",
        "end_date": "2018-02-09",
        "cache_dir": tmp_path,
    }
    if different_price:
        with pytest.raises(ValueError, match="economic values differ"):
            data.download_binance_klines("BTCUSDT", **kwargs)
    else:
        frame = data.download_binance_klines("BTCUSDT", **kwargs)
        assert len(frame) == 1
        row = frame.iloc[0]
        assert row.close_time == pd.Timestamp("2018-02-08T23:59:59.999Z")
        assert row.available_at == pd.Timestamp("2018-02-09T00:00:00Z")
        assert row.rest_close_time == pd.Timestamp("2018-02-08T00:28:14.788Z")
        assert row.rest_source_sha256 == hashlib.sha256(rest_payload).hexdigest()
        assert row.source_sha256 == hashlib.sha256(payload).hexdigest()
        assert row.source_revision == "archive_corrected_rest_close_time"
        assert row.source.endswith("BTCUSDT-1d-2018-02.zip")
        assert len(list(tmp_path.glob("*.response"))) == 1
        assert len(list(tmp_path.glob("*.zip"))) == 1
        assert len(list(tmp_path.glob("*.CHECKSUM"))) == 1
    assert len(calls) == 3


def test_invalid_cross_period_close_is_not_repaired(monkeypatch):
    malformed = list(_REST_20180208)
    malformed[6] = 1518134400000  # Exactly next-day open is outside this daily bar.
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return response([malformed])

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError, match="crosses its daily period"):
        data.download_binance_klines(
            "BTCUSDT", start_date="2018-02-08", end_date="2018-02-09"
        )
    assert calls == [data.BINANCE_KLINE_URLS[0]]
