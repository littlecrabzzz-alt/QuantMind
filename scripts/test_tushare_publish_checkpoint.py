"""Offline, temporary-root resumable publication and byte-equivalence proofs."""

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as m
from backend.shared import tushare_publish_checkpoint as spool
from scripts import test_tushare_publish_equivalence as equivalence
from scripts import test_tushare_publish_interval as interval


class StagedEquivalence(unittest.TestCase):
    setUp = equivalence.PublishEquivalence.setUp
    legacy = staticmethod(m.Pipeline.publish)

    def compare_publish(self):
        old, new = self.pairs
        left = old.publish()
        for phase in ("content_saved", "ready_saved"):
            self.assertIsNone(new.publish(staged=True))
            self.assertEqual(new.publication_step["phase"], phase)
        right = new.publish(staged=True)
        self.assertEqual(left, right)
        a = (old.root / f"releases/{left}/manifest.json").read_bytes()
        b = (new.root / f"releases/{right}/manifest.json").read_bytes()
        self.assertEqual(a, b)
        self.assertEqual(
            (old.root / "CURRENT.json").read_bytes(),
            (new.root / "CURRENT.json").read_bytes(),
        )
        self.assertFalse((new.root / spool.NAME / "checkpoint.json").exists())
        return right, json.loads(b)

    def test_three_generations_all_attempts_gaps_revisions_legacy_archive_noop_equal(
        self,
    ):
        equivalence.PublishEquivalence.test_three_generations_noop_and_entire_history_are_byte_equal(
            self
        )


