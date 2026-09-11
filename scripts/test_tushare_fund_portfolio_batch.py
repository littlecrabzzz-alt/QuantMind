import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_fund_portfolio_batch as preparation
from scripts import run_tushare_fund_portfolio_batch as runner


class FundPortfolioBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)

        def enqueue(code, **params):
            return pipeline.enqueue(
                preparation.API,
                {"ts_code": code, **params},
                priority=60,
                epoch=preparation.EPOCH,
            )

        self.a_late_period = enqueue(
            "510300.SH", period="20261231", ann_date="20250101"
        )
        self.a_new_publication = enqueue(
            "510300.SH", period="20250930", ann_date="20251030"
        )
        self.b_new = enqueue("159919.SZ", period="20240930")
        self.b_old = enqueue("159919.SZ", period="20240630")

        self.split_parent = enqueue("510500.SH", period="20250331")
        self.split_children = [
            enqueue("510500.SH", period="20250331", symbol="600000.SH"),
            enqueue("510500.SH", period="20250331", symbol="000001.SZ"),
        ]
        pipeline.record_partition(
            self.split_parent,
            self.split_children,
            "identifier_fanout",
            False,
            {"origin": "fixture", "universe_complete": False},
        )
        self.filler = enqueue("512000.SH", period="20231231")

        self.attempted_history = enqueue("588000.SH", period="20250630")
        attempted_sibling = pipeline.enqueue(
            preparation.API,
            {"ts_code": "588000.SH", "period": "20250630"},
            priority=30,
            epoch="20260901",
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted_sibling, 1, '{"status":"transport_error"}'),
        )

        self.terminal_history = enqueue("513100.SH", period="20250331")
        terminal_sibling = pipeline.enqueue(
            preparation.API,
            {"ts_code": "513100.SH", "period": "20250331"},
            priority=30,
            epoch="20260908",
        )
        pipeline.db.execute(
            "UPDATE jobs SET state='empty',tries=1 WHERE id=?", (terminal_sibling,)
        )
        self.recent_only = pipeline.enqueue(
            preparation.API,
            {"ts_code": "513500.SH", "period": "20250630"},
            priority=30,
            epoch="20260908",
        )
        self.unrelated = pipeline.enqueue(
            "daily", {"trade_date": "20260901"}, priority=25, epoch="history"
        )
        pipeline.db.commit()
        pipeline.close()

        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").touch()
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
            "api_requests_per_minute": {preparation.API: 240},
        }
        (self.root / "pipeline-config.json").write_bytes(json_bytes(self.config))
        release_manifest = json_bytes({"datasets": [], "files": {}})
        self.release_sha = digest(release_manifest)
        self.release_id = "data-" + self.release_sha
        release = self.root / "releases" / self.release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(release_manifest)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {"manifest_sha256": self.release_sha, "release_id": self.release_id}
            )
        )
        self.output = self.base / "batch.json"

    def tearDown(self):
        self.temp.cleanup()

    def _prepare(self, jobs=4):
        return preparation.prepare(
            self.root, self.output, self.release_id, self.release_sha, jobs
        )

    def test_prepare_preserves_pit_boundary_and_is_fair_across_funds(self):
        database_before = preparation.sha(self.root / "pipeline.sqlite")
        manifest = self._prepare()
        task_ids = {record["task_id"] for record in manifest["records"]}
        codes = [record["job"]["params"]["ts_code"] for record in manifest["records"]]

        self.assertEqual(manifest["source"]["eligible_jobs"], 7)
        self.assertEqual(manifest["source"]["eligible_funds"], 4)
        self.assertEqual(manifest["selected"]["unique_funds"], 4)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertIn(self.a_new_publication, task_ids)
        self.assertNotIn(self.a_late_period, task_ids)
        self.assertEqual(
            manifest["selected"]["selection_counts"]["split_child_leaf"], 1
        )
        self.assertTrue(
            manifest["boundaries"]["period_is_report_period_not_availability_time"]
        )
        self.assertFalse(manifest["boundaries"]["pit_verified"])
        self.assertEqual(
            preparation.sha(self.root / "pipeline.sqlite"), database_before
        )
        self.assertEqual(manifest["source"]["rate_gate"]["api_rpm"], 240)

    def test_cross_epoch_attempts_terminal_siblings_and_split_parents_are_excluded(
        self,
    ):
        manifest = self._prepare()
        task_ids = {record["task_id"] for record in manifest["records"]}
        self.assertNotIn(self.attempted_history, task_ids)
        self.assertNotIn(self.terminal_history, task_ids)
        self.assertNotIn(self.split_parent, task_ids)
        self.assertNotIn(self.recent_only, task_ids)
        self.assertEqual(sum(task_id in task_ids for task_id in self.split_children), 1)

    def test_next_round_waits_for_each_fund_and_prefers_split_leaves(self):
        manifest = self._prepare(jobs=6)
        records = manifest["records"]
        task_ids = {record["task_id"] for record in records}
        self.assertEqual(
            len({record["job"]["params"]["ts_code"] for record in records[:4]}),
            4,
        )
        self.assertTrue(set(self.split_children).issubset(task_ids))
        self.assertIn(self.a_late_period, task_ids)
        self.assertNotIn(self.b_old, task_ids)

    def test_plan_only_has_zero_external_and_write_access(self):
        manifest = self._prepare()
        result = runner.run_batch(
            self.output, preparation.sha(self.output), root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 4)
        self.assertEqual(result["rate_gate"]["account_rpm"], 500)
        for key in (
            "would_access_authority",
            "would_access_credentials",
            "would_call_upstream",
            "would_write",
            "would_publish",
        ):
            self.assertFalse(result[key])
        self.assertEqual(
            manifest["source"]["preparation_sha256"], runner.preparation_sha256()
        )
        for value in (
            preparation.sha(self.output),
            manifest["all_task_ids_sha256"],
            manifest["source"]["authority_config_sha256"],
            runner.helper_sha256(),
            runner.preparation_sha256(),
            manifest["source"]["release_manifest_sha256"],
        ):
            self.assertRegex(value, r"^[a-f0-9]{64}$")

    def test_execute_is_exact_bounded_and_does_not_publish(self):
        manifest = self._prepare(jobs=3)
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body["api_name"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": body["fields"].split(","), "items": []},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(respond))
        pointer = (self.root / "CURRENT.json").read_bytes()
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
                preparation.sha(self.output),
                expected_task_ids_sha256=manifest["all_task_ids_sha256"],
                expected_config_sha256=manifest["source"]["authority_config_sha256"],
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                root=self.root,
                max_requests=3,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(calls, [preparation.API] * 3)
        self.assertEqual(result["upstream_calls"], 3)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        with closing(sqlite3.connect(self.root / "pipeline.sqlite")) as db:
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

    def test_manifest_and_execute_pins_fail_closed(self):
        self._prepare()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            preparation.verify_manifest(self.output, "0" * 64)
        with self.assertRaisesRegex(ValueError, "1 to 360"):
            runner.run_batch(
                self.output, preparation.sha(self.output), max_requests=361
            )
        with self.assertRaisesRegex(ValueError, "at most 90"):
            runner.run_batch(self.output, preparation.sha(self.output), max_seconds=91)
        with self.assertRaisesRegex(ValueError, "Execute requires pinned"):
            runner.run_batch(self.output, preparation.sha(self.output), execute=True)


if __name__ == "__main__":
    unittest.main()
