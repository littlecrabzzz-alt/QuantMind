"""Only temporary synthetic parquet: bound schema and data I/O before DuckDB."""

from datetime import date

import pandas as pd
import pytest

from backend.services.engine.data_platform.quantdb_factor_reader import (
    DAILY_BACKWARD_DIR,
    FACTOR_SOURCE_DIRS,
    OHLCV_COLUMNS,
    QuantDBFactorError,
    QuantDBFactorReader,
)


def _frame(day):
    return pd.DataFrame(
        [
            {
                "symbol": "600001.SH",
                "date": day,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
                "amount": 1100.0,
                "alpha": 0.25,
            }
        ]
    )


def _write(root, dataset, day, frame):
    path = root / dataset / ("dt=" + day.replace("-", "")) / "data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def _setup(root, route):
    source = "ccass_factors" if route == "l1_donor" else "l1_factors"
    for day in ("2026-03-23", "2026-03-24"):
        frame = _frame(day)
        if route == "daily_backward":
            frame[list(OHLCV_COLUMNS)] = None
        elif route == "l1_donor":
            frame = frame.drop(columns=list(OHLCV_COLUMNS))
        _write(root, FACTOR_SOURCE_DIRS[source], day, frame)
        if route != "factor":
            donor = (
                DAILY_BACKWARD_DIR
                if route == "daily_backward"
                else FACTOR_SOURCE_DIRS["l1_factors"]
            )
            _write(root, donor, day, _frame(day).drop(columns=["alpha", "date"]))
    reader = QuantDBFactorReader(root)
    return source, reader


def _read(reader, source):
    return (
        reader.read_range(
            source, features=["alpha"], start=date(2026, 3, 23), end="2026-03-24"
        )
        .sort_values(["symbol", "trade_date"])
        .reset_index(drop=True)
    )


@pytest.mark.parametrize("route", ["factor", "daily_backward", "l1_donor"])
@pytest.mark.parametrize("outside_day", ["2026-03-22", "2026-03-25"])
@pytest.mark.parametrize("sentinel", ["broken_footer", "incompatible_schema"])
def test_outside_files_cannot_affect_schema_or_data(
    tmp_path, route, outside_day, sentinel
):
    source, reader = _setup(tmp_path, route)
    expected = _read(reader, source)
    assert expected["close"].tolist() == [11.0, 11.0]
    assert expected["alpha"].tolist() == [0.25, 0.25]
    dataset = (
        DAILY_BACKWARD_DIR
        if route == "daily_backward"
        else FACTOR_SOURCE_DIRS["l1_factors"]
    )
    outside = _frame(outside_day)
    # A future/past struct column would change union schema before SQL WHERE.
    outside["alpha" if route == "factor" else "close"] = [{"forbidden": 999}]
    path = _write(tmp_path, dataset, outside_day, outside)
    if sentinel == "broken_footer":
        path.write_bytes(b"OUTSIDE_REQUEST_MUST_NOT_BE_OPENED")
    actual = _read(reader, source)
    pd.testing.assert_frame_equal(actual, expected)


def test_normal_reads_keep_aliases_bounds_and_nonpartition_exclusion(tmp_path):
    # Quotes in paths must remain escaped in the explicit DuckDB file list.
    root = tmp_path / "quote's"
    source, reader = _setup(root, "factor")
    source_root = root / FACTOR_SOURCE_DIRS[source]
    (source_root / "legacy.parquet").write_bytes(b"NOT_A_PUBLISHED_PARTITION")
    stage = source_root / "_stage"
    stage.mkdir()
    (stage / "staging.parquet").write_bytes(b"NOT_A_PUBLISHED_PARTITION")
    frame = reader.read_day(
        source,
        features=["mapped"],
        feature_sources={"mapped": "alpha"},
        trade_date="2026-03-24",
    )
    assert frame["symbol"].tolist() == ["SH600001"]
    assert frame["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-03-24"]
    assert frame["mapped"].tolist() == [0.25]
    assert reader.describe(source).files == 2
    assert reader.available_dates(source) == ["2026-03-23", "2026-03-24"]


