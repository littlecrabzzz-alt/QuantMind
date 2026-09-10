"""fund_share exact batches are offline by default and bounded on execute."""

from contextlib import closing
import json
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_fund_share_batch as preparation
import run_tushare_fund_share_batch as runner


class FundShareBatchTests(unittest.TestCase):
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
        for day in ("20260901", "20260902", "20260903", "20260904"):
            for market in preparation.MARKETS:
                pipeline.enqueue(
                    preparation.API,
                    {"market": market, "trade_date": day},
                    priority=45,
                    epoch=preparation.EPOCH,
                )
        self.recent = pipeline.enqueue(
            preparation.API,
            {"market": "SH", "trade_date": "20260909"},
            priority=25,
            epoch="20260910",
        )
        self.unrelated = pipeline.enqueue(
            "fund_nav",
            {
                "ts_code": "510300.SH",
                "start_date": "20260901",
                "end_date": "20260909",
            },
            priority=1,
            epoch=preparation.EPOCH,
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "ENABLED").write_text("enabled\n")
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "rate_policy": "tiered_v1",
                    "requests_per_minute": 500,
                    "rollout_account_rpm": 500,
                }
            )
        )
        (self.root / "CURRENT.json").write_text('{"release_id":"unchanged"}\n')
        self.manifest = self.base / "batch.json"
        preparation.prepare(self.root, self.manifest, jobs=6)
        self.manifest_sha = preparation.sha(self.manifest)
        self.verified = preparation.verify_manifest(self.manifest, self.manifest_sha)

    def test_prepare_is_read_only_oldest_first_market_fair_and_history_only(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        records = self.verified["records"]
        params = [record["job"]["params"] for record in records]
        self.assertEqual(
            {item["trade_date"] for item in params},
            {"20260901", "20260902", "20260903"},
        )
        self.assertEqual(self.verified["source"]["pending_jobs"], 8)
        self.assertEqual(self.verified["selected"]["market_counts"], {"SH": 3, "SZ": 3})
        self.assertEqual({record["epoch"] for record in records}, {preparation.EPOCH})
        second = self.base / "second.json"
        preparation.prepare(self.root, second, jobs=6)
        self.assertEqual(second.read_bytes(), self.manifest.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        unsafe = self.base / "unsafe.json"
        unsafe.symlink_to(self.base / "missing-target.json")
        with self.assertRaisesRegex(ValueError, "must not exist"):
            preparation.prepare(self.root, unsafe, jobs=6)

    def test_plan_only_pins_all_code_without_authority_credentials_or_network(self):
        result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["api_counts"], {preparation.API: 6})
        self.assertEqual(result["helper_sha256"], runner.helper_sha256())
        self.assertEqual(result["preparation_sha256"], runner.preparation_sha256())
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_publish"])
        self.assertNotEqual(runner.helper_sha256(), runner.sha(Path(runner.__file__)))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)

    def test_manifest_rejects_promoted_boundary(self):
        value = json.loads(self.manifest.read_bytes())
        value["boundaries"]["known_at_verified"] = True
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid batch manifest"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

    def test_execute_is_exact_bounded_hash_pinned_and_does_not_publish(self):
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append((body["api_name"], body["params"]))
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
            patch.object(
                runner.exact_runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=101 * 2**30),
            ),
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
        self.assertEqual([api for api, _params in calls], [preparation.API] * 3)
        self.assertEqual(result["upstream_calls"], 3)
        self.assertEqual(result["max_upstream_calls"], 3)
        self.assertEqual(result["max_seconds"], 10)
        self.assertEqual(result["helper_sha256"], runner.helper_sha256())
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
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (self.recent,)
                ).fetchone()[0],
                "pending",
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (self.recent,)
                ).fetchone()[0],
                0,
            )

    def test_execute_requires_all_pins_and_rejects_stale_scope_before_secret(self):
        with self.assertRaisesRegex(ValueError, "Execute requires pinned"):
            runner.run_batch(self.manifest, self.manifest_sha, execute=True)
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret") as secret,
            patch.object(
                runner.exact_runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=99 * 2**30),
            ),
        ):
            blocked = runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_task_ids_sha256=self.verified["all_task_ids_sha256"],
                expected_config_sha256=runner.sha(self.config_path),
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                root=self.root,
                execute=True,
            )
        self.assertEqual(blocked["status"], "blocked_disk_reserve")
        secret.assert_not_called()
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
