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
