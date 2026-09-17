#!/usr/bin/env python3
"""Offline daily_info/dc_daily history range migration tests."""

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
from scripts import tushare_low_volume_daily_retirement as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
CONFIG = {
    "listing_extra_apis": ["daily_info"],
    "listing_extra_history_start": "20260101",
    "dc_extra_apis": ["dc_daily"],
    "dc_extra_history_start": "20260101",
}
TODAY = date(2026, 1, 10)


class LowVolumeDailyRetirement(unittest.TestCase):
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

    def enqueue(self, api, params, epoch="history"):
        return self.pipeline.enqueue(api, params, 55, epoch)

    def snapshot(self):
        return {
            table: [
                tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table}")
            ]
            for table in (
                "jobs",
                "attempts",
                "partition_splits",
                "partition_children",
                "planning_state",
            )
        }

    def fixture(self):
        daily_info = self.enqueue("daily_info", {"trade_date": "20260101"})
        dc_daily = self.enqueue(
            "dc_daily", {"trade_date": "20260102", "idx_type": "行业板块"}
        )
        attempt = json.dumps({"api_name": "daily_info", "status": "transport_error"})
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (daily_info,))
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (daily_info, 1, attempt)
        )
        completed = self.enqueue("daily_info", {"trade_date": "20260103"})
        result = json.dumps({"api_name": "daily_info", "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=?,tries=1 WHERE id=?",
            (result, completed),
        )
        recent = self.enqueue("daily_info", {"trade_date": "20260109"}, "20260110")
        unrelated = self.enqueue("suspend_d", {"trade_date": "20260101"})
        for name in migration.PLANNING_STATES:
            self.pipeline.db.execute(
                "INSERT INTO planning_state(name,anchor,signature,offset,done) "
                "VALUES(?, 'old', '{}', 99, 0)",
                (name,),
            )
        self.pipeline.db.commit()
        return daily_info, dc_daily, completed, recent, unrelated

    def test_snapshot_validation_rolls_back_every_change(self):
        self.fixture()
        before = self.snapshot()
        report = migration.migrate(self.pipeline, CONFIG, TODAY)
        self.assertEqual(report["status"], "snapshot_validation_rollback")
        self.assertEqual(report["planned_range_jobs"], 4)
        self.assertEqual(report["planned_range_jobs_by_api"], {"daily_info": 1, "dc_daily": 3})
        self.assertEqual(report["covered_history_daily_jobs"], 2)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(report["history_planning_states_reset"], 2)
        self.assertEqual(self.snapshot(), before)

    def test_apply_retires_only_exact_pending_history_days(self):
        daily_info, dc_daily, completed, recent, unrelated = self.fixture()
        attempts = [
            tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")
        ]
        report = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(report["superseded_history_daily_jobs"], 2)
        states = dict(
            self.pipeline.db.execute(
                "SELECT id,state FROM jobs WHERE id IN (?,?,?,?,?)",
                (daily_info, dc_daily, completed, recent, unrelated),
            )
        )
        self.assertEqual(states[daily_info], "superseded")
        self.assertEqual(states[dc_daily], "superseded")
        self.assertEqual(states[completed], "done")
        self.assertEqual(states[recent], "pending")
        self.assertEqual(states[unrelated], "pending")
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT count(*) FROM planning_state WHERE name IN (?,?)",
                migration.PLANNING_STATES,
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        second = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(second["old_open_history_daily_jobs"], 0)
        self.assertEqual(second["inserted_range_jobs"], 0)

    def test_uncovered_day_aborts_without_changes(self):
        self.enqueue("daily_info", {"trade_date": "20251231"})
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack one matching range coverage"):
            migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_active_parent_reference_aborts(self):
        child = self.enqueue("daily_info", {"trade_date": "20260101"})
        parent = self.enqueue(
            "daily_info", {"start_date": "20260101", "end_date": "20260103"}
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
