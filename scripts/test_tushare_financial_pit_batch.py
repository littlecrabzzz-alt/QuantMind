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
import run_tushare_financial_pit_batch as runner


class FinancialPitBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
        )
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
                db.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'").fetchone()[0],
                10,
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
        finally:
            db.close()

    def test_plan_only_verifies_hashes_without_authority_or_credentials(self):
        result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
        self.assertFalse(result["would_access_authority"])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)

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


if __name__ == "__main__":
    unittest.main()
