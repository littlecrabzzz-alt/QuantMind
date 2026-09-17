#!/usr/bin/env python3
"""Offline factor legacy-day retirement tests; no credentials or network."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_factor_daily_retirement as retirement  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class FactorDailyRetirement(unittest.TestCase):
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
        return self.pipeline.enqueue("factor_value", params, 55, epoch)

    def snapshot(self):
        return {
            table: [tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table}")]
            for table in ("jobs", "attempts", "partition_splits", "partition_children")
        }

    def covered_fixture(self):
        range_id = self.enqueue(
            {"ts_code": "000001.SZ", "start_date": "20260101", "end_date": "20260131"}
        )
        daily_id = self.enqueue({"ts_code": "000001.SZ", "trade_date": "20260105"})
        result = json.dumps({"api_name": "factor_value", "status": "transport_error"})
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (daily_id,))
        self.pipeline.db.execute("INSERT INTO attempts VALUES(?,?,?)", (daily_id, 1, result))
        completed_id = self.enqueue({"ts_code": "000001.SZ", "trade_date": "20260106"})
        completed_result = json.dumps({"api_name": "factor_value", "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=?,tries=1 WHERE id=?",
            (completed_result, completed_id),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (completed_id, 1, completed_result)
        )
        recent_id = self.enqueue(
            {"ts_code": "000001.SZ", "trade_date": "20260917"}, "20260917"
        )
        self.pipeline.db.commit()
        return range_id, daily_id, completed_id, recent_id

    def test_dry_run_is_exact(self):
        self.covered_fixture()
        before = self.snapshot()
        report = retirement.migrate(self.pipeline)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["covered_history_days"], 1)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_apply_only_retires_covered_pending_history_days(self):
        range_id, daily_id, completed_id, recent_id = self.covered_fixture()
        before_attempts = list(self.pipeline.db.execute("SELECT * FROM attempts"))
        report = retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(report["superseded_history_days"], 1)
        states = dict(
            self.pipeline.db.execute(
                "SELECT id,state FROM jobs WHERE id IN (?,?,?,?)",
                (range_id, daily_id, completed_id, recent_id),
            )
        )
        self.assertEqual(states[range_id], "pending")
        self.assertEqual(states[daily_id], "superseded")
        self.assertEqual(states[completed_id], "done")
        self.assertEqual(states[recent_id], "pending")
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            [tuple(row) for row in before_attempts],
        )
        second = retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(second["old_open_history_days"], 0)

    def test_uncovered_day_refuses_without_changes(self):
        self.enqueue({"ts_code": "000001.SZ", "trade_date": "20260201"})
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack matching usable range coverage"):
            retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_retired_range_does_not_count_as_coverage(self):
        range_id = self.enqueue(
            {"ts_code": "000001.SZ", "start_date": "20260101", "end_date": "20260131"}
        )
        self.pipeline.db.execute("UPDATE jobs SET state='blocked' WHERE id=?", (range_id,))
        self.enqueue({"ts_code": "000001.SZ", "trade_date": "20260105"})
        self.pipeline.db.commit()
        with self.assertRaisesRegex(ValueError, "lack matching usable range coverage"):
            retirement.migrate(self.pipeline, apply=True)

    def test_active_parent_reference_refuses(self):
        self.covered_fixture()
        daily_id = self.pipeline.db.execute(
            "SELECT id FROM jobs WHERE state='pending' AND epoch='history' "
            "AND json_type(job,'$.params.trade_date')='text'"
        ).fetchone()[0]
        parent = self.pipeline.enqueue(
            "factor_value",
            {"ts_code": "000001.SZ", "start_date": "20260101", "end_date": "20260110"},
            55,
            "history",
        )
        self.pipeline.record_partition(
            parent, [daily_id], "fixture", False, {"origin": "test"}
        )
        self.pipeline.db.execute("UPDATE jobs SET state='split_pending' WHERE id=?", (parent,))
        self.pipeline.db.commit()
        with self.assertRaisesRegex(ValueError, "shared by active split parents"):
            retirement.migrate(self.pipeline, apply=True)


if __name__ == "__main__":
    unittest.main()