class CheckpointRecovery(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            self.stack.enter_context(
                patch(name, side_effect=AssertionError("offline only"))
            )
        self.p = m.Pipeline(self.root, {"entries": []})
        self.addCleanup(lambda: self.p.close())
        self.first = self.p.publish()
        self.p.enqueue("daily", {"trade_date": "20260101"}, epoch="history")
        self.p.db.commit()
        self.pointer = (self.root / "CURRENT.json").read_bytes()

    def restart(self):
        self.p.close()
        self.p = m.Pipeline(self.root, {"entries": []})

    def phase(self, expected):
        self.assertIsNone(self.p.publish(staged=True))
        self.assertEqual(self.p.publication_step["phase"], expected)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)

    def frozen(self):
        self.phase("content_saved")
        return spool.load(self.root)

    def finish(self):
        self.phase("ready_saved")
        result = self.p.publish(staged=True)
        self.assertNotEqual(result, self.first)
        self.assertIsNone(spool.load(self.root))
        return result

    def test_restart_skips_live_scans_and_preserves_new_progress_for_next_version(self):
        self.frozen()
        frozen_jobs = [
            tuple(r) for r in self.p.db.execute("SELECT * FROM jobs ORDER BY id")
        ]
        self.p.enqueue("daily", {"trade_date": "20260102"}, epoch="history")
        self.p.db.commit()
        before = [tuple(r) for r in self.p.db.execute("SELECT * FROM jobs ORDER BY id")]
        self.restart()
        queries = []
        self.p.db.set_trace_callback(queries.append)
        result = self.finish()
        self.assertFalse(
            any(
                "FROM jobs" in q or "FROM attempts" in q or "FROM partition_" in q
                for q in queries
            )
        )
        manifest = m.manifest_at(self.root, result)
        self.assertEqual(sum(manifest["coverage"].values()), len(frozen_jobs))
        self.assertEqual(
            [tuple(r) for r in self.p.db.execute("SELECT * FROM jobs ORDER BY id")],
            before,
        )
        self.phase_after = self.p.publish(staged=True)
        self.p.publish(staged=True)
        newest = self.p.publish(staged=True)
        self.assertEqual(
            sum(m.manifest_at(self.root, newest)["coverage"].values()), len(before)
        )

    def test_freeze_journal_failure_does_not_expose_partial_input(self):
        original = spool._write

        def fail(root, name, raw):
            if name == "checkpoint.json":
                raise OSError("fixture journal failure")
            return original(root, name, raw)

        with (
            patch.object(spool, "_write", side_effect=fail),
            self.assertRaises(OSError),
        ):
            self.p.publish(staged=True)
        self.assertIsNone(spool.load(self.root))
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.restart()
        self.frozen()
        self.finish()

    def test_retention_then_serialization_failure_and_manifest_then_journal_failure(
        self,
    ):
        self.frozen()
        original = m.json_bytes

        def fail(value):
            if isinstance(value, dict) and "partition_closure" in value:
                raise RuntimeError("fixture interrupted encoding")
            return original(value)

        with (
            patch.object(m, "json_bytes", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            self.p.publish(staged=True)
        self.assertTrue((self.root / "archives" / (self.first[5:] + ".json")).exists())
        self.assertEqual(spool.load(self.root)["phase"], "content")
        self.restart()
        with (
            patch.object(spool, "ready", side_effect=OSError("fixture ready journal")),
            self.assertRaises(OSError),
        ):
            self.p.publish(staged=True)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.restart()
        self.finish()

    def test_journal_directory_fsync_failure_recovers_committed_exact_content(self):
        original = spool._sync
        raised = []

        def fail(directory):
            original(directory)
            if not raised and (self.root / spool.NAME / "checkpoint.json").exists():
                raised.append(True)
                raise OSError("fixture after journal rename")

        with patch.object(spool, "_sync", side_effect=fail), self.assertRaises(OSError):
            self.p.publish(staged=True)
        saved = spool.load(self.root)
        self.assertEqual(saved["phase"], "content")
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.restart()
        self.finish()

    def test_current_switch_then_cleanup_failure_recovers_same_release(self):
        self.frozen()
        self.phase("ready_saved")
        with (
            patch.object(spool, "clear", side_effect=OSError("fixture cleanup")),
            self.assertRaises(OSError),
        ):
            self.p.publish(staged=True)
        switched = spool.current(self.root)
        self.assertNotEqual(switched, self.first)
        self.restart()
        self.assertEqual(self.p.publish(staged=True), switched)
        self.assertIsNone(spool.load(self.root))

    def test_current_replace_failure_keeps_ready_for_retry(self):
        self.frozen()
        self.phase("ready_saved")
        original = m.atomic_json

        def fail(path, value):
            if path.name == "CURRENT.json":
                raise OSError("fixture pointer replace")
            return original(path, value)

        with (
            patch.object(m, "atomic_json", side_effect=fail),
            self.assertRaises(OSError),
        ):
            self.p.publish(staged=True)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.assertEqual(spool.load(self.root)["phase"], "ready")
        self.restart()
        self.assertNotEqual(self.p.publish(staged=True), self.first)

    def test_current_drift_and_legacy_call_fail_closed_without_discarding_journal(self):
        self.frozen()
        with self.assertRaisesRegex(ValueError, "explicit staged"):
            self.p.publish()
        m.atomic_json(
            self.root / "CURRENT.json",
            {"release_id": "data-" + "f" * 64, "manifest_sha256": "f" * 64},
        )
        saved = (self.root / spool.NAME / "checkpoint.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "predecessor changed"):
            self.p.publish(staged=True)
        self.assertEqual(
            (self.root / spool.NAME / "checkpoint.json").read_bytes(), saved
        )

    def test_equal_size_content_tamper_missing_ready_and_symlink_are_rejected(self):
        saved = self.frozen()
        path = self.root / spool.NAME / "content.json"
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"blocked_data"', b'"BROKEN__data"', 1))
        self.assertEqual(len(path.read_bytes()), len(original))
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.p.publish(staged=True)
        path.write_bytes(original)
        self.phase("ready_saved")
        ready = spool.load(self.root)
        manifest = self.root / "releases" / ready["release_id"] / "manifest.json"
        raw = manifest.read_bytes()
        manifest.unlink()
        with self.assertRaises(FileNotFoundError):
            self.p.publish(staged=True)
        external = self.root / "external"
        external.write_bytes(raw)
        manifest.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.p.publish(staged=True)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.assertEqual(saved["phase"], "content")

    def test_cooperative_budget_does_not_advance_current_or_claim_hard_bound(self):
        self.frozen()
        # Reading/comparing one indivisible snapshot can itself exceed the budget.
        with patch.object(m.time, "monotonic", side_effect=range(0, 1000, 20)):
            self.assertIsNone(self.p.publish(staged=True, stage_budget_seconds=1))
        self.assertTrue(self.p.publication_step["budget_exceeded"])
        self.assertEqual(spool.load(self.root)["phase"], "content")
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.pointer)
        self.finish()


class StagedTick(unittest.TestCase):
    setUp = interval.PublicationInterval.setUp
    acquire = interval.PublicationInterval.acquire
    register = interval.PublicationInterval.register
    tick = interval.PublicationInterval.tick
    saved = interval.PublicationInterval.saved
    checkpoint = interval.PublicationInterval.checkpoint

    def test_only_completed_pointer_updates_success_and_no_acquire_during_stages(self):
        self.config["publish_staged"] = True
        for _ in range(2):
            result = self.tick(120)
            self.assertFalse(result["publication"]["performed"])
            self.assertEqual(result["publication"]["status"], "staged")
            self.assertIsNone(self.checkpoint())
            self.assertFalse((self.root / "CURRENT.json").exists())
        result = self.tick(120)
        self.assertTrue(result["publication"]["performed"])
        self.assertEqual(self.checkpoint(), self.now)
        self.assertEqual(self.acquisitions, 0)
        self.assertEqual(self.registrations, 0)
        self.tick(120)
        self.assertEqual(self.acquisitions, 1)

    def test_pending_cannot_be_disabled_or_delayed_by_interval_change(self):
        self.config["publish_staged"] = True
        self.tick()
        self.config["publish_staged"] = False
        with self.assertRaisesRegex(ValueError, "explicit staged"):
            self.tick()
        self.config.update(publish_staged=True, publish_interval_seconds=999999)
        self.assertEqual(self.tick()["publication"]["status"], "staged")
        self.assertTrue(self.tick()["publication"]["performed"])
        self.assertEqual(self.acquisitions, 0)

    def test_staged_cannot_stack_after_legacy_acquisition(self):
        self.config.update(publish_staged=True, publish_interval_seconds=0)
        with self.assertRaisesRegex(ValueError, "positive publication"):
            self.tick()
        self.assertEqual(self.acquisitions, 0)


if __name__ == "__main__":
    unittest.main()
