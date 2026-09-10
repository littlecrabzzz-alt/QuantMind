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
import run_tushare_rrg_descendant_batch as descendant_runner


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

    def _split_etf_tree(self):
        record = next(
            row
            for values in self.verified["records_by_path"].values()
            for row in values
            if row["api_name"] == "etf_limit"
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, self.verified["catalog"])
        try:
            first = pipeline.enqueue(
                "etf_limit",
                {"start_date": "20220101", "end_date": "20220115"},
                priority=24,
                epoch=record["epoch"],
            )
            second = pipeline.enqueue(
                "etf_limit",
                {"start_date": "20220116", "end_date": "20220131"},
                priority=24,
                epoch=record["epoch"],
            )
            leaf_one = pipeline.enqueue(
                "etf_limit",
                {"start_date": "20220116", "end_date": "20220123"},
                priority=24,
                epoch=record["epoch"],
            )
            leaf_two = pipeline.enqueue(
                "etf_limit",
                {"start_date": "20220124", "end_date": "20220131"},
                priority=24,
                epoch=record["epoch"],
            )
            pipeline.record_partition(
                record["task_id"],
                [first, second],
                "date_bisection",
                True,
                {"fixture": "root"},
            )
            pipeline.record_partition(
                second,
                [leaf_one, leaf_two],
                "date_bisection",
                True,
                {"fixture": "child"},
            )
            pipeline.db.execute(
                "UPDATE jobs SET state='split_pending',priority=24,tries=1 "
                "WHERE id IN (?,?)",
                (record["task_id"], second),
            )
            pipeline.db.executemany(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,1,'{}')",
                [(record["task_id"],), (second,)],
            )
            pipeline.db.commit()
        finally:
            pipeline.close()
        return record["task_id"], {first, second, leaf_one, leaf_two}

    def descendant_plan(self, **overrides):
        arguments = {
            "batch_manifest": self.batch,
            "manifest_sha256": self.batch_sha,
            "audit_report": self.report,
            "root": self.root,
        }
        arguments.update(overrides)
        return descendant_runner.run_batch(**arguments)

    def execute_descendants(self, handler, plan, **overrides):
        arguments = {
            "expected_authority_sha256": plan["authority_sha256"],
            "expected_config_sha256": plan["authority_config_sha256"],
            "expected_helper_sha256": descendant_runner.helper_sha256(),
            "expected_task_set_sha256": plan["task_set_sha256"],
            "max_requests": 2,
            "max_seconds": 10,
            "execute": True,
        }
        arguments.update(overrides)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        disk = type("usage", (), {"free": 101 * 2**30})()
        with (
            patch.object(descendant_runner.pipeline_module, "ROOT", self.root),
            patch.object(
                descendant_runner.pipeline_module, "authority", return_value=None
            ),
            patch.object(
                descendant_runner.pipeline_module,
                "get_secret",
                return_value="fixture",
            ),
            patch.object(descendant_runner.httpx, "Client", return_value=client),
            patch.object(descendant_runner.shutil, "disk_usage", return_value=disk),
        ):
            return self.descendant_plan(**arguments)

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

    def test_descendant_plan_reports_full_tree_without_secret_or_network(self):
        parent, descendants = self._split_etf_tree()
        before = (self.root / "pipeline.sqlite").read_bytes()
        plan = self.descendant_plan()
        self.assertEqual(plan["status"], "plan_only")
        self.assertEqual(plan["descendant_root_tasks"], 1)
        self.assertEqual(plan["descendant_tasks"], 4)
        self.assertEqual(plan["pending_descendant_tasks"], 3)
        self.assertEqual([row["tasks"] for row in plan["layers"]], [1, 2, 2])
        self.assertEqual(plan["layers"][0]["task_ids"], [parent])
        self.assertEqual(
            {row["task_id"] for row in plan["tasks"] if row["depth"] > 0},
            descendants,
        )
        self.assertFalse(plan["credentials_accessed"])
        self.assertEqual(plan["upstream_calls"], 0)
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)

    def test_descendant_execute_is_hash_pinned_bounded_and_exact(self):
        _parent, descendants = self._split_etf_tree()
        pipeline = runner.pipeline_module.Pipeline(self.root, self.verified["catalog"])
        unrelated = pipeline.enqueue(
            "etf_limit",
            {"start_date": "20220201", "end_date": "20220228"},
            priority=1,
            epoch="history",
        )
        pipeline.db.commit()
        pipeline.close()
        plan = self.descendant_plan()
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body["params"])
            fields = body["fields"].split(",")
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": []}}
            )

        pointer = (self.root / "CURRENT.json").read_bytes()
        with (
            patch.object(
                runner.pipeline_module.Pipeline,
                "expand",
                side_effect=AssertionError("exact descendant run must not expand"),
            ),
            patch.object(
                runner.pipeline_module.Pipeline,
                "resume_identifier_split",
                side_effect=AssertionError("exact descendant run must not resume"),
            ),
        ):
            result = self.execute_descendants(respond, plan)
        self.assertEqual(result["status"], "exact_descendant_batch_executed")
        self.assertEqual(result["upstream_calls"], 2)
        self.assertEqual(result["scoped_jobs"], 4)
        self.assertEqual(result["attempted_by_api"], {"etf_limit": 2})
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            attempted = {
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT job_id FROM attempts WHERE attempt>0"
                )
            }
            self.assertFalse(unrelated in attempted)
            self.assertTrue(attempted & descendants)
        finally:
            db.close()
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.base), encoded)
        self.assertFalse(result["release_published"])

    def test_descendant_execute_rejects_hashes_bounds_lock_and_disk(self):
        self._split_etf_tree()
        plan = self.descendant_plan()

        def no_http(_request):
            raise AssertionError("HTTP must remain unreachable")

        with self.assertRaisesRegex(ValueError, "helper hash mismatch"):
            self.execute_descendants(no_http, plan, expected_helper_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "authority hash mismatch"):
            self.execute_descendants(no_http, plan, expected_authority_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "task set hash mismatch"):
            self.execute_descendants(no_http, plan, expected_task_set_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "request limit"):
            self.descendant_plan(max_requests=361)
        with self.assertRaisesRegex(ValueError, "at most 90"):
            self.descendant_plan(max_seconds=91)
        with (self.root / "pipeline.lock").open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.execute_descendants(no_http, plan)
        disk = type("usage", (), {"free": 99 * 2**30})()
        with (
            patch.object(descendant_runner.pipeline_module, "ROOT", self.root),
            patch.object(
                descendant_runner.pipeline_module, "authority", return_value=None
            ),
            patch.object(
                descendant_runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("disk gate must precede credentials"),
            ),
            patch.object(descendant_runner.shutil, "disk_usage", return_value=disk),
        ):
            result = self.descendant_plan(
                expected_authority_sha256=plan["authority_sha256"],
                expected_config_sha256=plan["authority_config_sha256"],
                expected_helper_sha256=descendant_runner.helper_sha256(),
                expected_task_set_sha256=plan["task_set_sha256"],
                execute=True,
            )
        self.assertEqual(result["status"], "blocked_disk_reserve")
        self.assertEqual(result["upstream_calls"], 0)


if __name__ == "__main__":
    unittest.main()