@pytest.mark.parametrize("partition", ["20260230", "2026-03-25", "unknown"])
def test_invalid_partition_dates_rejected_before_any_duckdb_open(
    tmp_path, monkeypatch, partition
):
    source, reader = _setup(tmp_path, "factor")
    path = tmp_path / FACTOR_SOURCE_DIRS[source] / f"dt={partition}" / "bad.parquet"
    path.parent.mkdir()
    path.write_bytes(b"INVALID_DATE_MUST_NOT_BE_OPENED")

    def forbidden_open():
        pytest.fail("Malformed partition reached DuckDB")

    monkeypatch.setattr(reader, "_duckdb", forbidden_open)
    with pytest.raises(QuantDBFactorError, match="Invalid QuantDB date partition"):
        _read(reader, source)


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-02-30", "2026-03-24"),
        ("2026-03-25", "2026-03-24"),
        ("2026-03-23", ""),
        (None, "2026-03-24"),
        ("2026-03-23", None),
    ],
)
def test_invalid_request_range_rejected_before_any_duckdb_open(
    tmp_path, monkeypatch, start, end
):
    source, reader = _setup(tmp_path, "factor")
    monkeypatch.setattr(
        reader, "_duckdb", lambda: pytest.fail("Invalid range reached DuckDB")
    )
    with pytest.raises(QuantDBFactorError, match="date range|start date|date bounds"):
        reader.read_range(source, features=["alpha"], start=start, end=end)


def test_empty_selection_does_not_sample_outside_schema(tmp_path, monkeypatch):
    source, reader = _setup(tmp_path, "factor")
    monkeypatch.setattr(
        reader, "_duckdb", lambda: pytest.fail("Empty range reached DuckDB")
    )
    with pytest.raises(QuantDBFactorError, match="No parquet files found in requested"):
        reader.read_day(source, features=["alpha"], trade_date="2026-03-22")


def test_donor_only_outside_range_is_not_available(tmp_path):
    frame = _frame("2026-03-24").drop(columns=list(OHLCV_COLUMNS))
    _write(tmp_path, FACTOR_SOURCE_DIRS["ccass_factors"], "2026-03-24", frame)
    path = _write(
        tmp_path, FACTOR_SOURCE_DIRS["l1_factors"], "2026-03-25", _frame("2026-03-25")
    )
    path.write_bytes(b"FUTURE_DONOR_MUST_NOT_BE_OPENED")
    reader = QuantDBFactorReader(tmp_path)
    with pytest.raises(QuantDBFactorError, match="donor unavailable"):
        reader.read_day("ccass_factors", features=["alpha"], trade_date="2026-03-24")


def test_in_range_bad_file_is_still_an_error(tmp_path):
    source, reader = _setup(tmp_path, "factor")
    current = tmp_path / FACTOR_SOURCE_DIRS[source] / "dt=20260324" / "data.parquet"
    current.write_bytes(b"IN_RANGE_DAMAGE_MUST_NOT_BE_HIDDEN")
    with pytest.raises(QuantDBFactorError, match="not ready"):
        reader.read_day(source, features=["alpha"], trade_date="2026-03-24")


def test_bounded_description_dates_match_selected_files_and_keep_coverage_semantics(
    tmp_path,
):
    source, reader = _setup(tmp_path, "factor")
    for day in ("2026-03-20", "2026-03-25"):
        _write(tmp_path, FACTOR_SOURCE_DIRS[source], day, _frame(day))

    bounded = reader.describe(source, start="2026-03-23", end="2026-03-24")
    assert (bounded.files, bounded.min_date, bounded.max_date) == (
        2,
        "2026-03-23",
        "2026-03-24",
    )
    unbounded = reader.describe(source)
    assert (unbounded.files, unbounded.min_date, unbounded.max_date) == (
        4,
        "2026-03-20",
        "2026-03-25",
    )
    # Sunday need not have a partition when the full source covers that date.
    ready = reader.assert_ready(source, start="2026-03-22", end="2026-03-24")
    assert ready.ready
    assert (ready.min_date, ready.max_date) == ("2026-03-23", "2026-03-24")
    frame = reader.read_range(
        source, features=["alpha"], start="2026-03-22", end="2026-03-24"
    )
    assert sorted(frame["trade_date"].dt.strftime("%Y-%m-%d")) == [
        "2026-03-23",
        "2026-03-24",
    ]
    with pytest.raises(QuantDBFactorError, match="starts at 2026-03-20"):
        reader.assert_ready(source, start="2026-03-19", end="2026-03-24")
    with pytest.raises(QuantDBFactorError, match="ends at 2026-03-25"):
        reader.assert_ready(source, start="2026-03-23", end="2026-03-26")
