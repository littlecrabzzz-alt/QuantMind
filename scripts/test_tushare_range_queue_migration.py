#!/usr/bin/env python3
"""Offline queue-range migration tests; no credentials, network or source calls."""

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
from scripts import tushare_range_queue_migration as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class RangeQueueMigration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        self.config = {
            "history_start": "19900101",
            "supplement_apis": ["moneyflow_dc"],
            "dc_extra_apis": ["dc_member"],
        }
        self.codes = ["000001.SZ", "600001.SH"]
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)

    def old_graph(self, api, day):
        parent = self.pipeline.enqueue(api, {"trade_date": day}, epoch="old")
        pending = self.pipeline.enqueue(
            api, {"trade_date": day, "ts_code": "BK0001.DC"}, epoch="old"
        )
        done = self.pipeline.enqueue(
            api, {"trade_date": day, "ts_code": "BK0002.DC"}, epoch="old"
        )
        self.pipeline.record_partition(
            parent,
            [pending, done],
            "identifier_fanout",
            False,
            {"origin": "fixture", "universe_complete": False},
        )
        result = json.dumps({"api_name": api, "status": "possibly_truncated"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',result=?,tries=1 WHERE id=?",
            (result, parent),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (parent, 1, result)
        )
        done_result = json.dumps({"api_name": api, "status": "sample_ok"})
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=?,tries=1 WHERE id=?",
            (done_result, done),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (done, 1, done_result)
        )
        self.pipeline.db.commit()
        return parent, pending, done

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

    def test_dry_run_is_exact_and_leaves_database_unchanged(self):
        self.old_graph("moneyflow_dc", "20260901")
        before = self.contents()
        report = migration.migrate(
            self.pipeline,
            self.config,
            date(2026, 9, 17),
            self.codes,
            ["moneyflow_dc"],
        )
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["planned_range_jobs"], 4)
        self.assertEqual(report["blocked_result_parents"], 1)
        self.assertEqual(report["superseded_open_children"], 1)
        self.assertEqual(self.contents(), before)

    def test_apply_preserves_results_and_replaces_both_daily_fanouts(self):
        graphs = {
            api: self.old_graph(api, "20260901")
            for api in ("moneyflow_dc", "dc_member")
        }
        unrelated_parent = self.pipeline.enqueue(
            "moneyflow_ths",
            {"start_date": "20260901", "end_date": "20260902"},
            epoch="unrelated",
        )
        unrelated_child = self.pipeline.enqueue(
            "moneyflow_ths",
            {"start_date": "20260901", "end_date": "20260901"},
            epoch="unrelated",
        )
        self.pipeline.record_partition(
            unrelated_parent,
            [unrelated_child],
            "date_bisection",
            True,
            {"origin": "preexisting_fixture"},
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (unrelated_parent,)
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked' WHERE id=?", (unrelated_child,)
        )
        self.pipeline.db.commit()
        attempts = list(self.pipeline.db.execute("SELECT * FROM attempts ORDER BY job_id"))
        results = {
            row["id"]: row["result"]
            for row in self.pipeline.db.execute(
                "SELECT id,result FROM jobs WHERE result IS NOT NULL"
            )
        }
        report = migration.migrate(
            self.pipeline,
            self.config,
            date(2026, 9, 17),
            self.codes,
            ["moneyflow_dc", "dc_member"],
            apply=True,
        )
        self.assertEqual(report["planned_range_jobs"], 22)
        self.assertEqual(report["inserted_range_jobs"], 22)
        self.assertEqual(report["blocked_result_parents"], 2)
        self.assertEqual(report["superseded_open_children"], 2)
        self.assertEqual(report["removed_partition_edges"], 4)
        self.assertEqual(
            report["database_quick_check"],
            "required_on_post_commit_consistent_copy",
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts ORDER BY job_id")],
            [tuple(row) for row in attempts],
        )
        self.assertEqual(
            {
                row["id"]: row["result"]
                for row in self.pipeline.db.execute(
                    "SELECT id,result FROM jobs WHERE result IS NOT NULL"
                )
            },
            results,
        )
        for parent, pending, done in graphs.values():
            states = dict(
                self.pipeline.db.execute(
                    "SELECT id,state FROM jobs WHERE id IN (?,?,?)",
                    (parent, pending, done),
                )
            )
            self.assertEqual(states[parent], "blocked")
            self.assertEqual(states[pending], "superseded")
            self.assertEqual(states[done], "done")
            split = self.pipeline.db.execute(
                "SELECT status,gap FROM partition_splits WHERE parent_id=?", (parent,)
            ).fetchone()
            self.assertEqual(tuple(split), ("blocked", migration.GAP))
            self.assertFalse(
                self.pipeline.db.execute(
                    "SELECT 1 FROM partition_children WHERE parent_id=?", (parent,)
                ).fetchone()
            )
        second = migration.migrate(
            self.pipeline,
            self.config,
            date(2026, 9, 17),
            self.codes,
            ["moneyflow_dc", "dc_member"],
            apply=True,
        )
        self.assertEqual(second["inserted_range_jobs"], 0)
        self.assertEqual(second["old_open_daily_jobs"], 0)

    def test_existing_retired_range_identity_rejects_and_rolls_back(self):
        planned = next(
            migration.planned_jobs(
                self.config,
                date(2026, 9, 17),
                self.codes,
                ["moneyflow_dc"],
            )
        )
        retired = self.pipeline.enqueue(
            planned["api_name"],
            planned["params"],
            planned["priority"],
            planned["epoch"],
            reuse_recent_open=planned["epoch"] != "history",
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked' WHERE id=?", (retired,)
        )
        self.pipeline.db.commit()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "missing or retired"):
            migration.migrate(
                self.pipeline,
                self.config,
                date(2026, 9, 17),
                self.codes,
                ["moneyflow_dc"],
                apply=True,
            )
        self.assertEqual(self.contents(), before)


if __name__ == "__main__":
    unittest.main()
