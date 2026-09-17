#!/usr/bin/env python3
"""Offline KPL daily-to-range migration tests; no credentials or network."""

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_kpl_daily_retirement as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
CONFIG = {
    "market_sentiment_history_start": {"kpl_list": "20260101"},
}
TODAY = date(2026, 1, 10)


class KplDailyRetirement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)

    def enqueue(self, params, epoch="history"):
        return self.pipeline.enqueue("kpl_list", params, 55, epoch)

    def snapshot(self):
        return {
            table: [tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table}")]
            for table in ("jobs", "attempts", "partition_splits", "partition_children")
        }

    def fixture(self):
        first = self.enqueue({"trade_date": "20260101", "tag": "涨停"})
        second = self.enqueue({"trade_date": "20260103", "tag": "炸板"})
        attempt = json.dumps({"api_name": "kpl_list", "status": "transport_error"})
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (first,))
        self.pipeline.db.execute("INSERT INTO attempts VALUES(?,?,?)", (first, 1, attempt))
        completed = self.enqueue({"trade_date": "20260102", "tag": "涨停"})
        result = json.dumps({"api_name": "kpl_list", "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=?,tries=1 WHERE id=?",
            (result, completed),
        )
        recent = self.enqueue(
            {"trade_date": "20260109", "tag": "涨停"}, "20260110"
        )
        child = self.enqueue(
            {"trade_date": "20260101", "tag": "涨停", "ts_code": "000001.SZ"}
        )
        self.pipeline.db.commit()
        return first, second, completed, recent, child

    def test_dry_run_is_exact_and_non_mutating(self):
        self.fixture()
        before = self.snapshot()
        report = migration.migrate(self.pipeline, CONFIG, TODAY)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["planned_range_jobs"], 5)
        self.assertEqual(report["inserted_range_jobs"], 5)
        self.assertEqual(report["covered_history_days"], 2)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_apply_retires_only_covered_open_roots(self):
        first, second, completed, recent, child = self.fixture()
        attempts = [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")]
        report = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(report["superseded_history_days"], 2)
        states = dict(
            self.pipeline.db.execute(
                "SELECT id,state FROM jobs WHERE id IN (?,?,?,?,?)",
                (first, second, completed, recent, child),
            )
        )
        self.assertEqual(states[first], "superseded")
        self.assertEqual(states[second], "superseded")
        self.assertEqual(states[completed], "done")
        self.assertEqual(states[recent], "pending")
        self.assertEqual(states[child], "pending")
        ranges = [
            json.loads(row[0])["params"]
            for row in self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE epoch='history' "
                "AND json_extract(job,'$.api_name')='kpl_list' "
                "AND json_type(job,'$.params.start_date')='text'"
            )
        ]
        self.assertEqual(len(ranges), 5)
        self.assertEqual(
            {(row["start_date"], row["end_date"]) for row in ranges},
            {("20260101", "20260103")},
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        second_run = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(second_run["old_open_history_days"], 0)
        self.assertEqual(second_run["inserted_range_jobs"], 0)

    def test_uncovered_day_aborts_without_changes(self):
        self.enqueue({"trade_date": "20251231", "tag": "涨停"})
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack matching range coverage"):
            migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_active_parent_reference_aborts(self):
        child = self.enqueue({"trade_date": "20260101", "tag": "涨停"})
        parent = self.enqueue(
            {"start_date": "20260101", "end_date": "20260103", "tag": "涨停"}
        )
        self.pipeline.record_partition(
            parent, [child], "date_bisection", True, {"origin": "test"}
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (parent,)
        )
        self.pipeline.db.commit()
        with self.assertRaisesRegex(ValueError, "shared by active split parents"):
            migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)


if __name__ == "__main__":
    unittest.main()
