"""Exact prepared-batch priority changes preserve all durable task state."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_tushare_rrg_acquisition_shard as importer
import prioritize_tushare_acquisition_batch as module
import test_tushare_rrg_acquisition_importer as fixture


class AcquisitionBatchPriorityTests(fixture.AcquisitionImporterTests):
    def priority_call(self, *, execute=False, **overrides):
        arguments = {
            "batch_manifest": self.batch_manifest,
            "manifest_sha256": self.batch_sha,
            "audit_report": self.report,
            "target_priority": 24,
            "max_jobs": 3,
            "root": self.root,
            "execute": execute,
        }
        arguments.update(overrides)
        with (
            patch.object(module.pipeline_module, "ROOT", self.root),
            patch.object(module.pipeline_module, "authority", return_value=None),
        ):
            return module.prioritize_batch(**arguments)

    def import_all(self):
        for shard in self.batch["shards"]:
            self.shard = shard
            self.execute(max_jobs=2)

    def test_priority_plan_is_inert_and_bounded(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        report = self.priority_call()
        self.assertEqual(report["status"], "plan_only")
        self.assertEqual(report["verified_jobs"], 3)
        self.assertFalse(report["would_mutate"])
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "explicit bounded"):
            self.priority_call(max_jobs=2)

    def test_only_pending_priority_changes_and_rerun_is_idempotent(self):
        self.import_all()
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        rows = db.execute("SELECT id FROM jobs ORDER BY rowid").fetchall()
        db.execute(
            "UPDATE jobs SET state='done',tries=2,result=?,retry_after=7 WHERE id=?",
            (json.dumps({"api_name": "fund_div", "status": "sample_ok"}), rows[0][0]),
        )
        db.commit()
        before = {row[0]: row for row in db.execute("SELECT * FROM jobs ORDER BY rowid")}
        db.close()

        first = self.priority_call(execute=True)
        self.assertEqual(first["changed_jobs"], 2)
        self.assertEqual(first["changed"], {"etf_limit": 1, "fund_div": 1})
        self.assertTrue(first["task_identity_preserved"])
        self.assertFalse(first["credentials_accessed"])
        self.assertEqual(first["upstream_calls"], 0)

        db = sqlite3.connect(self.root / "pipeline.sqlite")
        after = {row[0]: row for row in db.execute("SELECT * FROM jobs ORDER BY rowid")}
        db.close()
        for task_id, original in before.items():
            changed = list(after[task_id])
            self.assertEqual(changed[0:4], list(original[0:4]))
            self.assertEqual(changed[5:], list(original[5:]))
            self.assertEqual(changed[4], 24 if original[5] == "pending" else original[4])
        second = self.priority_call(execute=True)
        self.assertEqual(second["changed_jobs"], 0)

    def test_missing_or_mismatched_authority_task_rolls_back(self):
        self.import_all()
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        ids = [row[0] for row in db.execute("SELECT id FROM jobs ORDER BY rowid")]
        db.execute("UPDATE jobs SET logical_key='wrong' WHERE id=?", (ids[-1],))
        db.commit()
        before = db.execute("SELECT id,priority FROM jobs ORDER BY rowid").fetchall()
        db.close()
        with self.assertRaisesRegex(ValueError, "identity"):
            self.priority_call(execute=True)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        self.assertEqual(db.execute("SELECT id,priority FROM jobs ORDER BY rowid").fetchall(), before)
        db.close()


if __name__ == "__main__":
    unittest.main()
