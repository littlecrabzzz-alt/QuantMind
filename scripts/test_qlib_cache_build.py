"""Isolated real Parquet build, bounded reads, and failed-publication recovery."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.engine.qlib_data_builder import QlibDataBuilder, _symbol_frames


class Hub:
    UNIVERSE_MAP = {}
    available = True

    def __init__(self, root):
        self.data_dir = root
        self.dates = pd.bdate_range("2024-01-01", periods=400)
        self.symbols = [f"{600000 + i}.SH" for i in range(32)]

    def fetch_calendar(self):
        return pd.DataFrame({"trade_date": self.dates})

    def fetch_stock_list(self):
        return pd.DataFrame({"symbol": self.symbols})

    def fetch_index_kline(self, *args):
        return pd.DataFrame()

    def write_data(self):
        data = pd.DataFrame(
            {
                "symbol": np.repeat(self.symbols, len(self.dates)),
                "time": np.tile(self.dates, len(self.symbols)),
            }
        )
        data["close"] = 10.0 + np.arange(len(data)) / 10000
        for field in ("open", "high", "low"):
            data[field] = data.close
        data["volume"] = 100.0
        data["amount"] = data.volume * data.close
        for name in ("daily_backward", "daily_unadjusted", "daily_forward"):
            path = self.data_dir / "1_kline_data" / name / "dt=fixture/data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = data.copy()
            if name == "daily_backward":
                frame[["open", "high", "low", "close"]] *= 2
            frame.to_parquet(path, index=False)


def content(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


class Build(unittest.TestCase):
    def test_streaming_matches_previous_math_and_failure_keeps_old_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hub = Hub(root / "input")
            hub.write_data()
            live = root / "live"
            builder = QlibDataBuilder(hub, live)
            with patch.object(builder, "_multiplicative_factor", return_value=None):
                result = builder.build_all()
            self.assertEqual(result["features"], 32)
            expected = content(live)
            with self.assertRaisesRegex(ValueError, "separate output"):
                builder.build_all(symbols=["sh600000"])
            for i in range(32):
                base = np.asarray(
                    10.0 + (i * 400 + np.arange(400)) / 10000, dtype=np.float32
                )
                directory = live / "features" / f"sh{600000 + i}"
                close = np.fromfile(directory / "close.day.bin", dtype="<f4")
                factor = np.fromfile(directory / "factor.day.bin", dtype="<f4")
                np.testing.assert_allclose(close[1:] / factor[1:], base, rtol=1e-6)
                self.assertEqual(close[0], 0)
                self.assertEqual(len(close), 401)
            hub.dates = pd.bdate_range("2024-01-01", periods=401)
            hub.write_data()
            with (
                patch.object(
                    builder,
                    "_write_bin_file",
                    side_effect=OSError("disk write failure"),
                ),
                patch.object(builder, "_multiplicative_factor", return_value=None),
            ):
                with self.assertRaises(RuntimeError):
                    builder.build_all()
            self.assertEqual(content(live), expected)
            with patch.object(builder, "_multiplicative_factor", return_value=None):
                builder.build_all()
            self.assertEqual(
                (live / "calendars/day.txt").read_text().splitlines()[-1],
                str(hub.dates[-1].date()),
            )
            self.assertFalse(list(root.glob(".live-build-*")))
            hub.dates = pd.bdate_range(
                "2024-01-01", periods=402
            )  # calendar ahead of actual data
            before = content(live)
            with patch.object(builder, "_multiplicative_factor", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "do not reach"):
                    builder.build_all()
            self.assertEqual(content(live), before)

    def test_fresh_index_does_not_mask_stale_stocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hub = Hub(root / "input")
            b = QlibDataBuilder(hub, root / "cache")
            (b.qlib_dir / "calendars").mkdir(parents=True)
            (b.qlib_dir / "calendars/day.txt").write_text("2024-01-01\n2024-01-02\n")
            (b.qlib_dir / "instruments").mkdir()
            (b.qlib_dir / "instruments/all.txt").write_text("sh600000\nsh000300\n")
            for name, index in [("sh600000", 0), ("sh000300", 1)]:
                target = b.qlib_dir / "features" / name
                target.mkdir(parents=True)
                for field in [
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "factor",
                    "change",
                ]:
                    b._write_bin_file(
                        target / (field + ".day.bin"),
                        index,
                        np.array([1.0], dtype=np.float32),
                    )
            with self.assertRaisesRegex(RuntimeError, "do not reach"):
                b._validate_generation()

    def test_chunk_boundaries_preserve_complete_symbols(self):
        frame = pd.DataFrame(
            {
                "symbol": ["a"] * 9000 + ["b"] * 300 + ["c"] * 9500,
                "value": np.arange(18800),
            }
        )

        class Cursor:
            offset = 0

            def fetch_df_chunk(self, vectors):
                self.offset += 8192
                return frame.iloc[self.offset - 8192 : self.offset].copy()

            def fetchdf(self):
                raise AssertionError("unbounded fetch is forbidden")

        groups = list(_symbol_frames(Cursor()))
        self.assertEqual([len(g) for _, g in groups], [9000, 300, 9500])
        self.assertEqual(
            pd.concat([g for _, g in groups]).value.tolist(), frame.value.tolist()
        )

    def test_noncn_and_index_calendar_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hub = Hub(root / "input")
            hub.write_data()
            builder = QlibDataBuilder(hub, root / "us", market="US")
            builder.build_all()
            self.assertTrue((root / "us/features/us_600000.sh/close.day.bin").is_file())
            index = QlibDataBuilder(hub, root / "index")
            dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
            source = pd.DataFrame(
                {
                    "trade_date": [dates[0], dates[2]],
                    **{
                        k: [10.0, 12.0]
                        for k in ["open", "high", "low", "close", "volume", "amount"]
                    },
                }
            )
            # The real bounded index reader must avoid mounting unrelated views.
            from backend.services.engine.data_platform.quantdb_hub import QuantDBDataHub

            index_file = (
                hub.data_dir / "1_kline_data/index_daily/dt=20240101/data.parquet"
            )
            index_file.parent.mkdir(parents=True)
            index_rows = source.rename(columns={"trade_date": "time"}).assign(
                symbol="000300.SH"
            )
            index_rows.iloc[:1].assign(release_id="fixture").to_parquet(
                index_file, index=False
            )
            second = index_file.parent.parent / "dt=20240103/data.parquet"
            second.parent.mkdir()
            index_rows.iloc[1:].to_parquet(second, index=False)
            reader = QuantDBDataHub(
                hub.data_dir, duckdb_config={"memory_limit": "64MB", "threads": "1"}
            )
            from datetime import date

            with patch.object(
                reader, "_mount_views", side_effect=AssertionError("unrelated views")
            ):
                self.assertEqual(
                    len(
                        reader.fetch_index_kline(
                            "000300.SH", date(2024, 1, 1), date(2024, 1, 3)
                        )
                    ),
                    2,
                )
            out = root / "index/features/sh000300"
            out.mkdir(parents=True)
            with patch.object(hub, "fetch_index_kline", return_value=source):
                index._build_index_features(
                    "sh000300", "000300.SH", out, dates, dict(zip(dates, range(3), strict=True))
                )
            raw = np.fromfile(out / "close.day.bin", dtype="<f4")
            np.testing.assert_allclose(raw, [0, 10, np.nan, 12], equal_nan=True)


if __name__ == "__main__":
    unittest.main()
