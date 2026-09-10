"""Authority shard imports are verified, bounded, atomic and idempotent."""

import fcntl
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_tushare_rrg_acquisition_shard as module
import prepare_tushare_rrg_acquisition_batch as preparation


class AcquisitionImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.audit = self.base / "audit"
        self.audit.mkdir()
        self.report = self.audit / "report.json"
        self.report.write_text(
            json.dumps(
                {
                    "status": "blocked_data",
                    "release_id": "data-" + "a" * 64,
                    "upstream_calls": 0,
                    "credentials_accessed": False,
                    "window": {"start_date": "20220101", "end_date": "20221231"},
                    "collection_plan": {"jobs": 3},
                }
            )
        )
        rows = [
            {
                "api_name": "fund_div",
                "params": {"ts_code": "510300.SH"},
                "gate": "requires_terminal_receipt",
                "reason": "terminal receipt",
            },
            {
                "api_name": "fund_div",
                "params": {"ts_code": "159915.SZ"},
                "gate": "requires_terminal_receipt",
                "reason": "terminal receipt",
            },
            {
                "api_name": "etf_limit",
                "params": {"start_date": "20220101", "end_date": "20220131"},
                "gate": "collection_candidate",
                "reason": "monthly bounds",
            },
        ]
        self.plan = self.audit / "collection-plan.jsonl"
        self.plan.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                for row in rows
            )
        )
        (self.audit / "manifest.json").write_text(
            json.dumps(
                {
                    "release_id": "data-" + "a" * 64,
                    "status": "blocked_data",
                    "files": {
                        "report.json": {"sha256": preparation.sha(self.report)},
                        "collection-plan.jsonl": {"sha256": preparation.sha(self.plan)},
                    },
                }
            )
        )
        self.batch_folder = self.base / "batch"
        self.batch = preparation.prepare(
            self.report,
            preparation.sha(self.report),
            self.batch_folder,
            2,
            False,
        )
        self.batch_manifest = self.batch_folder / "batch-manifest.json"
        self.batch_sha = preparation.sha(self.batch_manifest)
        self.shard = self.batch["shards"][0]
        self.root = self.base / "authority"
        pipeline = module.Pipeline(self.root, self._catalog())
        pipeline.close()
        self.current = self.root / "CURRENT.json"
        self.current.write_text('{"release_id":"unchanged"}\n')

    @staticmethod
    def _catalog():
        return json.loads((module.REPO / "config/tushare-catalog.json").read_bytes())

    def invoke(self, **overrides):
        arguments = {
            "batch_manifest": self.batch_manifest,
            "manifest_sha256": self.batch_sha,
            "audit_report": self.report,
            "shard": self.shard["path"],
        }
        arguments.update(overrides)
        return module.import_shard(**arguments)

    def execute(self, **overrides):
        arguments = {
            "expected_shard_sha256": self.shard["sha256"],
            "root": self.root,
            "max_jobs": 2,
            "execute": True,
        }
        arguments.update(overrides)
        with (
            patch.object(module.pipeline_module, "ROOT", self.root),
            patch.object(module.pipeline_module, "authority", return_value=None),
        ):
            return self.invoke(**arguments)

    def job_count(self):
        connection = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            return connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        finally:
            connection.close()

    def test_plan_only_verifies_complete_batch_without_touching_authority(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        result = self.invoke(root=self.base / "ignored")
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_shards"], 2)
        self.assertEqual(result["verified_jobs"], 3)
        self.assertEqual(result["selected_jobs"], 2)
        self.assertFalse(result["would_enqueue"])
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        self.assertFalse((self.root / "pipeline.lock").exists())

    def test_execute_is_atomic_idempotent_and_receipt_is_redacted(self):
        original_verify = module.verify_batch

        def verify_while_locked(*args, **kwargs):
            with (self.root / "pipeline.lock").open("a+") as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original_verify(*args, **kwargs)

        with patch.object(module, "verify_batch", verify_while_locked):
            first = self.execute()
        self.assertEqual(first["status"], "shard_enqueued")
        self.assertEqual((first["inserted"], first["already_present"]), (2, 0))
        self.assertEqual(first["states"], {"pending": 2})
        self.assertEqual(self.job_count(), 2)
        self.assertEqual(self.current.read_text(), '{"release_id":"unchanged"}\n')
        encoded = json.dumps(first, sort_keys=True)
        self.assertNotIn(str(self.base), encoded)
        self.assertNotIn("510300.SH", encoded)
        self.assertNotIn("params", encoded)
        self.assertFalse(first["credentials_accessed"])
        self.assertEqual(first["upstream_calls"], 0)
        self.assertFalse(first["worker_run"])
        self.assertFalse(first["release_published"])
        self.assertFalse(first["current_release_switched"])

        second = self.execute()
        self.assertEqual((second["inserted"], second["already_present"]), (0, 2))
        self.assertEqual(self.job_count(), 2)
        self.assertEqual(second["task_ids_sha256"], first["task_ids_sha256"])

    def test_busy_lock_and_old_schema_reject_without_queue_changes(self):
        lock_path = self.root / "pipeline.lock"
        with lock_path.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.execute()
        self.assertEqual(self.job_count(), 0)

        connection = sqlite3.connect(self.root / "pipeline.sqlite")
        connection.execute("PRAGMA user_version=5")
        connection.close()
        with self.assertRaisesRegex(ValueError, "schema must already be version 6"):
            self.execute()
        connection = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
            )
        finally:
            connection.close()

    def test_mid_import_failure_rolls_back_entire_shard(self):
        original = module.Pipeline.enqueue
        calls = 0

        def fail_second(pipeline, *args, **kwargs):
            nonlocal calls
            if pipeline.root.resolve() == self.root.resolve():
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected failure")
            return original(pipeline, *args, **kwargs)

        with patch.object(module.Pipeline, "enqueue", fail_second):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                self.execute()
        self.assertEqual(self.job_count(), 0)

    def test_full_hash_chain_identity_and_explicit_bounds_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "Batch manifest hash mismatch"):
            self.invoke(manifest_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "Explicit shard hash mismatch"):
            self.execute(expected_shard_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "bounded import limit"):
            self.execute(max_jobs=1)
        with self.assertRaisesRegex(ValueError, "configured authority root"):
            self.execute(root=self.base / "other")

        shard_path = self.batch_folder / self.shard["path"]
        records = [json.loads(line) for line in shard_path.read_text().splitlines()]
        records[0]["priority"] += 1
        shard_path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in records)
        )
        manifest = json.loads(self.batch_manifest.read_bytes())
        meta = manifest["shards"][0]
        meta["bytes"] = shard_path.stat().st_size
        meta["sha256"] = preparation.sha(shard_path)
        self.batch_manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "source plan policy"):
            self.invoke(manifest_sha256=preparation.sha(self.batch_manifest))

    def test_unlisted_shard_and_source_tampering_are_rejected(self):
        extra = self.batch_folder / "shards" / "9999-extra.jsonl"
        extra.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "Unlisted or missing"):
            self.invoke()
        extra.unlink()
        self.report.write_text(self.report.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Audit report hash mismatch"):
            self.invoke()


if __name__ == "__main__":
    unittest.main()
