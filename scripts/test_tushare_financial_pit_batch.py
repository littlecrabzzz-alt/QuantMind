"""Financial PIT batches pin existing leaves and execute only that scope."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_financial_pit_batch as preparation
import prepare_tushare_financial_recovery_batch as recovery
import run_tushare_financial_pit_batch as runner


class FinancialPitBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        self.catalog = catalog
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.selected = []
        for api in preparation.ALLOWED_APIS:
            for number in range(3):
                self.selected.append(
                    pipeline.enqueue(
                        api,
                        {
                            "ts_code": f"{number + 1:06d}.SZ",
                            "period": "20260630",
                            "report_type": "1",
                        },
                        priority=26,
                        epoch="20260910",
                    )
                )
        self.unrelated = pipeline.enqueue(
            "forecast_vip",
            {"ts_code": "000999.SZ", "period": "20260630"},
            priority=1,
            epoch="20260910",
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").write_text("enabled\n")
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_text(json.dumps(self.config))
        (self.root / "CURRENT.json").write_text('{"release_id":"unchanged"}\n')
        self.manifest = self.base / "batch.json"
        preparation.prepare(self.root, self.manifest, "20260910", jobs_per_api=2)
        self.manifest_sha = preparation.sha(self.manifest)
        self.verified = preparation.verify_manifest(self.manifest, self.manifest_sha)

    def test_prepare_selects_balanced_existing_leaf_tasks_and_is_read_only(self):
        self.assertEqual(
            self.verified["api_counts"],
            {"balancesheet_vip": 2, "cashflow_vip": 2, "income_vip": 2},
        )
        self.assertEqual(len(self.verified["records"]), 6)
        identities = {
            api: {
                (
                    row["job"]["params"]["period"],
                    row["job"]["params"]["report_type"],
                    row["job"]["params"]["ts_code"],
                )
                for row in self.verified["records"]
                if row["job"]["api_name"] == api
            }
            for api in preparation.ALLOWED_APIS
        }
        self.assertEqual(len({frozenset(values) for values in identities.values()}), 1)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE state='pending'"
                ).fetchone()[0],
                10,
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0
            )
        finally:
            db.close()

    def test_plan_only_verifies_hashes_without_authority_or_credentials(self):
        result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])
        self.assertEqual(result["preparation_sha256"], runner.preparation_sha256())

        legacy_manifest = self.base / "legacy-batch.json"
        legacy = json.loads(self.manifest.read_bytes())
        legacy["source"]["selection"] = "latest_period_common_code_specific_leaves"
        legacy_manifest.write_bytes(preparation.json_bytes(legacy))
        legacy_result = runner.run_batch(
            legacy_manifest, preparation.sha(legacy_manifest)
        )
        self.assertEqual(legacy_result["status"], "plan_only")

        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)
        with self.assertRaisesRegex(ValueError, "preparation hash mismatch"):
            runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_preparation_sha256="0" * 64,
            )

    def test_prepare_balances_markets_and_skips_cross_epoch_logical_duplicates(self):
        root = self.base / "balanced-authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(root, catalog)
        codes = (
            "600001.SH",
            "600002.SH",
            "000001.SZ",
            "000002.SZ",
            "920001.BJ",
            "920002.BJ",
        )
        for api in preparation.ALLOWED_APIS:
            for code in codes:
                pipeline.enqueue(
                    api,
                    {"ts_code": code, "period": "20260630", "report_type": "1"},
                    priority=26,
                    epoch="20260910",
                )
            pipeline.enqueue(
                api,
                {"ts_code": "600001.SH", "period": "20260630", "report_type": "1"},
                priority=26,
                epoch="20260909",
            )
            duplicate = pipeline.enqueue(
                api,
                {"ts_code": "000001.SZ", "period": "20260630", "report_type": "1"},
                priority=26,
                epoch="20260911",
            )
            pipeline.db.execute("UPDATE jobs SET state='done' WHERE id=?", (duplicate,))
        pipeline.db.commit()
        pipeline.close()

        manifest = self.base / "balanced-batch.json"
        result = preparation.prepare(root, manifest, "20260910", jobs_per_api=3)
        selected = {row["job"]["params"]["ts_code"] for row in result["records"]}
        self.assertEqual(selected, {"600002.SH", "000002.SZ", "920001.BJ"})
        self.assertEqual(
            result["source"]["selection"],
            preparation.SELECTION_MODE,
        )

    def test_prepare_does_not_require_cross_api_common_leaves(self):
        root = self.base / "disjoint-authority"
        pipeline = runner.pipeline_module.Pipeline(root, self.catalog)
        for api_number, api in enumerate(preparation.ALLOWED_APIS):
            for code_number in range(2):
                pipeline.enqueue(
                    api,
                    {
                        "ts_code": f"{api_number + 1}{code_number + 1:05d}.SZ",
                        "period": "20260630",
                        "report_type": "1",
                    },
                    priority=26,
                    epoch="20260910",
                )
        pipeline.db.commit()
        pipeline.close()

        manifest = self.base / "disjoint-batch.json"
        result = preparation.prepare(root, manifest, "20260910", jobs_per_api=2)
        self.assertEqual(
            result["api_counts"],
            {"balancesheet_vip": 2, "cashflow_vip": 2, "income_vip": 2},
        )
        identities = {
            api: {
                row["job"]["params"]["ts_code"]
                for row in result["records"]
                if row["job"]["api_name"] == api
            }
            for api in preparation.ALLOWED_APIS
        }
        self.assertEqual(len(set.union(*identities.values())), 6)
        self.assertEqual(len(set.intersection(*identities.values())), 0)

    def test_prepare_keeps_available_api_work_when_another_is_empty(self):
        root = self.base / "partial-authority"
        pipeline = runner.pipeline_module.Pipeline(root, self.catalog)
        for api in preparation.ALLOWED_APIS[:2]:
            pipeline.enqueue(
                api,
                {
                    "ts_code": "600001.SH",
                    "period": "20260630",
                    "report_type": "1",
                },
                priority=26,
                epoch="20260910",
            )
        pipeline.db.commit()
        pipeline.close()

        manifest = self.base / "partial-batch.json"
        result = preparation.prepare(root, manifest, "20260910", jobs_per_api=2)
        self.assertEqual(
            result["api_counts"], {"balancesheet_vip": 1, "income_vip": 1}
        )
        self.assertEqual(len(result["records"]), 2)
        runner_plan = runner.run_batch(manifest, preparation.sha(manifest))
        self.assertEqual(runner_plan["status"], "plan_only")
        self.assertEqual(runner_plan["verified_jobs"], 2)

    def test_history_uses_date_pending_but_skips_date_terminal_duplicate(self):
        root = self.base / "history-authority"
        pipeline = runner.pipeline_module.Pipeline(root, self.catalog)
        for api in preparation.ALLOWED_APIS:
            for number in range(121):
                params = {
                    "ts_code": f"{number + 1:06d}.SZ",
                    "period": "20191231",
                    "report_type": "1",
                }
                pipeline.enqueue(api, params, priority=45, epoch="history")
                if number == 0:
                    pipeline.enqueue(api, params, priority=25, epoch="20260910")
                elif number == 1:
                    duplicate = pipeline.enqueue(
                        api, params, priority=25, epoch="20260910"
                    )
                    pipeline.db.execute(
                        "UPDATE jobs SET state='done' WHERE id=?", (duplicate,)
                    )
        pipeline.db.commit()
        pipeline.close()

        manifest = self.base / "history-batch.json"
        result = preparation.prepare(root, manifest, "history", jobs_per_api=120)
        self.assertEqual(
            result["api_counts"],
            {"balancesheet_vip": 120, "cashflow_vip": 120, "income_vip": 120},
        )
        self.assertEqual(len(result["records"]), 360)
        self.assertEqual({row["epoch"] for row in result["records"]}, {"history"})
        codes = {row["job"]["params"]["ts_code"] for row in result["records"]}
        self.assertIn("000001.SZ", codes)
        self.assertNotIn("000002.SZ", codes)
        self.assertIn("000121.SZ", codes)
        plan = runner.run_batch(manifest, preparation.sha(manifest))
        self.assertEqual(plan["status"], "plan_only")
        self.assertEqual(plan["verified_jobs"], 360)

    def test_date_epoch_skips_retriable_history_task_after_an_attempt(self):
        root = self.base / "history-attempt-authority"
        pipeline = runner.pipeline_module.Pipeline(root, self.catalog)
        for api in preparation.ALLOWED_APIS:
            duplicate_params = {
                "ts_code": "000001.SZ",
                "period": "20260630",
                "report_type": "1",
            }
            pipeline.enqueue(api, duplicate_params, priority=25, epoch="20260910")
            history_task = pipeline.enqueue(
                api, duplicate_params, priority=45, epoch="history"
            )
            pipeline.db.execute(
                "UPDATE jobs SET tries=1 WHERE id=?", (history_task,)
            )
            pipeline.db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
                (history_task, 1, "{}"),
            )
            pipeline.enqueue(
                api,
                {
                    "ts_code": "000002.SZ",
                    "period": "20260630",
                    "report_type": "1",
                },
                priority=25,
                epoch="20260910",
            )
        pipeline.db.commit()
        pipeline.close()

        manifest = self.base / "date-after-history-attempt.json"
        result = preparation.prepare(root, manifest, "20260910", jobs_per_api=1)
        self.assertEqual(
            {row["job"]["params"]["ts_code"] for row in result["records"]},
            {"000002.SZ"},
        )

    def test_prepare_rejects_unknown_epoch_labels(self):
        for epoch in ("recent", "HISTORY", "2026091", "202609100"):
            with self.subTest(epoch=epoch):
                with self.assertRaisesRegex(ValueError, "YYYYMMDD or history"):
                    preparation.prepare(
                        self.root, self.base / "invalid.json", epoch, jobs_per_api=1
                    )

    def test_execute_is_api_fair_exact_bounded_and_does_not_publish(self):
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body["api_name"])
            fields = body["fields"].split(",")
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": []}}
            )

        client = httpx.Client(transport=httpx.MockTransport(respond))
        pointer = (self.root / "CURRENT.json").read_bytes()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.httpx, "Client", return_value=client),
        ):
            result = runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_task_ids_sha256=self.verified["all_task_ids_sha256"],
                expected_config_sha256=runner.sha(self.config_path),
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                root=self.root,
                max_requests=3,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(set(calls), set(preparation.ALLOWED_APIS))
        self.assertEqual(result["upstream_calls"], 3)
        self.assertFalse(result["release_published"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (self.unrelated,)
                ).fetchone()[0],
                "pending",
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (self.unrelated,)
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def _mark_done_and_attempted(self):
        done = self.verified["records"][0]
        attempted = next(
            row
            for row in self.verified["records"]
            if row["job"]["api_name"] == "cashflow_vip"
        )
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (done["task_id"],))
            db.execute("UPDATE jobs SET tries=1 WHERE id=?", (attempted["task_id"],))
            db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
                (attempted["task_id"], 1, '{"status":"transport_error"}'),
            )
            db.commit()
        finally:
            db.close()
        return done, attempted

    def test_recovery_defaults_to_rejecting_pending_attempts(self):
        self._mark_done_and_attempted()
        output = self.base / "recovery-rejected.json"
        with self.assertRaisesRegex(ValueError, "outside authority"):
            recovery.prepare(
                self.root,
                self.manifest,
                self.manifest_sha,
                self.root / "forbidden.json",
                apis=["income_vip"],
            )
        with self.assertRaisesRegex(ValueError, "explicit exclusion: 1"):
            recovery.prepare(
                self.root, self.manifest, self.manifest_sha, output
            )
        self.assertFalse(output.exists())

    def test_recovery_filters_only_original_pristine_tasks_with_lineage(self):
        done, attempted = self._mark_done_and_attempted()
        output = self.base / "recovery.json"
        database = self.root / "pipeline.sqlite"
        database_sha = preparation.sha(database)
        with (
            patch(
                "socket.socket.connect",
                side_effect=AssertionError("generation must stay offline"),
            ),
            patch(
                "socket.getaddrinfo",
                side_effect=AssertionError("generation must stay offline"),
            ),
            patch(
                "backend.shared.runtime_secrets.get_secret",
                side_effect=AssertionError("generation must not read credentials"),
            ),
        ):
            result = recovery.prepare(
                self.root,
                self.manifest,
                self.manifest_sha,
                output,
                exclude_pending_with_attempts=True,
            )
        self.assertEqual(preparation.sha(database), database_sha)
        selected = {row["task_id"] for row in result["records"]}
        self.assertEqual(len(selected), 4)
        self.assertNotIn(done["task_id"], selected)
        self.assertNotIn(attempted["task_id"], selected)
        self.assertEqual(result["source"]["source_manifest_sha256"], self.manifest_sha)
        self.assertEqual(
            result["all_task_ids_sha256"],
            preparation.digest(preparation.json_bytes(sorted(selected))),
        )
        source_jobs = {
            row["task_id"]: row["job"] for row in self.verified["records"]
        }
        self.assertTrue(
            all(row["job"] == source_jobs[row["task_id"]] for row in result["records"])
        )
        plan = runner.run_batch(output, recovery.sha(output))
        self.assertEqual(plan["status"], "plan_only")
        self.assertEqual(plan["verified_jobs"], 4)
        self.assertFalse(plan["would_access_authority"])
        self.assertFalse(plan["would_access_credentials"])
        self.assertFalse(plan["would_call_upstream"])

    def test_recovery_api_filter_does_not_consider_unselected_attempts(self):
        _done, _attempted = self._mark_done_and_attempted()
        output = self.base / "income-recovery.json"
        result = recovery.prepare(
            self.root,
            self.manifest,
            self.manifest_sha,
            output,
            apis=["income_vip"],
        )
        self.assertEqual(result["api_counts"], {"income_vip": 1})
        self.assertEqual(
            {row["job"]["api_name"] for row in result["records"]}, {"income_vip"}
        )

    def test_execute_rejects_recovery_task_that_gained_an_attempt(self):
        output = self.base / "stale-recovery.json"
        result = recovery.prepare(
            self.root,
            self.manifest,
            self.manifest_sha,
            output,
            apis=["income_vip"],
        )
        task_id = result["records"][0]["task_id"]
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute("UPDATE jobs SET tries=1 WHERE id=?", (task_id,))
            db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
                (task_id, 1, '{}'),
            )
            db.commit()
        finally:
            db.close()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credential access must happen later"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no longer pristine pending"):
                runner.run_batch(
                    output,
                    recovery.sha(output),
                    expected_task_ids_sha256=result["all_task_ids_sha256"],
                    expected_config_sha256=runner.sha(self.config_path),
                    expected_helper_sha256=runner.helper_sha256(),
                    expected_preparation_sha256=runner.preparation_sha256(),
                    root=self.root,
                    max_requests=1,
                    max_seconds=1,
                    execute=True,
                )


if __name__ == "__main__":
    unittest.main()
