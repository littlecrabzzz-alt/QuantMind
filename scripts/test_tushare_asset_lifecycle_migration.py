#!/usr/bin/env python3
"""Offline index/fund/period lifecycle queue migration tests."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_asset_lifecycle_migration as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class AssetLifecycleMigration(unittest.TestCase):
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
        self.identifiers = {
            "stock_lifecycles": [{"ts_code": "600000.SH", "list_date": "20200115"}],
            "index_lifecycles": [{"ts_code": "000300.SH", "start_date": "20200115"}],
            "fund_lifecycles": [{"ts_code": "000001.OF", "start_date": "20200115"}],
        }

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
            table: [
                tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table}")
            ]
            for table in (
                "jobs",
                "attempts",
                "partition_splits",
                "partition_children",
            )
        }

    def fixture(self):
        ids = {
            "index_pre": self.enqueue(
                "index_daily",
                {
                    "ts_code": "000300.SH",
                    "start_date": "20190101",
                    "end_date": "20191231",
                },
            ),
            "weight_crossing": self.enqueue(
                "index_weight",
                {
                    "index_code": "000300.SH",
                    "start_date": "20200101",
                    "end_date": "20200131",
                },
            ),
            "fund_pre": self.enqueue(
                "fund_nav",
                {
                    "ts_code": "000001.OF",
                    "start_date": "20180101",
                    "end_date": "20181231",
                },
            ),
            "weekly_crossing": self.enqueue(
                "weekly",
                {
                    "ts_code": "600000.SH",
                    "start_date": "20200101",
                    "end_date": "20200131",
                },
            ),
            "monthly_valid": self.enqueue(
                "monthly",
                {
                    "ts_code": "600000.SH",
                    "start_date": "20200201",
                    "end_date": "20200229",
                },
            ),
            "unknown": self.enqueue(
                "index_weekly",
                {
                    "ts_code": "000905.SH",
                    "start_date": "19900101",
                    "end_date": "19991231",
                },
            ),
            "completed": self.enqueue(
                "index_monthly",
                {
                    "ts_code": "000300.SH",
                    "start_date": "19900101",
                    "end_date": "19991231",
                },
                state="done",
            ),
            "split_candidate": self.enqueue(
                "index_daily",
                {
                    "ts_code": "000300.SH",
                    "start_date": "20100101",
                    "end_date": "20101231",
                },
                state="split_pending",
            ),
        }
        ids["active_child"] = self.enqueue(
            "weekly",
            {
                "ts_code": "600000.SH",
                "start_date": "20150101",
                "end_date": "20151231",
            },
        )
        ids["active_parent"] = self.enqueue(
            "weekly",
            {
                "ts_code": "600000.SH",
                "start_date": "20200201",
                "end_date": "20201231",
            },
        )
        self.pipeline.record_partition(
            ids["active_parent"],
            [ids["active_child"]],
            "fixture",
            False,
            {"origin": "test"},
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (ids["active_parent"],)
        )
        attempted = json.dumps({"api_name": "index_daily", "status": "transport_error"})
        self.pipeline.db.execute(
            "UPDATE jobs SET tries=1 WHERE id=?", (ids["index_pre"],)
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (ids["index_pre"], 1, attempted)
        )
        completed = json.dumps({"api_name": "index_monthly", "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET result=?,tries=1 WHERE id=?",
            (completed, ids["completed"]),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (ids["completed"], 1, completed)
        )
        self.pipeline.db.commit()
        return ids

    def test_dry_run_is_exact(self):
        self.fixture()
        before = self.contents()
        report = migration.migrate(self.pipeline, self.identifiers)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["candidate_jobs"], 4)
        self.assertEqual(report["crossing_replacement_jobs"], 2)
        self.assertEqual(report["active_parent_children_preserved"], 1)
        self.assertEqual(report["split_pending_candidates_preserved"], 1)
        self.assertEqual(report["candidate_attempts_preserved"], 1)
        self.assertEqual(self.contents(), before)

    def test_apply_clips_crossings_and_preserves_graph_and_evidence(self):
        ids = self.fixture()
        attempts = [
            tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")
        ]
        graph = [
            tuple(row)
            for row in self.pipeline.db.execute("SELECT * FROM partition_children")
        ]
        report = migration.migrate(self.pipeline, self.identifiers, apply=True)
        self.assertEqual(report["superseded_jobs"], 4)
        states = dict(self.pipeline.db.execute("SELECT id,state FROM jobs"))
        for name in ("index_pre", "weight_crossing", "fund_pre", "weekly_crossing"):
            self.assertEqual(states[ids[name]], "superseded")
        for name in ("monthly_valid", "unknown", "active_child"):
            self.assertEqual(states[ids[name]], "pending")
        for name in ("split_candidate", "active_parent"):
            self.assertEqual(states[ids[name]], "split_pending")
        self.assertEqual(states[ids["completed"]], "done")
        replacements = [
            json.loads(row[0])["params"]
            for row in self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE state='pending' "
                "AND json_extract(job,'$.params.start_date')='20200115'"
            )
        ]
        self.assertEqual(len(replacements), 2)
        self.assertEqual(
            {row.get("index_code", row.get("ts_code")) for row in replacements},
            {"000300.SH", "600000.SH"},
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        self.assertEqual(
            [
                tuple(row)
                for row in self.pipeline.db.execute("SELECT * FROM partition_children")
            ],
            graph,
        )
        second = migration.migrate(self.pipeline, self.identifiers, apply=True)
        self.assertEqual(second["candidate_jobs"], 0)
        self.assertEqual(second["inserted_replacement_jobs"], 0)

    def test_malformed_lifecycle_refuses_without_changes(self):
        self.fixture()
        before = self.contents()
        malformed = {**self.identifiers, "fund_lifecycles": "not-a-list"}
        with self.assertRaises(ValueError):
            migration.migrate(self.pipeline, malformed, apply=True)
        self.assertEqual(self.contents(), before)


if __name__ == "__main__":
    unittest.main()
