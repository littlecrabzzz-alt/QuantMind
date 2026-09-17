#!/usr/bin/env python3
"""Offline proof for conservative legacy index period replacement."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_index_period_replacement as replacement  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class IndexPeriodReplacement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)
        self.day = "20260903"
        self.epoch = "period-20260906"
        self.parent = self.pipeline.enqueue(
            "index_weekly", {"trade_date": self.day}, epoch="legacy"
        )
        result = {
            "api_name": "index_weekly",
            "status": "possibly_truncated",
            "row_count": 1000,
            "split": {
                "method": "identifier_fanout",
                "children": 2,
                "universe_complete": False,
            },
        }
        encoded = json.dumps(result, sort_keys=True)
        self.legacy_result = encoded
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',tries=1,result=? WHERE id=?",
            (encoded, self.parent),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (self.parent, 1, encoded)
        )
        self.pipeline.db.execute(
            "INSERT INTO partition_splits VALUES(?,?,'0','0',?,'gap',?)",
            (
                self.parent,
                "identifier_fanout",
                json.dumps({"origin": "legacy_unverified"}),
                "legacy_relationship_unverified",
            ),
        )
        for code in ("000001.SH", "399001.SZ"):
            self.pipeline.enqueue(
                "index_weekly",
                {
                    "ts_code": code,
                    "start_date": "20260824",
                    "end_date": "20260906",
                },
                epoch=self.epoch,
            )
        self.pipeline.db.commit()

    def snapshot(self):
        return {
            table: [
                tuple(row)
                for row in self.pipeline.db.execute(f"SELECT * FROM {table}")
            ]
            for table in ("jobs", "attempts", "partition_splits", "partition_children")
        }

    def test_dry_run_apply_and_reconcile_are_evidence_preserving(self):
        before = self.snapshot()
        report = replacement.retire(
            self.pipeline, self.parent, self.epoch, self.day, 2
        )
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(self.snapshot(), before)
        report = replacement.retire(
            self.pipeline, self.parent, self.epoch, self.day, 2, apply=True
        )
        self.assertEqual(report["status"], "applied")
        self.assertFalse(report["replacement_data_complete"])
        self.assertEqual(report["upstream_calls"], 0)
        row = self.pipeline.db.execute(
            "SELECT state,tries,result FROM jobs WHERE id=?", (self.parent,)
        ).fetchone()
        self.assertEqual(
            (row["state"], row["tries"], row["result"]),
            ("blocked", 1, self.legacy_result),
        )
        split = self.pipeline.db.execute(
            "SELECT status,gap,evidence FROM partition_splits WHERE parent_id=?",
            (self.parent,),
        ).fetchone()
        self.assertEqual((split["status"], split["gap"]), ("blocked", replacement.GAP))
        self.assertEqual(json.loads(split["evidence"])["replacement_jobs"], 2)
        self.pipeline.reconcile_partitions(child_id=self.parent)
        self.assertEqual(
            tuple(
                self.pipeline.db.execute(
                    "SELECT state,tries,result FROM jobs WHERE id=?", (self.parent,)
                ).fetchone()
            ),
            ("blocked", 1, self.legacy_result),
        )
        self.assertEqual(
            replacement.retire(
                self.pipeline, self.parent, self.epoch, self.day, 2, apply=True
            )["status"],
            "no_action",
        )

    def test_requires_exact_unique_replacement_inventory(self):
        with self.assertRaisesRegex(ValueError, "Expected 3 unique"):
            replacement.retire(
                self.pipeline, self.parent, self.epoch, self.day, 3, apply=True
            )
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (self.parent,)
            ).fetchone()[0],
            "split_pending",
        )


if __name__ == "__main__":
    unittest.main()
