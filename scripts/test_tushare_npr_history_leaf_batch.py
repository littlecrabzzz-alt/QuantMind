"""NPR leaf batches admit exactly six new history logical requests."""

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
from scripts import prepare_tushare_npr_history_leaf_batch as preparation
from scripts import run_tushare_npr_history_leaf_batch as runner


class NprHistoryLeafBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        self.catalog = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = pipeline_module.Pipeline(self.root, self.catalog)
        windows = [
            ("2008-03-16 12:00:00", "2008-03-24 06:00:00"),
            ("2008-03-24 06:00:00", "2008-04-01 00:00:00"),
            ("2018-12-16 12:00:00", "2018-12-24 06:00:00"),
            ("2018-12-24 06:00:00", "2019-01-01 00:00:00"),
            ("2019-10-16 12:00:00", "2019-10-24 06:00:00"),
            ("2019-10-24 06:00:00", "2019-11-01 00:00:00"),
        ]
        self.children = []
        for index in range(0, len(windows), 2):
            parent = pipeline.enqueue(
                "npr",
                {
                    "start_date": windows[index][0],
                    "end_date": windows[index + 1][1],
                },
                epoch="history",
            )
            pair = [
                pipeline.enqueue(
                    "npr",
                    {"start_date": start, "end_date": end},
                    epoch="history",
                )
                for start, end in windows[index : index + 2]
            ]
            self.children.extend(pair)
            pipeline.db.executemany(
                "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
                [(parent, child) for child in pair],
            )
            pipeline.db.execute(
                "INSERT INTO partition_splits("
                "parent_id,method,expected_children,coverage_proven,evidence,status,gap"
                ") VALUES(?,?,?,?,?,?,?)",
                (parent, "date_bisection", 2, 1, "{}", "complete", None),
            )

        excluded_parent = pipeline.enqueue(
            "npr",
            {
                "start_date": "2020-01-01 00:00:00",
                "end_date": "2020-02-01 00:00:00",
            },
            epoch="history",
        )
        self.attempted_logical = pipeline.enqueue(
            "npr",
            {
                "start_date": "2020-01-01 00:00:00",
                "end_date": "2020-01-16 12:00:00",
            },
            epoch="history",
        )
        attempted_refresh = pipeline.enqueue(
            "npr",
            {
                "start_date": "2020-01-01 00:00:00",
                "end_date": "2020-01-16 12:00:00",
            },
            epoch="20260911",
        )
        self.unattempted_refresh = pipeline.enqueue(
            "npr",
            {
                "start_date": "2020-01-16 12:00:00",
                "end_date": "2020-02-01 00:00:00",
            },
            epoch="20260911",
        )
        pipeline.db.executemany(
            "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
            [
                (excluded_parent, self.attempted_logical),
                (excluded_parent, self.unattempted_refresh),
            ],
        )
        pipeline.db.execute(
            "INSERT INTO partition_splits("
            "parent_id,method,expected_children,coverage_proven,evidence,status,gap"
            ") VALUES(?,?,?,?,?,?,?)",
            (excluded_parent, "date_bisection", 2, 1, "{}", "complete", None),
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted_refresh, 1, "{}"),
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
        )
        self.manifest_sha = preparation.sha(self.output)
        self.manifest = preparation.verify_manifest(
            self.output, self.manifest_sha
        )

    def test_prepare_selects_exactly_six_new_history_leaves(self):
        task_ids = {record["task_id"] for record in self.manifest["records"]}
        self.assertEqual(self.manifest["api_counts"], {"npr": 6})
        self.assertEqual(task_ids, set(self.children))
        self.assertNotIn(self.attempted_logical, task_ids)
        self.assertNotIn(self.unattempted_refresh, task_ids)
        self.assertTrue(
            all(
                record["epoch"] == "history"
                and record["attempts"] == 0
                and record["tries"] == 0
                and record["state"] == "pending"
                and record["parent_ids"]
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

    def test_prepare_refreezes_after_leaf_inventory_drifts(self):
        pipeline = pipeline_module.Pipeline(self.root, self.catalog)
        parent = pipeline.enqueue(
            "npr",
            {
                "start_date": "2021-01-01 00:00:00",
                "end_date": "2021-02-01 00:00:00",
            },
            epoch="history",
        )
        child = pipeline.enqueue(
            "npr",
            {
                "start_date": "2021-01-01 00:00:00",
                "end_date": "2021-01-16 12:00:00",
            },
            epoch="history",
        )
        pipeline.db.execute(
            "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
            (parent, child),
        )
        pipeline.db.execute(
            "INSERT INTO partition_splits("
            "parent_id,method,expected_children,coverage_proven,evidence,status,gap"
            ") VALUES(?,?,?,?,?,?,?)",
            (parent, "date_bisection", 1, 1, "{}", "complete", None),
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (self.children[0], 1, "{}"),
        )
        pipeline.db.commit()
        pipeline.close()
        drift = self.base / "drift.json"
        preparation.prepare(
            self.root,
            drift,
            self.release_id,
            self.release_sha,
        )
        manifest = json.loads(drift.read_bytes())
        task_ids = {record["task_id"] for record in manifest["records"]}
        self.assertEqual(len(task_ids), 6)
        self.assertNotIn(self.children[0], task_ids)
        self.assertIn(child, task_ids)
        self.assertEqual(
            manifest["source"]["frozen_task_ids_sha256"],
            manifest["all_task_ids_sha256"],
        )

    def test_plan_only_is_offline_and_does_not_access_authority(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        result = runner.run_batch(
            self.output, self.manifest_sha, root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)

    def test_execute_rechecks_logical_attempts(self):
        pipeline = pipeline_module.Pipeline(self.root, self.catalog)
        duplicate = pipeline.enqueue(
            "npr",
            self.manifest["records"][0]["job"]["params"],
            epoch="refresh-after-freeze",
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (duplicate, 1, "{}"),
        )
        pipeline.db.commit()
        pipeline.close()
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        db.row_factory = sqlite3.Row
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
                max_requests=360,
                max_seconds=90,
                execute=True,
            )
        self.assertEqual(calls, ["npr"] * 6)
        self.assertEqual(result["upstream_calls"], 6)
        self.assertEqual(result["max_upstream_calls"], 360)
        self.assertEqual(result["max_seconds"], 90)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)


if __name__ == "__main__":
    unittest.main()
