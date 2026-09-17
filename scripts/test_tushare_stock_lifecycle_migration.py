#!/usr/bin/env python3
"""Offline listing-date queue migration tests; no credentials or network."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_stock_lifecycle_migration as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class StockLifecycleMigration(unittest.TestCase):
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
        self.lifecycles = [
            {"ts_code": "000001.SZ", "list_date": "20200115"},
            {"ts_code": "T600018.SH", "list_date": None},
        ]

    def enqueue(self, api, params, *, epoch="history", state=None):
        job_id = self.pipeline.enqueue(api, params, 55, epoch)
        if state:
            self.pipeline.db.execute(
                "UPDATE jobs SET state=? WHERE id=?", (state, job_id)
            )
        self.pipeline.db.commit()
        return job_id

    def contents(self):
        return {
            table: [tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table}")]
            for table in (
                "jobs",
                "attempts",
                "partition_splits",
                "partition_children",
            )
        }

    def fixture(self):
        ids = {
            "factor_day": self.enqueue(
                "factor_value", {"ts_code": "000001.SZ", "trade_date": "20200101"}
            ),
            "factor_range": self.enqueue(
                "factor_value",
                {
                    "ts_code": "000001.SZ",
                    "start_date": "20191201",
                    "end_date": "20191231",
                },
            ),
            "factor_crossing": self.enqueue(
                "factor_value",
                {
                    "ts_code": "000001.SZ",
                    "start_date": "20200101",
                    "end_date": "20200131",
                },
            ),
            "cyq_day": self.enqueue(
                "cyq_perf",
                {"ts_code": "000001.SZ", "trade_date": "20200102"},
                epoch="20260917",
            ),
            "cyq_range": self.enqueue(
                "cyq_chips",
                {
                    "ts_code": "000001.SZ",
                    "start_date": "20190101",
                    "end_date": "20190131",
                },
            ),
            "unknown": self.enqueue(
                "cyq_perf",
                {
                    "ts_code": "T600018.SH",
                    "start_date": "20190101",
                    "end_date": "20190131",
                },
            ),
            "valid": self.enqueue(
                "cyq_chips",
                {"ts_code": "000001.SZ", "trade_date": "20200115"},
            ),
            "completed": self.enqueue(
                "factor_value",
                {"ts_code": "000001.SZ", "trade_date": "20180101"},
                state="done",
            ),
        }
        result = json.dumps({"api_name": "factor_value", "status": "transport_error"})
        self.pipeline.db.execute(
            "UPDATE jobs SET tries=1 WHERE id=?", (ids["factor_day"],)
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (ids["factor_day"], 1, result)
        )
        completed_result = json.dumps(
            {"api_name": "factor_value", "status": "sample_ok"}
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET result=?,tries=1 WHERE id=?",
            (completed_result, ids["completed"]),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            (ids["completed"], 1, completed_result),
        )
        self.pipeline.db.commit()
        return ids

    def test_dry_run_is_exact(self):
        self.fixture()
        before = self.contents()
        report = migration.migrate(self.pipeline, self.lifecycles)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["candidate_jobs"], 5)
        self.assertEqual(report["crossing_replacement_jobs"], 1)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(self.contents(), before)

    def test_apply_clips_crossing_and_preserves_unknown_completed_and_attempts(self):
        ids = self.fixture()
        attempts = [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")]
        report = migration.migrate(self.pipeline, self.lifecycles, apply=True)
        self.assertEqual(report["superseded_jobs"], 5)
        self.assertEqual(report["inserted_replacement_jobs"], 1)
        states = dict(self.pipeline.db.execute("SELECT id,state FROM jobs"))
        for name in ("factor_day", "factor_range", "factor_crossing", "cyq_day", "cyq_range"):
            self.assertEqual(states[ids[name]], "superseded")
        self.assertEqual(states[ids["unknown"]], "pending")
        self.assertEqual(states[ids["valid"]], "pending")
        self.assertEqual(states[ids["completed"]], "done")
        replacement = self.pipeline.db.execute(
            "SELECT job,state FROM jobs WHERE state='pending' "
            "AND json_extract(job,'$.api_name')='factor_value' "
            "AND json_extract(job,'$.params.start_date')='20200115'"
        ).fetchone()
        self.assertIsNotNone(replacement)
        self.assertEqual(
            json.loads(replacement["job"])["params"],
            {
                "ts_code": "000001.SZ",
                "start_date": "20200115",
                "end_date": "20200131",
            },
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        second = migration.migrate(self.pipeline, self.lifecycles, apply=True)
        self.assertEqual(second["candidate_jobs"], 0)
        self.assertEqual(second["inserted_replacement_jobs"], 0)

    def test_split_pending_candidate_refuses_without_changes(self):
        self.enqueue(
            "cyq_perf",
            {"ts_code": "000001.SZ", "trade_date": "20190101"},
            state="split_pending",
        )
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "split_pending"):
            migration.migrate(self.pipeline, self.lifecycles, apply=True)
        self.assertEqual(self.contents(), before)

    def test_active_parent_reference_refuses_without_changes(self):
        child = self.enqueue(
            "factor_value",
            {"ts_code": "000001.SZ", "trade_date": "20190101"},
        )
        parent = self.enqueue(
            "factor_value",
            {
                "ts_code": "000001.SZ",
                "start_date": "20200201",
                "end_date": "20200229",
            },
        )
        self.pipeline.record_partition(
            parent, [child], "fixture", False, {"origin": "test"}
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (parent,)
        )
        self.pipeline.db.commit()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "active split parents"):
            migration.migrate(self.pipeline, self.lifecycles, apply=True)
        self.assertEqual(self.contents(), before)

    def test_malformed_lifecycle_refuses_without_changes(self):
        self.fixture()
        before = self.contents()
        for lifecycle in (
            [{"ts_code": "bad", "list_date": "20200101"}],
            [{"ts_code": "000001.SZ", "list_date": "20200230"}],
            "not-a-list",
        ):
            with self.subTest(lifecycle=lifecycle), self.assertRaises(ValueError):
                migration.migrate(self.pipeline, lifecycle, apply=True)
            self.assertEqual(self.contents(), before)


if __name__ == "__main__":
    unittest.main()
