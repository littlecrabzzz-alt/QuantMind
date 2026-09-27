"""Temporary synthetic inputs only; canonical donor keys and join cardinality."""

import pandas as pd
import pytest

from backend.services.engine.data_platform.quantdb_factor_reader import (
    DAILY_BACKWARD_DIR,
    FACTOR_SOURCE_DIRS,
    OHLCV_COLUMNS,
    QuantDBFactorError,
    QuantDBFactorReader,
)
from backend.shared.stock_utils import StockCodeUtil

DAY = "2026-03-24"


def _write(root, dataset, rows):
    path = root / dataset / "dt=20260324" / "synthetic.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _main(symbol, value=None, alpha=0.25, with_ohlcv=True):
    row = {"symbol": symbol, "date": DAY, "alpha": alpha}
    if with_ohlcv:
        row.update(dict.fromkeys(OHLCV_COLUMNS, value))
    return row


def _donor(symbol, value=22.0):
    return {"symbol": symbol, **dict.fromkeys(OHLCV_COLUMNS, value)}


def _setup(root, route, main_rows, donor_rows, market="CN"):
    source = "l1_factors" if route == "daily_backward" else "ccass_factors"
    _write(root, FACTOR_SOURCE_DIRS[source], main_rows)
    donor_dataset = (
        DAILY_BACKWARD_DIR
        if route == "daily_backward"
        else FACTOR_SOURCE_DIRS["l1_factors"]
    )
    donor_path = _write(root, donor_dataset, donor_rows)
    return QuantDBFactorReader(root, market=market), source, donor_path


def _read(reader, source, include_ohlcv=True):
    return reader.read_range(
        source,
        features=["alpha"],
        start=DAY,
        end=DAY,
        include_ohlcv=include_ohlcv,
    )


@pytest.mark.parametrize("route", ["daily_backward", "l1_donor"])
@pytest.mark.parametrize("reverse", [False, True])
def test_both_routes_and_directions_use_shared_symbol_contract(
    tmp_path, route, reverse
):
    pairs = [
        ("600001.SH", "SH600001"),
        ("000001.SZ", "SZ000001"),
        ("830001.BJ", "BJ830001"),
        ("510300", "SH510300"),
        ("520000", "SH520000"),
        ("560000", "SH560000"),
        ("588000", "SH588000"),
        ("159915", "SZ159915"),
        ("160000", "SZ160000"),
        ("0001.hk", "0001.HK"),
        ("aapl", "AAPL"),
        ("btc-usdt", "BTC-USDT"),
        ("123456", "123456"),  # Shared helper leaves this unknown bare code alone.
    ]
    if reverse:
        pairs = [(b, a) for a, b in pairs]
    main = [_main(a, with_ohlcv=route == "daily_backward") for a, _ in pairs]
    donor = [_donor(b) for _, b in pairs]
    reader, source, _ = _setup(tmp_path, route, main, donor)
    frame = _read(reader, source)
    assert len(frame) == len(pairs)
    assert set(frame["symbol"]) == {StockCodeUtil.to_prefix(a) for a, _ in pairs}
    assert (frame[list(OHLCV_COLUMNS)] == 22.0).all().all()
    assert frame.attrs["ohlcv_availability"]["missing_rows"] == 0


@pytest.mark.parametrize("route", ["daily_backward", "l1_donor"])
def test_same_format_and_main_values_keep_priority(tmp_path, route):
    main = [_main("600001.SH", 11.0), _main("000001.SZ", 11.0)]
    main[1]["close"] = None
    reader, source, _ = _setup(
        tmp_path, route, main, [_donor("600001.SH"), _donor("000001.SZ")]
    )
    # A secondary source with its own OHLCV does not activate the L1 donor route.
    if route == "l1_donor":
        _write(tmp_path, DAILY_BACKWARD_DIR, [_donor("600001.SH"), _donor("000001.SZ")])
    frame = _read(reader, source).set_index("symbol")
    assert frame.loc["SH600001", list(OHLCV_COLUMNS)].tolist() == [11.0] * 6
    assert frame.loc["SZ000001", "close"] == 22.0
    assert frame.loc["SZ000001", "open"] == 11.0


@pytest.mark.parametrize("route", ["daily_backward", "l1_donor"])
@pytest.mark.parametrize("duplicate_symbol", ["600001.SH", "SH600001"])
@pytest.mark.parametrize("duplicate_value", [22.0, 33.0])
def test_any_duplicate_canonical_donor_key_is_rejected(
    tmp_path, route, duplicate_symbol, duplicate_value
):
    reader, source, _ = _setup(
        tmp_path,
        route,
        [_main("600001.SH", with_ohlcv=route == "daily_backward")],
        [_donor("600001.SH"), _donor(duplicate_symbol, duplicate_value)],
    )
    with pytest.raises(
        QuantDBFactorError,
        match=r"Duplicate canonical OHLCV donor key.*SH600001/20260324 \(2 rows\)",
    ):
        _read(reader, source)


