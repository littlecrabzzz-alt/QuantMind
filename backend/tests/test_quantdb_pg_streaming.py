"""Real Parquet/DuckDB regression checks; the PG sink is isolated in memory."""
import pandas as pd
import pytest

from backend.scripts import quantdb_daily_sync as sync


class Sink:
    def __init__(self, fail_write=None):
        self.rows = {}
        self.pending = {}
        self.writes = 0
        self.fail_write = fail_write
        self.rollbacks = 0
        self.closed = False
        self.disposed = False

    def raw_connection(self):
        return self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        self.rows.update(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def dispose(self):
        self.disposed = True

    def execute_values(self, cursor, sql, rows, page_size):
        self.writes += 1
        if self.writes == self.fail_write:
            raise RuntimeError("injected second-page failure")
        cols = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
        for row in rows:
            value = dict(zip(cols, row))
            self.pending[(value["trade_date"], value["symbol"])] = value


@pytest.fixture
def source(tmp_path, monkeypatch):
    dates = pd.date_range("2026-01-01", periods=140)
    history = []
    for i, day in enumerate(dates):
        prices = pd.DataFrame([
            {"symbol": f"{s:06d}.SZ", "open": 10 + s + i / 20,
             "high": 11 + s + i / 20, "low": 9 + s + i / 20,
             "close": 10.5 + s + i / 20, "volume": 1000 + i, "amount": 2000 + i}
            for s in range(1, 91)
        ])
        path = tmp_path / "1_kline_data/daily_forward" / f"dt={day:%Y%m%d}"
        path.mkdir(parents=True)
        prices.to_parquet(path / "data.parquet", index=False)
        history.append(prices.assign(trade_date=day.date()))
        if i >= 74:
            feat = prices[["symbol"]].copy()
            for j, name in enumerate(sync._FEATURE_COLS):
                feat[name] = i + j / 10
            path = tmp_path / "6_ml_datasets/features_daily" / f"dt={day:%Y%m%d}"
            path.mkdir(parents=True)
            feat.to_parquet(path / "data.parquet", index=False)
    # Unrelated / out-of-window files must not be bound by a global view scan.
    for rel in ("1_kline_data/daily_forward/dt=20160104",
                "6_ml_datasets/features_daily/dt=20260101",
                "6_ml_datasets/l2_factors/dt=20260501"):
        path = tmp_path / rel
        path.mkdir(parents=True, exist_ok=True)
        (path / "data.parquet").write_bytes(b"not parquet")
    monkeypatch.setattr(sync, "QUANTDB_DATA_DIR", tmp_path)
    return tmp_path, pd.concat(history, ignore_index=True), dates[74].date(), dates[-1].date()


def bind_sink(monkeypatch, sink):
    monkeypatch.setattr(sync, "_get_engine", lambda: sink)
    monkeypatch.setattr("psycopg2.extras.execute_values", sink.execute_values)


def test_streamed_values_warmup_filter_and_idempotence(source, monkeypatch):
    _, history, start, end = source
    sink = Sink()
    bind_sink(monkeypatch, sink)
    expected = sync._add_price_derived_cols(history)
    expected = expected[expected.trade_date >= start].copy()
    expected["symbol"] = expected.symbol.map(sync._to_internal)
    expected = expected.set_index(["trade_date", "symbol"]).sort_index()
    original = sync._add_price_derived_cols
    sizes = []

    def observe(frame):
        sizes.append(len(frame))
        return original(frame)

    monkeypatch.setattr(sync, "_add_price_derived_cols", observe)
    for _ in range(2):
        result = sync.fill_pg_from_parquet(start_date=start, end_date=end, batch_days=100)
        assert result["status"] == "ok", result
        assert result["rows"] == 90 * 66
        assert len(sink.rows) == 90 * 66
    assert max(sizes) == 140  # Full history retained per symbol, never per market.
    actual = pd.DataFrame(sink.rows.values()).set_index(["trade_date", "symbol"]).sort_index()
    cols = list(sync._KLINE_COLS) + list(sync._PRICE_DERIVED_COLS)
    pd.testing.assert_frame_equal(actual[cols], expected[cols], check_dtype=False)
    assert actual.loc[(end, "SZ000001"), "pe_ttm"] == 139
    assert actual.loc[(end, "SZ000001"), "volume_ma_5"] == pytest.approx(140.8)
    assert sink.closed and sink.disposed

    filtered = Sink()
    bind_sink(monkeypatch, filtered)
    result = sync.fill_pg_from_parquet(symbols=["SZ000002"], start_date=start,
                                       end_date=end, batch_days=100)
    assert result["rows"] == 66
    assert {key[1] for key in filtered.rows} == {"SZ000002"}


def test_mid_batch_pg_failure_rolls_back_and_is_reported(source, monkeypatch):
    _, _, start, end = source
    sink = Sink(fail_write=2)
    bind_sink(monkeypatch, sink)
    result = sync.fill_pg_from_parquet(start_date=start, end_date=end, batch_days=100)
    assert result["status"] == "partial"
    assert result["rows"] == 0
    assert result["failed_batches"] == [f"{start}~{end}"]
    assert sink.writes == 2 and sink.rollbacks == 1
    assert not sink.rows and not sink.pending
    assert sink.closed and sink.disposed


def test_duplicate_feature_rows_fail_without_publishing(source, monkeypatch):
    root, _, start, end = source
    path = root / "6_ml_datasets/features_daily" / f"dt={end:%Y%m%d}" / "data.parquet"
    feat = pd.read_parquet(path)
    pd.concat([feat, feat.iloc[:1]], ignore_index=True).to_parquet(path, index=False)
    sink = Sink()
    bind_sink(monkeypatch, sink)
    result = sync.fill_pg_from_parquet(start_date=start, end_date=end, batch_days=100)
    assert result["status"] == "partial"
    assert result["rows"] == 0 and not sink.rows
