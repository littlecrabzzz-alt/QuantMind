"""Exact RRG batch selection, authority gates and redacted receipt."""

import fcntl
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_tushare_rrg_acquisition_shard as importer
import prepare_tushare_rrg_acquisition_batch as preparation
import run_tushare_rrg_acquisition_batch as runner


class ExactBatchRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
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
                    "collection_plan": {"jobs": 4},
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
            {
                "api_name": "fund_daily",
                "params": {
                    "ts_code": "510300.SH",
                    "start_date": "20220104",
                    "end_date": "20220104",
                },
                "gate": "diagnostic_refresh_only",
                "reason": "no fill",
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
        self.batch_dir = self.base / "batch"
        preparation.prepare(
            self.report,
            preparation.sha(self.report),
            self.batch_dir,
            2,
            False,
        )
        self.batch = self.batch_dir / "batch-manifest.json"
        self.batch_sha = preparation.sha(self.batch)
        self.verified = importer.verify_batch(
            self.batch, self.batch_sha, self.report, shard=None
        )
        self.root = self.base / "authority"
        pipeline = runner.pipeline_module.Pipeline(self.root, self.verified["catalog"])
        pipeline.close()
        (self.root / "ENABLED").write_text("enabled\n")
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_text(json.dumps(self.config))
        (self.root / "CURRENT.json").write_text('{"release_id":"unchanged"}\n')
        self._import_all()

    def _import_all(self):
        manifest = json.loads(self.batch.read_bytes())
        for shard in manifest["shards"]:
            with (
                patch.object(importer.pipeline_module, "ROOT", self.root),
                patch.object(importer.pipeline_module, "authority", return_value=None),
            ):
                importer.import_shard(
                    self.batch,
                    self.batch_sha,
                    self.report,
                    shard=shard["path"],
                    expected_shard_sha256=shard["sha256"],
                    root=self.root,
                    max_jobs=2,
                    execute=True,
                )

    def invoke(self, **overrides):
        arguments = {
            "batch_manifest": self.batch,
            "manifest_sha256": self.batch_sha,
            "audit_report": self.report,
        }
        arguments.update(overrides)
        return runner.run_batch(**arguments)

    def execute(self, handler, **overrides):
        arguments = {
            "expected_task_ids_sha256": self.verified["all_task_ids_sha256"],
            "expected_config_sha256": runner.sha(self.config_path),
            "expected_helper_sha256": runner.helper_sha256(),
            "root": self.root,
            "max_requests": 2,
            "max_seconds": 10,
            "execute": True,
        }
        arguments.update(overrides)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.httpx, "Client", return_value=client),
        ):
            return self.invoke(**arguments)

    def test_plan_only_verifies_hash_chain_without_authority_or_credentials(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        result = self.invoke(root=self.base / "ignored")
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 3)
        self.assertEqual(result["api_counts"], {"etf_limit": 1, "fund_div": 2})
        self.assertEqual(result["selection"], "exact_manifest_task_ids_api_fair")
        self.assertFalse(result["would_access_authority"])
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)

    def test_plan_only_accepts_a_fund_daily_diagnostics_only_batch(self):
        output = self.base / "diagnostics-only"
        preparation.prepare(
            self.report,
            preparation.sha(self.report),
            output,
            2,
            False,
            diagnostics_only=True,
        )
        batch = output / "batch-manifest.json"
        result = runner.run_batch(
            batch,
            preparation.sha(batch),
            self.report,
            root=self.base / "unused",
        )
        self.assertEqual(result["verified_jobs"], 1)
        self.assertEqual(result["api_counts"], {"fund_daily": 1})

    def test_execute_is_exact_api_fair_bounded_and_does_not_publish(self):
        pipeline = runner.pipeline_module.Pipeline(self.root, self.verified["catalog"])
        unrelated = pipeline.enqueue(
            "fund_div", {"ts_code": "512000.SH"}, priority=1, epoch="history"
        )
        pipeline.db.commit()
        pipeline.close()
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append((body["api_name"], body["params"]))
            fields = body["fields"].split(",")
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": []}}
            )

        pointer = (self.root / "CURRENT.json").read_bytes()
        with (
            patch.object(
                runner.pipeline_module.Pipeline,
                "expand",
                side_effect=AssertionError(
                    "exact run must not expand the global queue"
                ),
            ),
            patch.object(
                runner.pipeline_module.Pipeline,
                "resume_identifier_split",
                side_effect=AssertionError(
                    "exact run must not resume an unrelated deferred split"
                ),
            ),
        ):
            result = self.execute(respond)
        self.assertEqual([api for api, _ in calls], ["etf_limit", "fund_div"])
        self.assertEqual(result["attempted_by_api"], {"etf_limit": 1, "fund_div": 1})
        self.assertEqual(result["upstream_calls"], 2)
        self.assertEqual(result["scoped_jobs"], 3)
        self.assertTrue(result["exact_task_scope"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (unrelated,)
                ).fetchone()[0],
                "pending",
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (unrelated,)
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.base), encoded)
        self.assertNotIn("510300.SH", encoded)
        self.assertFalse(result["release_published"])

    def test_execute_rejects_hash_bounds_schema_and_busy_lock_before_http(self):
        calls = 0

        def respond(_request):
            nonlocal calls
            calls += 1
            raise AssertionError("HTTP must remain unreachable")

        with self.assertRaisesRegex(ValueError, "helper hash mismatch"):
            self.execute(respond, expected_helper_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "config hash mismatch"):
            self.execute(respond, expected_config_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "task ID inventory hash mismatch"):
            self.execute(respond, expected_task_ids_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "request limit"):
            self.invoke(max_requests=361)
        with self.assertRaisesRegex(ValueError, "at most 90"):
            self.invoke(max_seconds=91)

        with (self.root / "pipeline.lock").open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.execute(respond)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute("PRAGMA user_version=5")
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "schema must already be version 6"):
            self.execute(respond)
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