@pytest.mark.parametrize("include_ohlcv", [True, False])
def test_main_canonical_collision_cannot_be_hidden_by_dedup(tmp_path, include_ohlcv):
    reader, source, _ = _setup(
        tmp_path,
        "daily_backward",
        [_main("600001.SH", 11.0, 1.0), _main("SH600001", 11.0, 2.0)],
        [_donor("SH600001")],
    )
    with pytest.raises(
        QuantDBFactorError, match="Canonical factor key collision.*SH600001"
    ):
        _read(reader, source, include_ohlcv)


def test_existing_same_raw_key_keep_last_is_preserved(tmp_path):
    reader, source, _ = _setup(
        tmp_path,
        "daily_backward",
        [_main("600001.SH", 11.0, 1.0), _main("600001.SH", 11.0, 2.0)],
        [_donor("SH600001")],
    )
    frame = _read(reader, source)
    assert len(frame) == 1
    assert frame.iloc[0]["alpha"] == 2.0


@pytest.mark.parametrize("route", ["daily_backward", "l1_donor"])
def test_true_missing_donor_rows_stay_missing_and_are_reported(tmp_path, route):
    reader, source, _ = _setup(
        tmp_path,
        route,
        [
            _main("600001.SH", with_ohlcv=route == "daily_backward"),
            _main("000001.SZ", with_ohlcv=route == "daily_backward"),
            _main("123456", with_ohlcv=route == "daily_backward"),
        ],
        [_donor("SH600001"), _donor("SH123456")],
    )
    frame = _read(reader, source).set_index("symbol")
    assert frame.loc["SH600001", "close"] == 22.0
    assert pd.isna(frame.loc["SZ000001", "close"])
    assert pd.isna(frame.loc["123456", "close"])  # Do not guess a market.
    report = frame.attrs["ohlcv_availability"]
    assert report["missing_rows"] == 2
    assert report["missing_by_column"] == dict.fromkeys(OHLCV_COLUMNS, 2)
    assert {e["symbol"] for e in report["examples"]} == {"SZ000001", "123456"}
    assert not report["examples_truncated"]


def test_zero_matches_not_forced_to_fail_and_diagnostic_examples_are_bounded(tmp_path):
    reader, source, _ = _setup(
        tmp_path,
        "l1_donor",
        [_main(f"SYNTHETIC-{i}", with_ohlcv=False) for i in range(25)],
        [_donor("OTHER")],
        market="CUSTOM",
    )
    frame = _read(reader, source)
    report = frame.attrs["ohlcv_availability"]
    assert len(frame) == report["missing_rows"] == 25
    assert len(report["examples"]) == 20
    assert report["examples_truncated"]


@pytest.mark.parametrize("route", ["daily_backward", "l1_donor"])
def test_no_ohlcv_does_not_inspect_or_join_donor(tmp_path, monkeypatch, route):
    reader, source, donor_path = _setup(
        tmp_path, route, [_main("600001.SH", with_ohlcv=False)], [_donor("SH600001")]
    )
    donor_path.write_bytes(b"OHLCV_NOT_REQUESTED_MUST_NOT_BE_OPENED")

    def forbidden(*args, **kwargs):
        pytest.fail("include_ohlcv=False inspected an OHLCV donor")

    monkeypatch.setattr(reader, "_donor_has_ohlcv", forbidden)
    monkeypatch.setattr(reader, "_ohlcv_donor_relation", forbidden)
    monkeypatch.setattr(reader, "_daily_backward_relation", forbidden)
    frame = _read(reader, source, include_ohlcv=False)
    assert list(frame.columns) == ["symbol", "trade_date", "alpha"]
    assert frame["symbol"].tolist() == ["SH600001"]
    assert "ohlcv_availability" not in frame.attrs


def test_no_ohlcv_still_requires_source_keys(tmp_path):
    _write(tmp_path, FACTOR_SOURCE_DIRS["l1_factors"], [{"date": DAY, "alpha": 1.0}])
    with pytest.raises(QuantDBFactorError, match="not ready"):
        _read(QuantDBFactorReader(tmp_path), "l1_factors", include_ohlcv=False)


@pytest.mark.parametrize(
    "market,symbol", [("HK", "0001.HK"), ("US", "AAPL"), ("CRYPTO", "BTCUSDT")]
)
def test_other_markets_use_shared_passthrough_contract(tmp_path, market, symbol):
    reader, source, _ = _setup(
        tmp_path,
        "l1_donor",
        [_main(symbol, with_ohlcv=False)],
        [_donor(symbol)],
        market=market,
    )
    frame = _read(reader, source)
    assert frame["symbol"].tolist() == [StockCodeUtil.to_prefix(symbol)]
    assert frame["close"].tolist() == [22.0]
