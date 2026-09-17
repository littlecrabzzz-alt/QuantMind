#!/usr/bin/env python3
"""Offline TDX-member daily-to-range migration tests; no network."""

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
from scripts import tushare_tdx_member_daily_retirement as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
CONFIG = {
    "enable_market_sentiment": True,
    "market_sentiment_apis": [
        "tdx_index",
        "tdx_daily",
        "kpl_list",
        "ths_hot",
        "dc_hot",
    ],
    "market_members_apis": ["tdx_member", "kpl_concept_cons"],
    "market_members_history_start": {"tdx_member": "20260101"},
}
TODAY = date(2026, 1, 10)


class TdxMemberDailyRetirement(unittest.TestCase):
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
        return self.pipeline.enqueue("tdx_member", params, 55, epoch)

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
        bulk = self.enqueue({"trade_date": "20260101"})
        board = self.enqueue({"trade_date": "20260103", "ts_code": "880206.TDX"})
        attempt = json.dumps({"api_name": "tdx_member", "status": "transport_error"})
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (bulk,))
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (bulk, 1, attempt)
        )
        completed = self.enqueue({"trade_date": "20260102"})
        result = json.dumps({"api_name": "tdx_member", "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=?,tries=1 WHERE id=?",
            (result, completed),
        )
        recent = self.enqueue({"trade_date": "20260109"}, "20260110")
        terminal = self.enqueue({"trade_date": "20260101", "con_code": "000001.SZ"})
        self.pipeline.db.execute(
            "INSERT INTO planning_state(name,anchor,signature,offset,done) "
            "VALUES('history:market_members','old','{}',99,0)"
        )
        self.pipeline.db.commit()
        return bulk, board, completed, recent, terminal

    def test_rollback_validation_is_exact_and_non_mutating(self):
        self.fixture()
        before = self.snapshot()
        report = migration.migrate(self.pipeline, CONFIG, TODAY)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["planned_range_jobs"], 1)
        self.assertEqual(report["inserted_range_jobs"], 1)
        self.assertEqual(report["covered_history_daily_jobs"], 2)
        self.assertEqual(report["old_open_history_bulk_jobs"], 1)
        self.assertEqual(report["old_open_history_board_jobs"], 1)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(report["history_planning_states_reset"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_apply_retires_only_covered_open_roots(self):
        bulk, board, completed, recent, terminal = self.fixture()
        attempts = [
            tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")
        ]
        report = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(report["superseded_history_daily_jobs"], 2)
        states = dict(
            self.pipeline.db.execute(
                "SELECT id,state FROM jobs WHERE id IN (?,?,?,?,?)",
                (bulk, board, completed, recent, terminal),
            )
        )
        self.assertEqual(states[bulk], "superseded")
        self.assertEqual(states[board], "superseded")
        self.assertEqual(states[completed], "done")
        self.assertEqual(states[recent], "pending")
        self.assertEqual(states[terminal], "pending")
        self.assertIsNone(
            self.pipeline.db.execute(
                "SELECT 1 FROM planning_state WHERE name='history:market_members'"
            ).fetchone()
        )
        ranges = [
            json.loads(row[0])["params"]
            for row in self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE epoch='history' "
                "AND json_extract(job,'$.api_name')='tdx_member' "
                "AND json_type(job,'$.params.start_date')='text'"
            )
        ]
        self.assertEqual(
            ranges,
            [{"end_date": "20260103", "start_date": "20260101"}],
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        second = migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(second["old_open_history_daily_jobs"], 0)
        self.assertEqual(second["inserted_range_jobs"], 0)

    def test_uncovered_day_aborts_without_changes(self):
        self.enqueue({"trade_date": "20251231", "ts_code": "880206.TDX"})
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack matching range coverage"):
            migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_active_parent_reference_aborts(self):
        child = self.enqueue({"trade_date": "20260101", "ts_code": "880206.TDX"})
        parent = self.enqueue({"start_date": "20260101", "end_date": "20260103"})
        self.pipeline.record_partition(
            parent, [child], "identifier_fanout", False, {"origin": "test"}
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (parent,)
        )
        self.pipeline.db.commit()
        with self.assertRaisesRegex(ValueError, "shared by active split parents"):
            migration.migrate(self.pipeline, CONFIG, TODAY, apply=True)


if __name__ == "__main__":
    unittest.main()
