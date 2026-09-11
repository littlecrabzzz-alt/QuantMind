"""IRM Q&A batches pin pristine tasks and preserve fixed-release/rate gates."""

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared import tushare_pipeline as pipeline_module
from scripts import prepare_tushare_irm_qa_batch as preparation
from scripts import run_tushare_irm_qa_batch as runner


class IrmQaBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = pipeline_module.Pipeline(self.root, catalog)
        self.tasks = []
        specs = (
            ("irm_qa_sh", {"start_date": "20260910", "end_date": "20260910"}),
            (
                "irm_qa_sh",
                {
                    "pub_start": "2026-09-10 00:00:00",
                    "pub_end": "2026-09-11 00:00:00",
                },
            ),
            ("irm_qa_sz", {"start_date": "20260910", "end_date": "20260910"}),
            (
                "irm_qa_sz",
                {
                    "pub_start": "2026-09-10 00:00:00",
                    "pub_end": "2026-09-11 00:00:00",
                },
            ),
        )
        for api, params in specs:
            for epoch in ("history", "2026091105"):
                self.tasks.append(pipeline.enqueue(api, params, epoch=epoch))
        child = pipeline.enqueue(
            "irm_qa_sh",
            {"start_date": "20260911", "end_date": "20260911"},
            epoch="history",
        )
        pipeline.db.execute(
            "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
            ("fixture-parent", child),
        )
        attempted_params = {"start_date": "20260909", "end_date": "20260909"}
        attempted = pipeline.enqueue("irm_qa_sh", attempted_params, epoch="history")
        pipeline.enqueue("irm_qa_sh", attempted_params, epoch="2026091105")
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted, 1, "{}"),
        )
        tainted = pipeline.enqueue(
            "irm_qa_sh",
            {"start_date": "20260908", "end_date": "20260908"},
            epoch="history",
        )
        pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (tainted,))
        pipeline.enqueue(
            "irm_qa_sz", {"ts_code": "000001.SZ"}, epoch="history"
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "pipeline.lock").touch(exist_ok=True)
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
        release_dir = self.root / "releases" / self.release_id
        release_dir.mkdir(parents=True)
        (release_dir / "manifest.json").write_bytes(release_bytes)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {
                    "manifest_sha256": self.release_sha,
                    "release_id": self.release_id,
                }
            )
        )
        self.output = self.base / "batch.json"
        preparation.prepare(
            self.root, self.output, self.release_id, self.release_sha, jobs=4
        )
        self.manifest_sha = preparation.sha(self.output)
        self.manifest = preparation.verify_manifest(self.output, self.manifest_sha)

    def test_prepare_freezes_distinct_pristine_logical_requests(self):
        self.assertEqual(
            self.manifest["api_counts"], {"irm_qa_sh": 2, "irm_qa_sz": 2}
        )
        self.assertEqual(
            self.manifest["axis_counts"],
            {
                "irm_qa_sh:question": 1,
                "irm_qa_sh:reply": 1,
                "irm_qa_sz:question": 1,
                "irm_qa_sz:reply": 1,
            },
        )
        self.assertEqual(
            self.manifest["logical_request_counts"],
            {"distinct": 4, "duplicate_tasks": 0},
        )
        self.assertEqual(self.manifest["source"]["eligible_tasks"], 5)
        self.assertEqual(self.manifest["source"]["skipped_logical_duplicates"], 0)
        self.assertEqual(
            self.manifest["source"]["excluded_invalid_parameter_tasks"], 1
        )
        self.assertEqual(self.manifest["source"]["excluded_prior_logical_keys"], 1)
        self.assertEqual(
            self.manifest["partition_counts"], {"child": 1, "unsplit": 3}
        )
        self.assertTrue(
            all(row["epoch"] == "history" for row in self.manifest["records"])
        )
        selected_sh_questions = [
            row
            for row in self.manifest["records"]
            if row["job"]["api_name"] == "irm_qa_sh"
            and "start_date" in row["job"]["params"]
        ]
        self.assertEqual(
            selected_sh_questions[0]["job"]["params"]["start_date"], "20260911"
        )
        self.assertEqual(
            self.manifest["api_rate_contracts"],
            {
                "irm_qa_sh": {
                    "rpm": 500,
                    "source": "user_purchased_permission_family",
                },
                "irm_qa_sz": {
                    "rpm": 500,
                    "source": "user_purchased_permission_family",
                },
            },
        )
        self.assertTrue(
            all(
                row["state"] == "pending"
                and row["tries"] == 0
                and row["attempts"] == 0
                for row in self.manifest["records"]
            )
        )

    def test_prepare_and_plan_only_have_no_side_effects_or_network(self):
        database_before = (self.root / "pipeline.sqlite").read_bytes()
        other = self.base / "same.json"
        preparation.prepare(self.root, other, self.release_id, self.release_sha, jobs=4)
        self.assertEqual(other.read_bytes(), self.output.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), database_before)
        result = runner.run_batch(
            self.output, self.manifest_sha, root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 4)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])

    def test_manifest_release_and_rate_tampering_fail_closed(self):
        changed = json.loads(self.output.read_bytes())
        changed["api_rate_contracts"]["irm_qa_sh"]["rpm"] = 499
        tampered = self.base / "tampered.json"
        tampered.write_bytes(json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "Invalid batch manifest"):
            preparation.verify_manifest(tampered, preparation.sha(tampered))

        (self.root / "CURRENT.json").write_bytes(
            json_bytes({"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64})
        )
        with self.assertRaisesRegex(ValueError, "no longer CURRENT"):
            runner._verify_release(self.root, self.manifest)

    def test_execute_requires_all_pins_and_pristine_authority_tasks(self):
        with self.assertRaisesRegex(ValueError, "requires pinned release"):
            runner.run_batch(self.output, self.manifest_sha, execute=True)
        first = self.manifest["records"][0]
        pipeline = SimpleNamespace()
        import sqlite3

        pipeline.db = sqlite3.connect(self.root / "pipeline.sqlite")
        pipeline.db.row_factory = sqlite3.Row
        pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (first["task_id"],))
        pipeline.db.commit()
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            runner._verify_authority_jobs(pipeline, self.manifest["records"])
        pipeline.db.close()

    def test_execute_is_exact_bounded_rate_gated_and_does_not_publish(self):
        calls = []

        def respond(request):
            payload = json.loads(request.content)
            calls.append(payload["api_name"])
            fields = payload["fields"].split(",")
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
                expected_config_sha256=preparation.sha(self.config_path),
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                root=self.root,
                max_requests=4,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(sorted(calls), ["irm_qa_sh"] * 2 + ["irm_qa_sz"] * 2)
        self.assertEqual(result["upstream_calls"], 4)
        self.assertEqual(result["api_rate_contracts"]["irm_qa_sz"]["rpm"], 500)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)


if __name__ == "__main__":
    unittest.main()
