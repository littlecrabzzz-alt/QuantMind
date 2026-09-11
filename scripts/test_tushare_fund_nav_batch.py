"""fund_nav batches pin existing history tasks and preserve evidence boundaries."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_fund_nav_batch as preparation
import run_tushare_fund_nav_batch as runner


class FundNavBatchTests(unittest.TestCase):
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
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.parent = pipeline.enqueue(
            "fund_nav",
            {"ts_code": "000001.OF", "start_date": "19900101", "end_date": "20260901"},
            priority=45,
            epoch="history",
        )
        children = []
        for code, start, end in (
            ("000001.OF", "19900101", "20081231"),
            ("000001.OF", "20090101", "20260901"),
        ):
            children.append(
                pipeline.enqueue(
                    "fund_nav",
                    {"ts_code": code, "start_date": start, "end_date": end},
                    priority=45,
                    epoch="history",
                )
            )
        pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (self.parent,)
        )
        pipeline.db.execute(
            "INSERT INTO partition_splits(parent_id,method,expected_children,coverage_proven,evidence,status,gap) "
            "VALUES(?,?,?,?,?,?,?)",
            (self.parent, "date_bisection", 2, 0, "{}", "gap", "child_not_verified"),
        )
        pipeline.db.executemany(
            "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
            [(self.parent, child) for child in children],
        )
        for number in range(2, 7):
            pipeline.enqueue(
                "fund_nav",
                {
                    "ts_code": f"{number:06d}.OF",
                    "start_date": "19900101",
                    "end_date": "20260901",
                },
                priority=45,
                epoch="history",
            )
        pipeline.enqueue(
            "fund_nav",
            {"ts_code": "000099.OF", "start_date": "20260903", "end_date": "20260909"},
            priority=25,
            epoch="20260910",
        )
        self.unrelated = pipeline.enqueue(
            "fund_share", {"trade_date": "20260909", "market": "SH"}, epoch="history"
        )
        self._capture_fund_basic(
            pipeline,
            [
                ["000001.OF", "O", "L", "20000101", "20300101", None],
                ["000002.OF", "O", "D", "20010101", "20200101", "20200102"],
            ],
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
        preparation.prepare(self.root, self.manifest, jobs=4)
        self.manifest_sha = preparation.sha(self.manifest)
        self.verified = preparation.verify_manifest(self.manifest, self.manifest_sha)

    def _capture_fund_basic(self, pipeline, items):
        task = pipeline.enqueue("fund_basic", {"market": "O"}, epoch="discovery")
        body = preparation.json_bytes(
            {
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "market",
                        "status",
                        "list_date",
                        "due_date",
                        "delist_date",
                    ],
                    "items": items,
                },
            }
        )
        object_sha = preparation.digest(body)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / f"{object_sha}.json").write_bytes(body)
        result = {"status": "sample_ok", "object_sha256": object_sha}
        pipeline.db.execute(
            "UPDATE jobs SET state='done',result=? WHERE id=?",
            (json.dumps(result), task),
        )

    def test_prepare_prioritizes_split_leaves_and_preserves_universe_gaps(self):
        self.assertEqual(
            self.verified["selection_counts"],
            {"pending_history_root": 2, "pending_split_leaf": 2},
        )
        self.assertEqual(self.verified["api_counts"], {"fund_nav": 4})
        self.assertEqual(self.verified["universe"]["observed_fund_basic_codes"], 2)
        self.assertGreater(
            self.verified["universe"]["planned_codes_not_observed_in_fund_basic"], 0
        )
        split_ids = {
            task_id
            for task_id, reason in self.verified["selection_reasons"].items()
            if reason == "pending_split_leaf"
        }
        self.assertEqual(len(split_ids), 2)
        context = {row["ts_code"]: row for row in self.verified["selected_funds"]}
        self.assertEqual(context["000001.OF"]["due_date"], "20300101")
        self.assertFalse(context["000003.OF"]["observed_in_fund_basic"])
        self.assertIn(
            "first became knowable", self.verified["boundaries"]["point_in_time"]
        )

    def test_prepare_is_read_only_and_plan_only_uses_no_authority_or_credentials(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        second = self.base / "same.json"
        preparation.prepare(self.root, second, jobs=4)
        self.assertEqual(second.read_bytes(), self.manifest.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 4)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_write"])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)
        with self.assertRaisesRegex(ValueError, "preparation hash mismatch"):
            runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_preparation_sha256="0" * 64,
            )

    def test_execute_is_exact_bounded_and_does_not_publish(self):
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
                max_requests=2,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(calls, ["fund_nav", "fund_nav"])
        self.assertEqual(result["upstream_calls"], 2)
        self.assertFalse(result["release_published"])
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

    def test_execute_rejects_a_stale_task_before_reading_credentials(self):
        task_id = self.verified["records"][0]["task_id"]
        with closing(sqlite3.connect(self.root / "pipeline.sqlite")) as db:
            with db:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (task_id,))
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret") as secret,
        ):
            with self.assertRaisesRegex(ValueError, "no longer pending"):
                runner.run_batch(
                    self.manifest,
                    self.manifest_sha,
                    expected_task_ids_sha256=self.verified["all_task_ids_sha256"],
                    expected_config_sha256=runner.sha(self.config_path),
                    expected_helper_sha256=runner.helper_sha256(),
                    expected_preparation_sha256=runner.preparation_sha256(),
                    root=self.root,
                    execute=True,
                )
        secret.assert_not_called()


if __name__ == "__main__":
    unittest.main()
