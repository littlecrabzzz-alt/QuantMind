"""Publish substage timing, immutable output and error reporting; fixtures only."""

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_archive as archive
from backend.shared import tushare_documents as documents
from backend.shared import tushare_pipeline as module


class PublishTimingTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            self.stack.enter_context(
                patch(target, side_effect=AssertionError("offline only"))
            )

    def assert_timing(self, failed=None):
        timing = self.p.publish_timing
        self.assertEqual(timing["failed_stage"], failed)
        self.assertTrue(timing["stage_seconds"])
        self.assertGreaterEqual(timing["total_elapsed_seconds"], 0)
        self.assertTrue(all(x >= 0 for x in timing["stage_seconds"].values()))
        if failed:
            self.assertIn(failed, timing["stage_seconds"])
            self.assertNotIn(failed, timing["completed_stages"])
        self.assertEqual(
            set(timing["completed_stages"]), set(timing["stage_seconds"]) - {failed}
        )
        return timing

    def test_release_and_noop_identity_preserved_without_timing_in_artifacts(self):
        first = self.p.publish()
        self.assertRegex(first, r"^data-[a-f0-9]{64}$")
        timing = self.assert_timing()
        self.assertIn("scan_attempts_and_stat", timing["completed_stages"])
        self.assertIn("coverage_and_closure", timing["completed_stages"])
        self.assertNotIn("retain_previous", timing["completed_stages"])
        path = self.root / f"releases/{first}/manifest.json"
        original = path.read_bytes()
        self.assertNotIn("timing", json.loads(original))
        files_before = {p.relative_to(self.root) for p in self.root.rglob("*.json")}
        self.assertEqual(self.p.publish(), first)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(
            {p.relative_to(self.root) for p in self.root.rglob("*.json")}, files_before
        )
        timing = self.assert_timing()
        self.assertEqual(timing["completed_stages"][-1], "compare_previous")
        self.assertNotIn("write_manifest", timing["stage_seconds"])
        self.assertEqual(
            json.loads((self.root / "CURRENT.json").read_bytes())["release_id"], first
        )

    def test_changed_release_times_both_archive_reads_and_real_document_index(self):
        first = self.p.publish()
        db = documents._document_db(self.root)
        db.execute(
            "INSERT INTO documents(id,observation,url) VALUES(?,?,?)",
            ("a" * 64, "fixture", "https://example.com/document.pdf"),
        )
        db.commit()
        db.close()
        self.p.enqueue("trade_cal", {"start_date": "20260101"}, 1, "fixture")
        second = self.p.publish()
        self.assertNotEqual(second, first)
        timing = self.assert_timing()
        for stage in (
            "archive_inventory_before",
            "archive_inventory_after",
            "retain_previous",
            "document_index",
            "serialize_manifest",
            "write_manifest",
        ):
            self.assertIn(stage, timing["completed_stages"])
        manifest = module.manifest_at(self.root, second)
        self.assertEqual(manifest["documents"]["schema_version"], 3)
        self.assertIn(f"archives/{first[5:]}.json", manifest["files"])
        self.assertEqual(self.p.publish(), second)
        self.assert_timing()

    def test_missing_attempt_artifact_records_failure_without_writing_release(self):
        result = {
            "api_name": "daily",
            "observation": "a" * 32 + ".json",
            "observation_sha256": "b" * 64,
            "object_sha256": "c" * 64,
        }
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", ("fixture", 1, json.dumps(result))
        )
        self.p.db.commit()
        with self.assertRaises(FileNotFoundError):
            self.p.publish()
        timing = self.assert_timing("scan_attempts_and_stat")
        self.assertEqual(timing["completed_stages"], ["read_current", "scan_gaps"])
        self.assertFalse((self.root / "CURRENT.json").exists())

    def test_retention_failure_keeps_current_and_resets_on_retry(self):
        first = self.p.publish()
        pointer = (self.root / "CURRENT.json").read_bytes()
        self.p.enqueue("trade_cal", {"start_date": "20260101"}, 1, "fixture")
        with patch.object(
            archive, "retain_release", side_effect=RuntimeError("private error")
        ):
            with self.assertRaisesRegex(RuntimeError, "private error"):
                self.p.publish()
        self.assert_timing("retain_previous")
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        self.assertNotIn("private error", json.dumps(self.p.publish_timing))
        second = self.p.publish()
        self.assertNotEqual(second, first)
        self.assert_timing()

    def tick_context(self):
        (self.root / "ENABLED").touch()
        (self.root / "pipeline-config.json").write_text("{}")
        for target, kwargs in (
            ("ROOT", {"new": self.root}),
            ("authority", {}),
            ("get_secret", {"return_value": "fixture-no-real-secret"}),
            ("Pipeline", {"return_value": self.p}),
        ):
            self.stack.enter_context(patch.object(module, target, **kwargs))
        self.stack.enter_context(
            patch.object(
                module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=200 * 2**30),
            )
        )
        self.stack.enter_context(patch.object(module.httpx, "Client"))
        self.stack.enter_context(patch.object(self.p, "initialize"))
        self.stack.enter_context(patch.object(self.p, "plan_extended", return_value={}))
        self.stack.enter_context(
            patch.object(self.p, "run", return_value={"requests": 0})
        )
        self.stack.enter_context(
            patch.object(archive, "recover_archive", return_value={"remaining": 0})
        )

    def test_tick_forwards_publish_timing_in_existing_success_status(self):
        self.tick_context()
        report = module.tick()
        self.assertEqual(
            report, json.loads((self.root / "pipeline-status.json").read_bytes())
        )
        self.assertEqual(report["timing"]["publish"], self.p.publish_timing)
        self.assertEqual(report["requests"], 0)
        self.assertIn("publish", report["timing"]["completed_stages"])
        self.assert_timing()

    def test_tick_error_keeps_substage_timing_and_original_exception(self):
        self.tick_context()
        with patch.object(
            self.p, "partition_inventory", side_effect=RuntimeError("private error")
        ):
            with self.assertRaisesRegex(RuntimeError, "private error"):
                module.tick()
        report = json.loads((self.root / "pipeline-status.json").read_bytes())
        self.assertEqual(report["timing"]["failed_stage"], "publish")
        self.assertEqual(
            report["timing"]["publish"]["failed_stage"], "coverage_and_closure"
        )
        self.assertEqual(report["status"], "error")
        self.assertNotIn("private error", json.dumps(report))
        self.assertFalse((self.root / "CURRENT.json").exists())
        self.assert_timing("coverage_and_closure")


if __name__ == "__main__":
    unittest.main()
