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
                "SELECT status,gap,evidence FROM partition_splits WHERE parent_id=?", (parent,)
            ).fetchone()
            self.assertEqual(tuple(split)[:2], ("blocked", migration.GAP))
            self.assertEqual(
                json.loads(split["evidence"])["replacement_gap"], migration.GAP
            )
            self.assertFalse(
                self.pipeline.db.execute(
                    "SELECT 1 FROM partition_children WHERE parent_id=?", (parent,)
                ).fetchone()
            )
            self.pipeline.reconcile_partitions(child_id=parent)
            self.assertEqual(
                tuple(
                    self.pipeline.db.execute(
                        "SELECT status,gap FROM partition_splits WHERE parent_id=?",
                        (parent,),
                    ).fetchone()
                ),
                ("blocked", migration.GAP),
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

        for parent, _pending, _done in graphs.values():
            evidence = json.loads(
                self.pipeline.db.execute(
                    "SELECT evidence FROM partition_splits WHERE parent_id=?", (parent,)
                ).fetchone()[0]
            )
            evidence.pop("replacement_gap")
            self.pipeline.db.execute(
                "UPDATE partition_splits SET status='gap',gap='parent_not_split_pending',"
                "evidence=? WHERE parent_id=?",
                (json.dumps(evidence, sort_keys=True), parent),
            )
        self.pipeline.db.commit()
        repair = migration.repair_reconciled_gaps(
            self.pipeline, 2, apply=True
        )
        self.assertEqual(repair["status"], "applied")
        self.assertEqual(repair["restored_markers"], 2)
        self.assertEqual(repair["preserved_result_jobs"], 2)
        self.assertEqual(repair["preserved_attempts"], 2)
        self.assertEqual(
            migration.repair_reconciled_gaps(self.pipeline, 2, apply=True)["status"],
            "no_action",
        )

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

    def test_repair_retires_only_superseded_children_with_range_proof(self):
        day = "20260908"
        parent = self.pipeline.enqueue("dc_member", {"trade_date": day}, epoch="old")
        children = [
            self.pipeline.enqueue(
                "dc_member", {"trade_date": day, "ts_code": code}, epoch="old"
            )
            for code in ("BK0001.DC", "BK0002.DC")
        ]
        self.pipeline.record_partition(
            parent,
            children,
            "identifier_fanout",
            False,
            {"origin": "v4", "universe_complete": False},
        )
        result = json.dumps(
            {
                "api_name": "dc_member",
                "status": "possibly_truncated",
                "row_count": 8000,
            },
            sort_keys=True,
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',tries=1,result=? WHERE id=?",
            (result, parent),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (parent, 1, result)
        )
        self.pipeline.db.executemany(
            "UPDATE jobs SET state='superseded' WHERE id=?",
            [(child,) for child in children],
        )
        for code in self.codes:
            self.pipeline.enqueue(
                "dc_member",
                {
                    "con_code": code,
                    "start_date": "20260701",
                    "end_date": "20260910",
                },
                epoch="history",
            )
        self.pipeline.db.commit()
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "reviewed replacement coverage"):
            migration.repair_reconciled_gaps(
                self.pipeline, 1, expected_retired_edges=2, apply=True
            )
        self.assertEqual(self.contents(), before)
        dry_run = migration.repair_reconciled_gaps(
            self.pipeline,
            1,
            expected_retired_edges=2,
            replacement_counts={"dc_member": 2},
        )
        self.assertEqual(dry_run["status"], "planned_rollback")
        self.assertEqual(dry_run["retired_child_edges"], 2)
        self.assertEqual(self.contents(), before)
        report = migration.repair_reconciled_gaps(
            self.pipeline,
            1,
            expected_retired_edges=2,
            replacement_counts={"dc_member": 2},
            apply=True,
        )
        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["removed_retired_child_edges"], 2)
        self.assertEqual(report["preserved_result_jobs"], 1)
        self.assertEqual(report["preserved_attempts"], 1)
        self.assertFalse(
            self.pipeline.db.execute(
                "SELECT 1 FROM partition_children WHERE parent_id=?", (parent,)
            ).fetchone()
        )
        parent_row = self.pipeline.db.execute(
            "SELECT state,tries,result FROM jobs WHERE id=?", (parent,)
        ).fetchone()
        self.assertEqual(tuple(parent_row), ("blocked", 1, result))
        self.assertEqual(
            dict(
                self.pipeline.db.execute(
                    "SELECT id,state FROM jobs WHERE id IN (?,?)", children
                )
            ),
            dict.fromkeys(children, "superseded"),
        )
        self.pipeline.reconcile_partitions(child_id=parent)
        split = self.pipeline.db.execute(
            "SELECT status,gap,evidence FROM partition_splits WHERE parent_id=?",
            (parent,),
        ).fetchone()
        self.assertEqual((split["status"], split["gap"]), ("blocked", migration.GAP))
        evidence = json.loads(split["evidence"])
        self.assertEqual(evidence["retired_child_edges"], 2)
        self.assertEqual(evidence["replacement_jobs"], 2)
        second = migration.repair_reconciled_gaps(
            self.pipeline,
            1,
            expected_retired_edges=2,
            replacement_counts={"dc_member": 2},
            apply=True,
        )
        self.assertEqual(second["status"], "no_action")
        self.assertEqual(second["removed_retired_child_edges"], 0)


if __name__ == "__main__":
    unittest.main()
