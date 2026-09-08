"""Isolated tick timing checks; no credentials, production roots or network."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module


class TickTimingTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "ENABLED").touch()
        (self.root / "pipeline-config.json").write_text(
            json.dumps(
                {
                    "batch_requests": 17,
                    "batch_seconds": 90,
                    "enable_documents": True,
                    "document_execution": "worker",
                }
            )
        )
        self.clock = 1000.0
        self.calls = []
        self.failure = None
        self.pipeline = MagicMock()
        self.stage_values = {
            "initialize": None,
            "planning": {"enqueued": 3},
            "archive": {"remaining": 4},
            "acquire": {"requests": 17, "elapsed_seconds": 90, "done": 21},
            "document_registration": {"registered": 2},
            "documents": {"parsed": 1},
            "publish": "data-" + "a" * 64,
            "close": None,
        }
        self.durations = dict(
            zip(self.stage_values, (2, 3, 5, 90, 7, 11, 13, 1), strict=True)
        )
        for method, stage in (
            ("initialize", "initialize"),
            ("plan_extended", "planning"),
            ("run", "acquire"),
            ("register_documents", "document_registration"),
            ("publish", "publish"),
            ("close", "close"),
        ):
            getattr(self.pipeline, method).side_effect = self.effect(stage)
        self.stack.enter_context(patch.object(module, "ROOT", self.root))
        self.stack.enter_context(patch.object(module, "authority"))
        self.stack.enter_context(
            patch.object(module, "get_secret", return_value="test-only")
        )
        self.stack.enter_context(
            patch.object(
                module.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=200 * 2**30),
            )
        )
        self.stack.enter_context(
            patch.object(module, "Pipeline", return_value=self.pipeline)
        )
        self.stack.enter_context(
            patch.object(module.time, "monotonic", side_effect=lambda: self.clock)
        )
        self.client = self.stack.enter_context(patch.object(module.httpx, "Client"))
        self.stack.enter_context(
            patch(
                "backend.shared.tushare_archive.recover_archive",
                side_effect=self.effect("archive"),
            )
        )
        self.documents = self.stack.enter_context(
            patch(
                "backend.shared.tushare_documents.run_documents",
                side_effect=self.effect("documents"),
            )
        )
        self.stack.enter_context(
            patch("socket.socket", side_effect=AssertionError("network forbidden"))
        )

    def effect(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            self.clock += self.durations[name]
            if name == self.failure:
                raise RuntimeError("test secret text must never be reported")
            return self.stage_values[name]

        return call

    def saved(self):
        return json.loads((self.root / "pipeline-status.json").read_bytes())

    def test_success_preserves_fields_order_arguments_and_wall_clock(self):
        report = module.tick()
        expected = [
            "initialize",
            "planning",
            "archive",
            "acquire",
            "document_registration",
            "publish",
            "close",
        ]
        self.assertEqual(self.calls, expected)
        self.assertEqual(report, self.saved())
        self.assertEqual(report["requests"], 17)
        self.assertEqual(report["elapsed_seconds"], 90)
        self.assertEqual(report["done"], 21)
        self.assertEqual(report["planning"], {"enqueued": 3})
        self.assertEqual(report["archive"], {"remaining": 4})
        self.assertEqual(report["release_id"], self.stage_values["publish"])
        timing = report["timing"]
        self.assertEqual(timing["completed_stages"], expected)
        self.assertEqual(
            timing["stage_seconds"], {key: self.durations[key] for key in expected}
        )
        self.assertEqual(timing["total_elapsed_seconds"], 121)
        self.assertIsNone(timing["failed_stage"])
        self.assertEqual(timing["included_stages"], {"reconciliation": "acquire"})
        self.pipeline.run.assert_called_once_with(
            self.client.return_value.__enter__.return_value,
            "test-only",
            unittest.mock.ANY,
            17,
            90,
            pause=0,
        )
        self.documents.assert_not_called()
        self.pipeline.reconcile_partitions.assert_not_called()

    def test_each_stage_error_keeps_completed_timings_and_exception(self):
        stages = [
            "initialize",
            "planning",
            "archive",
            "acquire",
            "document_registration",
            "publish",
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                self.calls.clear()
                self.failure = stage
                with self.assertRaisesRegex(RuntimeError, "test secret"):
                    module.tick()
                report = self.saved()
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["error_type"], "RuntimeError")
                self.assertEqual(report["timing"]["failed_stage"], stage)
                self.assertNotIn(stage, report["timing"]["completed_stages"])
                self.assertIn("close", report["timing"]["completed_stages"])
                self.assertGreater(report["timing"]["total_elapsed_seconds"], 0)
                self.assertTrue(
                    all(
                        value >= 0
                        for value in report["timing"]["stage_seconds"].values()
                    )
                )
                self.assertNotIn("test secret", json.dumps(report))
                self.assertNotIn("release_id", report)
                if stage == "publish":
                    self.assertEqual(report["requests"], 17)
                    self.assertEqual(report["archive"], {"remaining": 4})

    def test_reporting_error_does_not_mask_original(self):
        self.failure = "archive"
        with patch.object(module, "atomic_json", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "test secret"):
                module.tick()
        self.assertEqual(self.calls, ["initialize", "planning", "archive", "close"])

    def test_inline_documents_and_explicit_batch_limits_unchanged(self):
        (self.root / "pipeline-config.json").write_text(
            json.dumps({"enable_documents": True})
        )
        report = module.tick(max_requests=2, max_seconds=4)
        self.assertEqual(report["documents"], {"parsed": 1})
        self.assertEqual(report["timing"]["stage_seconds"]["documents"], 11)
        self.assertEqual(self.pipeline.run.call_args.args[-2:], (2, 4))
        self.documents.assert_called_once_with(
            self.root, max_documents=3, max_seconds=20
        )

    def test_early_guard_return_is_unchanged(self):
        (self.root / "ENABLED").unlink()
        self.assertEqual(module.tick(), {"status": "disabled"})
        self.assertFalse((self.root / "pipeline-status.json").exists())
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
