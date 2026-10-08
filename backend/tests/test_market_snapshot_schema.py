"""Daily snapshots need only the common price schema across providers."""
from pathlib import Path
import tempfile
import duckdb
from backend.scripts.market_snapshot.schema_adapter import get_conn


def test_daily_views_without_provider_specific_columns():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with duckdb.connect() as writer:
            for dataset in ("daily_unadjusted", "index_daily"):
                partition = root / "1_kline_data" / dataset / "dt=20260918"
                partition.mkdir(parents=True)
                writer.execute(f"""COPY (SELECT '000001.SZ' AS symbol,
                    '2026-09-18' AS time, 10.0 AS open, 11.0 AS high,
                    9.0 AS low, 10.5 AS close, 100 AS volume, 1050 AS amount)
                    TO '{partition / 'data.parquet'}' (FORMAT PARQUET)""")
        with get_conn(root) as con:
            for dataset in ("daily_unadjusted", "index_daily"):
                assert con.execute(f"SELECT close, amount FROM qdb_{dataset}").fetchone() == (10.5, 1050)


if __name__ == "__main__":
    test_daily_views_without_provider_specific_columns()


def test_technical_views_keep_missing_past_returns_null(tmp_path):
    partition = tmp_path / "5_technical_derived/technical_indicators/dt=20261008"
    partition.mkdir(parents=True)
    with duckdb.connect() as writer:
        writer.execute(f"""COPY (SELECT '000001.SZ' AS symbol,
            '2026-10-08' AS time, 10.5 AS close, 1.25 AS pct_change,
            999.0 AS future_return_1d, 999.0 AS future_return_20d)
            TO '{partition / "data.parquet"}' (FORMAT PARQUET)""")
    with get_conn(tmp_path) as con:
        assert con.execute("""SELECT symbol, close, pct_change,
            return_1d, return_3d, return_5d, return_10d, return_20d, return_60d
            FROM qdb_technical_indicators""").fetchone() == (
            "000001.SZ", 10.5, 1.25, None, None, None, None, None, None
        )


def test_technical_views_preserve_past_returns_across_schema_change(tmp_path):
    with duckdb.connect() as writer:
        for day, extra in (("20261007", "2.5 AS return_1d"),
                           ("20261008", "999.0 AS future_return_1d")):
            partition = tmp_path / "5_technical_derived/technical_indicators" / f"dt={day}"
            partition.mkdir(parents=True)
            writer.execute(f"""COPY (SELECT '000001.SZ' AS "Symbol",
                '{day}' AS time, 10.5 AS close, 1.25 AS pct_change, {extra})
                TO '{partition / "data.parquet"}' (FORMAT PARQUET)""")
    with get_conn(tmp_path) as con:
        assert con.execute("""SELECT time, return_1d, return_20d
            FROM qdb_technical_indicators ORDER BY time""").fetchall() == [
            ("20261007", 2.5, None), ("20261008", None, None)
        ]
