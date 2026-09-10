"""Index-weight batches pin existing history and preserve research boundaries."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_index_weight_batch as preparation
import run_tushare_index_weight_batch as runner


class IndexWeightBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.history = []
        for code in ("000001.SH", "000300.SH", "000905.SH", "000985.CSI"):
            for month in ("202606", "202607", "202608"):
                self.history.append(
                    pipeline.enqueue(
                        preparation.API,
                        {
                            "index_code": code,
                            "start_date": month + "01",
                            "end_date": month + ("30" if month == "202606" else "31"),
                        },
                        priority=45,
                        epoch=preparation.EPOCH,
                    )
                )
        self.recent = pipeline.enqueue(
            preparation.API,
            {
                "index_code": "399001.SZ",
                "start_date": "20260902",
                "end_date": "20260908",
            },
            priority=25,
            epoch="20260909",
        )
        self.unrelated = pipeline.enqueue(
            "fund_nav",
            {
                "ts_code": "510300.SH",
                "start_date": "20260801",
                "end_date": "20260831",
            },
            priority=1,
            epoch=preparation.EPOCH,
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
        preparation.prepare(self.root, self.manifest, batch_jobs=6)
        self.manifest_sha = preparation.sha(self.manifest)
        self.verified = preparation.verify_manifest(self.manifest, self.manifest_sha)

    def test_prepare_is_read_only_recent_index_fair_and_history_only(self):
        records = self.verified["records"]
        per_code = {}
        for record in records:
            params = record["job"]["params"]
            per_code.setdefault(params["index_code"], []).append(params["end_date"])
            self.assertEqual(record["epoch"], preparation.EPOCH)
        self.assertEqual(set(per_code), {"000001.SH", "000300.SH", "000905.SH", "000985.CSI"})
        self.assertEqual(sorted(map(len, per_code.values())), [1, 1, 2, 2])
        self.assertTrue(all(max(days) == "20260831" for days in per_code.values()))
        self.assertEqual(self.verified["boundaries"], preparation.BOUNDARIES)
        self.assertFalse(self.verified["boundaries"]["known_at_verified"])
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
            self.assertEqual(
                db.execute("SELECT state FROM jobs WHERE id=?", (self.recent,)).fetchone()[0],
                "pending",
            )
        finally:
            db.close()

    def test_plan_only_verifies_hashes_without_authority_credentials_or_network(self):
        result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["api_counts"], {preparation.API: 6})
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)

    def test_manifest_rejects_boundary_promotion_and_bad_leaf(self):
        value = json.loads(self.manifest.read_bytes())
        value["boundaries"]["known_at_verified"] = True
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid batch manifest"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

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
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute("SELECT state FROM jobs WHERE id=?", (self.unrelated,)).fetchone()[0],
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

    def test_bounds_and_execute_pins_are_mandatory(self):
        with self.assertRaisesRegex(ValueError, "1 to 360"):
            runner.run_batch(self.manifest, self.manifest_sha, max_requests=361)
        with self.assertRaisesRegex(ValueError, "at most 90"):
            runner.run_batch(self.manifest, self.manifest_sha, max_seconds=91)
        with self.assertRaisesRegex(ValueError, "Execute requires pinned"):
            runner.run_batch(self.manifest, self.manifest_sha, execute=True)


if __name__ == "__main__":
    unittest.main()
