"""Announcement exact batches admit only untouched direct split children."""

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared import tushare_pipeline as pipeline_module
from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_anns_d_batch as preparation
from scripts import run_tushare_anns_d_batch as runner


class AnnouncementBatchTest(unittest.TestCase):
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
        self.parent = pipeline.enqueue(
            "anns_d",
            {"start_date": "20260101", "end_date": "20260131"},
            epoch="history",
        )
        self.children = []
        for start, end in (("20260101", "20260115"), ("20260116", "20260131")):
            self.children.append(
                pipeline.enqueue(
                    "anns_d",
                    {"start_date": start, "end_date": end},
                    epoch="history",
                )
            )
        self.duplicate = pipeline.enqueue(
            "anns_d",
            {"start_date": "20260101", "end_date": "20260115"},
            epoch="20260911",
        )
        attempted = pipeline.enqueue(
            "anns_d",
            {"start_date": "20260201", "end_date": "20260215"},
            epoch="history",
        )
        self.root_only = pipeline.enqueue(
            "anns_d",
            {"start_date": "20260301", "end_date": "20260315"},
            epoch="history",
        )
        pipeline.db.executemany(
            "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
            [
                (self.parent, self.children[0]),
                (self.parent, self.children[1]),
                (self.parent, self.duplicate),
                (self.parent, attempted),
            ],
        )
        pipeline.db.execute(
            "INSERT INTO partition_splits("
            "parent_id,method,expected_children,coverage_proven,evidence,status,gap"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                self.parent,
                "date_bisection",
                4,
                1,
                "{}",
                "complete",
                None,
            ),
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted, 1, "{}"),
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
            self.root,
            self.output,
            self.release_id,
            self.release_sha,
            jobs=2,
        )
        self.manifest_sha = preparation.sha(self.output)
        self.manifest = preparation.verify_manifest(
            self.output, self.manifest_sha
        )

    def test_prepare_selects_unique_unattempted_direct_children(self):
        self.assertEqual(self.manifest["api_counts"], {"anns_d": 2})
        self.assertEqual(
            {record["task_id"] for record in self.manifest["records"]},
            set(self.children),
        )
        self.assertTrue(
            all(
                record["attempts"] == 0
                and record["tries"] == 0
                and record["state"] == "pending"
                and record["parent_ids"] == [self.parent]
                for record in self.manifest["records"]
            )
        )
        self.assertEqual(
            self.manifest["rate_contracts"],
            {
                "account": {"rpm": 500, "source": "configured_shared_gate"},
                "api": {
                    "rpm": 500,
                    "source": "user_purchased_permission_family",
                },
            },
        )

    def test_prepare_and_plan_only_are_read_only_and_offline(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        other = self.base / "same.json"
        preparation.prepare(
            self.root, other, self.release_id, self.release_sha, jobs=2
        )
        self.assertEqual(other.read_bytes(), self.output.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        result = runner.run_batch(
            self.output, self.manifest_sha, root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 2)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])

    def test_manifest_release_rate_and_code_tampering_fail_closed(self):
        changed = json.loads(self.output.read_bytes())
        changed["rate_contracts"]["api"]["rpm"] = 499
        tampered = self.base / "tampered.json"
        tampered.write_bytes(json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "Invalid batch manifest"):
            preparation.verify_manifest(tampered, preparation.sha(tampered))
        with self.assertRaisesRegex(ValueError, "helper hash mismatch"):
            runner.run_batch(
                self.output,
                self.manifest_sha,
                expected_helper_sha256="0" * 64,
            )
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64}
            )
        )
        with self.assertRaisesRegex(ValueError, "no longer CURRENT"):
            runner._verify_release(self.root, self.manifest)

    def test_execute_rechecks_task_and_logical_attempts(self):
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        db.row_factory = sqlite3.Row
        db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (self.duplicate, 1, "{}"),
        )
        db.commit()
        holder = SimpleNamespace(db=db)
        with self.assertRaisesRegex(ValueError, "gained an attempt"):
            runner._verify_authority_jobs(holder, self.manifest["records"])
        db.close()

    def test_execute_is_exact_bounded_and_does_not_publish(self):
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
                max_requests=2,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(calls, ["anns_d", "anns_d"])
        self.assertEqual(result["upstream_calls"], 2)
        self.assertEqual(result["rate_contracts"]["api"]["rpm"], 500)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)


if __name__ == "__main__":
    unittest.main()
