"""Offline recovery tests for retained normalization timeouts."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_intake import (  # noqa: E402
    assess_success_payload,
    digest,
    json_bytes,
)
from backend.shared.tushare_pipeline import Pipeline, manifest_at  # noqa: E402
from scripts import tushare_normalization_recovery as migration  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class NormalizationRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def seed(self, *, error="TimeoutError"):
        task = self.pipeline.enqueue(
            "daily_basic", {"trade_date": "20250530"}, 45, "history"
        )
        job = json.loads(
            self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE id=?", (task,)
            ).fetchone()[0]
        )
        fields = job["fields"].split(",")
        item = [
            "000001.SZ"
            if field == "ts_code"
            else "20250530"
            if field == "trade_date"
            else 1
            for field in fields
        ]
        payload = {
            "code": 0,
            "data": {"fields": fields, "items": [item], "has_more": False},
        }
        raw = json_bytes(payload)
        object_sha = digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / f"{object_sha}.json").write_bytes(raw)
        observation_body = json_bytes(
            {
                "request": {"api_name": "daily_basic", "params": job["params"]},
                "fetched_at": "2026-09-17T00:00:00Z",
            }
        )
        observation_sha = digest(observation_body)
        (self.root / "observations").mkdir(exist_ok=True)
        observation = task[:32] + ".json"
        (self.root / "observations" / observation).write_bytes(observation_body)
        result = {
            **assess_success_payload(job, payload),
            "api_name": "daily_basic",
            "response_complete": True,
            "response_format": "json",
            "http_status": 200,
            "object_sha256": object_sha,
            "observation": observation,
            "observation_sha256": observation_sha,
            "normalization_error": error,
        }
        self.assertEqual(result["status"], "sample_ok")
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

    def test_dry_run_then_apply_preserves_attempt_and_publishes_dataset(self):
        task, original = self.seed()
        dry = migration.recover(self.pipeline)
        self.assertEqual(dry["recovered_by_api"], {"daily_basic": 1})
        self.assertFalse((self.root / "parquet").exists())
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "blocked",
        )

        report = migration.recover(self.pipeline, apply=True)
        self.assertEqual(report["recovered_jobs"], 1)
        state, raw = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        saved = json.loads(raw)
        self.assertEqual(state, "done")
        self.assertNotIn("normalization_error", saved)
        self.assertTrue((self.root / saved["parquet"]["path"]).is_file())
        self.assertEqual(saved["normalization_recovery"]["upstream_calls"], 0)
        attempt = json.loads(
            self.pipeline.db.execute(
                "SELECT result FROM attempts WHERE job_id=?", (task,)
            ).fetchone()[0]
        )
        self.assertEqual(attempt, original)
        self.assertEqual(attempt["normalization_error"], "TimeoutError")
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT count(*) FROM normalization_recoveries WHERE job_id=?",
                (task,),
            ).fetchone()[0],
            1,
        )
        release = self.pipeline.publish()
        manifest = manifest_at(self.root, release)
        dataset = next(
            row
            for row in manifest["datasets"]
            if row["api_name"] == "daily_basic"
        )
        self.assertEqual(dataset["quality_state"], "sample_ok")
        self.assertEqual(
            dataset["normalization_recovery"]["previous_error"], "TimeoutError"
        )
        self.assertNotIn(task, {gap["id"] for gap in manifest["gaps"]})
        research = manifest_at(self.root, self.pipeline.publish(research=True))
        self.assertEqual(research["datasets"], manifest["datasets"])

    def test_non_transient_error_stays_blocked(self):
        task, _ = self.seed(error="ValueError")
        report = migration.recover(self.pipeline, apply=True)
        self.assertEqual(report["candidate_jobs"], 0)
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "blocked",
        )

    def test_corrupt_object_aborts_without_mutation(self):
        task, result = self.seed()
        (self.root / "objects" / f"{result['object_sha256']}.json").write_bytes(
            b"corrupt"
        )
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            migration.recover(self.pipeline, apply=True)
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "blocked",
        )


if __name__ == "__main__":
    unittest.main()
