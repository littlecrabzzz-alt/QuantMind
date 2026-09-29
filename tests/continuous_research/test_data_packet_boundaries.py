"""Date-boundary regressions using temporary synthetic Parquet files only."""

from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from scripts.continuous_research.data_packets import _bounded


class DataPacketBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "synthetic.parquet"

    def write(self, values, kind=pa.string()):
        pq.write_table(
            pa.table(
                {
                    "day": pa.array(values, type=kind),
                    "payload": list(range(len(values))),
                }
            ),
            self.path,
        )

    def read(self, start="2026-03-23", end="2026-03-24"):
        return _bounded(self.path, "day", start, end, ["day", "payload", "absent"])

    def test_mixed_string_formats_reject_both_sides_before_pandas(self):
        values = [
            "20140101",  # Former ISO branch admitted this compact lower violation.
            "2014-03-22",
            "20140323",
            "2014-03-23",
            "20260324",
            "2026-03-24",
            "20260325",
            "2026-03-25",  # Former compact branch admitted this upper violation.
            "2026-12-31",
            None,
        ]
        for kind in (pa.string(), pa.large_string()):
            with self.subTest(kind=kind):
                self.write(values, kind)
                dataset = ds.dataset(self.path, format="parquet", partitioning=None)
                inspected = []

                class GuardedDataset:
                    schema = dataset.schema

                    def to_table(
                        inner, _dataset=dataset, _inspected=inspected, **kwargs
                    ):
                        self.assertIsNotNone(kwargs.get("filter"))
                        table = _dataset.to_table(**kwargs)
                        _inspected.append(table["payload"].to_pylist())
                        # Assert the Arrow output, before _bounded calls to_pandas.
                        self.assertEqual(_inspected[-1], [2, 3, 4, 5])
                        return table

                with patch("pyarrow.dataset.dataset", return_value=GuardedDataset()):
                    result = self.read("2014-03-23")
                self.assertEqual(inspected, [[2, 3, 4, 5]])
                self.assertEqual(result.payload.tolist(), [2, 3, 4, 5])
                self.assertEqual(result.columns.tolist(), ["day", "payload"])

    def test_invalid_strings_are_not_admitted_as_dates(self):
        self.write(
            [
                "20240229",
                "2024-02-29",
                "20250229",
                "2025-02-29",
                "20260230",
                "2026-02-30",
                "20260010",
                "2026-13-01",
                "2026-03-00",
                "2026-03-24garbage",
                "20260324garbage",
                "2026-3-24",
                "2026032",
                " 20260324",
                "2026-03-24T24:00:00",
                "2026-03-24T23:60:00",
                "2026-03-24T12:00:00+25:00",
                "",
                None,
            ]
        )
        self.assertEqual(self.read("2024-01-01").payload.tolist(), [0, 1])

    def test_iso_times_use_the_declared_calendar_day(self):
        self.write(
            [
                "2026-03-22T23:59:59.999999",
                "2026-03-23T00:00:00",
                "2026-03-24 23:59:59.999999999",
                "2026-03-24T23:59:59Z",
                "2026-03-24T23:59:59-08:00",
                "2026-03-25T00:00:00+08:00",
            ]
        )
        self.assertEqual(self.read().payload.tolist(), [1, 2, 3, 4])

    def test_integer_dates_validate_actual_calendar_days(self):
        self.write(
            [20240229, 20250229, 20260230, 20260323, 20260324, 20260325, None],
            pa.int64(),
        )
        self.assertEqual(self.read("2024-01-01").payload.tolist(), [0, 3, 4])

    def test_typed_date_and_timestamp_boundaries_are_preserved(self):
        days = [date(2026, 3, day) for day in (22, 23, 24, 25)]
        cases = [
            (pa.date32(), days),
            (pa.date64(), days),
            (
                pa.timestamp("us"),
                [
                    datetime(2026, 3, 22, 23, 59, 59, 999999),
                    datetime(2026, 3, 23),
                    datetime(2026, 3, 24, 23, 59, 59, 999999),
                    datetime(2026, 3, 25),
                ],
            ),
        ]
        for kind, values in cases:
            with self.subTest(kind=kind):
                self.write(values + [None], kind)
                self.assertEqual(self.read().payload.tolist(), [1, 2])

    def test_empty_window_does_not_fall_back_to_all_rows(self):
        self.write(["2026-03-25", "20260325", "not-a-date", None])
        self.assertTrue(self.read().empty)

    def test_unsupported_or_absent_date_column_fails(self):
        self.write([20260324.0], pa.float64())
        with self.assertRaisesRegex(ValueError, "Unsupported date type"):
            self.read()
        with self.assertRaisesRegex(ValueError, "Missing date column"):
            _bounded(self.path, "missing", "2026-03-23", "2026-03-24", ["payload"])


if __name__ == "__main__":
    unittest.main()
