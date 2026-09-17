#!/usr/bin/env python3
"""Offline reassessment tests for retained cyq_chips supplier-empty payloads."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_cyq_empty_reassessment as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
EXACT_MESSAGE = "指定数据不存在，请确认参数！"


class CyqEmptyReassessment(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def seed(self, *, message=EXACT_MESSAGE):
        task = self.pipeline.enqueue(
            "cyq_chips",
            {"ts_code": "600001.SH", "trade_date": "20260904"},
            55,
            "history",
        )
        raw = json_bytes({"code": 50101, "msg": message, "data": None})
        object_sha = digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / f"{object_sha}.json").write_bytes(raw)
        observation_body = json_bytes({"fixture": task, "payload": json.loads(raw)})
        observation_sha = digest(observation_body)
        (self.root / "observations").mkdir(exist_ok=True)
        observation = task[:32] + ".json"
        (self.root / "observations" / observation).write_bytes(observation_body)
        result = {
            "api_name": "cyq_chips",
            "status": "api_error",
            "code": 50101,
            "field_coverage": "unverified_default_or_invalid",
            "requested_missing_fields": None,
            "unexpected_returned_fields": None,
            "response_complete": True,
            "response_format": "json",
            "http_status": 200,
            "object_sha256": object_sha,
            "observation": observation,
            "observation_sha256": observation_sha,
        }
        encoded = json.dumps(result, sort_keys=True)
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',tries=1,result=? WHERE id=?",
            (encoded, task),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (task, 1, encoded),
        )
        self.pipeline.db.commit()
        return task, result

    def snapshot(self):
        return {
            table: [
                tuple(row)
                for row in self.pipeline.db.execute(f"SELECT * FROM {table} ORDER BY 1")
            ]
            for table in ("jobs", "attempts", "capability")
        }

    def test_dry_run_rolls_back_then_apply_preserves_attempt(self):
        task, old = self.seed()
        before = self.snapshot()
        dry = migration.reassess(self.pipeline)
        self.assertEqual(dry["status"], "planned_rollback")
        self.assertEqual(dry["candidate_jobs"], 1)
        self.assertEqual(dry["promoted_jobs"], 1)
        self.assertEqual(self.snapshot(), before)

        report = migration.reassess(self.pipeline, apply=True)
        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["promoted_jobs"], 1)
        state, saved = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        saved = json.loads(saved)
        self.assertEqual(state, "empty")
        self.assertEqual(saved["status"], "empty_unverified")
        self.assertTrue(saved["supplier_empty_hint"])
        self.assertFalse(saved["coverage_proven"])
        self.assertEqual(
            saved["response_reassessment"]["previous_status"], old["status"]
        )
        self.assertEqual(
            json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM attempts WHERE job_id=?", (task,)
                ).fetchone()[0]
            )["status"],
            "api_error",
        )
        status, reason = self.pipeline.db.execute(
            "SELECT status,reason FROM capability WHERE scope=?",
            ("reassessment:" + task,),
        ).fetchone()
        self.assertEqual(status, "supplier_empty_reassessed")
        self.assertFalse(json.loads(reason)["coverage_proven"])
        second = migration.reassess(self.pipeline, apply=True)
        self.assertEqual(second["candidate_jobs"], 0)

    def test_nearby_supplier_message_stays_blocked(self):
        task, _ = self.seed(message="指定数据不存在，请检查参数！")
        report = migration.reassess(self.pipeline, apply=True)
        self.assertEqual(report["candidate_jobs"], 1)
        self.assertEqual(report["promoted_jobs"], 0)
        self.assertEqual(report["unchanged_by_status"], {"api_error": 1})
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "blocked",
        )

    def test_corrupt_object_aborts_and_rolls_back(self):
        task, _ = self.seed()
        row = self.pipeline.db.execute(
            "SELECT result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        result = json.loads(row[0])
        (self.root / "objects" / f"{result['object_sha256']}.json").write_bytes(
            b"corrupt"
        )
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            migration.reassess(self.pipeline, apply=True)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
