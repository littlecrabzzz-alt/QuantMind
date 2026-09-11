"""fina_mainbz exact batches retain company, report-window and type identity."""

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_fina_mainbz_batch as preparation
from scripts import run_tushare_fina_mainbz_batch as runner


class FinaMainbzBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.tasks = []
        for year in (2024, 2023):
            for kind in preparation.TYPES:
                for _market, code in (
                    ("SH", "600001.SH"),
                    ("SZ", "000001.SZ"),
                    ("BJ", "920001.BJ"),
                ):
                    self.tasks.append(
                        pipeline.enqueue(
                            preparation.API,
                            {
                                "ts_code": code,
                                "type": kind,
                                "start_date": f"{year}0101",
                                "end_date": f"{year}1231",
                            },
                            priority=40,
                            epoch=preparation.EPOCH,
                        )
                    )
        attempted = self.tasks[0]
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted, 1, '{"status":"transport_error"}'),
        )
        self.unrelated = pipeline.enqueue(
            "fina_audit",
            {"ts_code": "600999.SH"},
            priority=40,
            epoch="history",
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").touch()
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_bytes(json_bytes(self.config))
        release_bytes = json_bytes({"datasets": [], "files": {}})
        self.release_sha = digest(release_bytes)
        self.release_id = "data-" + self.release_sha
        release = self.root / "releases" / self.release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(release_bytes)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {"manifest_sha256": self.release_sha, "release_id": self.release_id}
            )
        )
        self.output = self.base / "batch.json"
        preparation.prepare(
            self.root, self.output, self.release_id, self.release_sha, jobs=9
        )
        self.manifest_sha = preparation.sha(self.output)
        self.manifest = preparation.verify_manifest(self.output, self.manifest_sha)

    def test_prepare_is_read_only_pristine_and_semantically_balanced(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        copy = self.base / "copy.json"
        preparation.prepare(self.root, copy, self.release_id, self.release_sha, jobs=9)
        self.assertEqual(copy.read_bytes(), self.output.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        self.assertEqual(
            self.manifest["selected"]["type_counts"], {"D": 3, "I": 3, "P": 3}
        )
        self.assertEqual(
            self.manifest["selected"]["market_counts"], {"BJ": 3, "SH": 3, "SZ": 3}
        )
        self.assertEqual(self.manifest["selected"]["report_period_end_min"], "20231231")
        self.assertEqual(self.manifest["selected"]["report_period_end_max"], "20241231")
        self.assertTrue(all(row["attempts"] == 0 for row in self.manifest["records"]))
        self.assertEqual(
            self.manifest["rate_contracts"],
            {
                "account": {"rpm": 500, "source": "configured_shared_gate"},
                "api": {"rpm": 500, "source": "points_regular_allowlist_doc290"},
            },
        )
        self.assertFalse(self.manifest["boundaries"]["pit_verified"])
        self.assertFalse(self.manifest["boundaries"]["known_at_verified"])

    def test_plan_only_needs_no_authority_credentials_network_or_writes(self):
        result = runner.run_batch(
            self.output, self.manifest_sha, root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 9)
        self.assertEqual(
            result["eligible_task_ids_sha256"],
            self.manifest["source"]["eligible_task_ids_sha256"],
        )
        for field in (
            "would_access_authority",
            "would_access_credentials",
            "would_call_upstream",
            "would_write",
            "would_publish",
        ):
            self.assertFalse(result[field])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.output, "0" * 64)

    def test_rate_and_release_changes_fail_closed(self):
        limited = dict(self.config, api_requests_per_minute={preparation.API: 200})
        with self.assertRaisesRegex(ValueError, "rate contract"):
            preparation.rate_contracts(limited)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes({"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64})
        )
        with self.assertRaisesRegex(ValueError, "no longer CURRENT"):
            runner._verify_release(self.root, self.manifest)

    def test_execute_is_exact_bounded_and_does_not_publish(self):
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": body["fields"].split(","), "items": []},
                },
            )

        pointer = (self.root / "CURRENT.json").read_bytes()
        client = httpx.Client(transport=httpx.MockTransport(respond))
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority"),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.httpx, "Client", return_value=client),
            patch.object(
                runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=runner.MIN_FREE_BYTES + 1),
            ),
        ):
            result = runner.run_batch(
                self.output,
                self.manifest_sha,
                expected_task_ids_sha256=self.manifest["all_task_ids_sha256"],
                expected_config_sha256=self.manifest["source"][
                    "authority_config_sha256"
                ],
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                root=self.root,
                max_requests=3,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(item["api_name"] == preparation.API for item in requests))
        expected_params = {"ts_code", "type", "start_date", "end_date"}
        self.assertTrue(
            all(set(item["params"]) == expected_params for item in requests)
        )
        self.assertEqual(result["upstream_calls"], 3)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
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

    def test_execute_rejects_changed_eligible_inventory(self):
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        pipeline.enqueue(
            preparation.API,
            {
                "ts_code": "600099.SH",
                "type": "P",
                "start_date": "20220101",
                "end_date": "20221231",
            },
            priority=40,
            epoch=preparation.EPOCH,
        )
        pipeline.db.commit()
        pipeline.close()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority"),
        ):
            with self.assertRaisesRegex(ValueError, "eligible task inventory changed"):
                runner.run_batch(
                    self.output,
                    self.manifest_sha,
                    expected_task_ids_sha256=self.manifest["all_task_ids_sha256"],
                    expected_config_sha256=self.manifest["source"][
                        "authority_config_sha256"
                    ],
                    expected_helper_sha256=runner.helper_sha256(),
                    expected_preparation_sha256=runner.preparation_sha256(),
                    expected_release_id=self.release_id,
                    expected_release_manifest_sha256=self.release_sha,
                    root=self.root,
                    execute=True,
                )


if __name__ == "__main__":
    unittest.main()
