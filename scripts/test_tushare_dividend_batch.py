import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_dividend_batch as preparation
from scripts import run_tushare_dividend_batch as runner


class DividendBatchTest(unittest.TestCase):
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
        self.task_ids = []
        for market, prefix in (("SH", "6"), ("SZ", "0"), ("BJ", "8")):
            for number in range(4):
                self.task_ids.append(
                    pipeline.enqueue(
                        preparation.API,
                        {"ts_code": f"{prefix}{number:05d}.{market}"},
                        priority=40,
                        epoch=preparation.EPOCH,
                    )
                )
        self.unrelated = pipeline.enqueue(
            "dividend", {"ann_date": "20260901"}, priority=20, epoch="20260911"
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (self.task_ids[0], 1, '{"status":"transport_error"}'),
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").touch()
        (self.root / "pipeline-config.json").write_bytes(
            json_bytes({"rate_policy": "tiered_v1", "requests_per_minute": 500})
        )
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

    def _prepare(self, jobs=6):
        return preparation.prepare(
            self.root, self.output, self.release_id, self.release_sha, jobs
        )

    def test_prepare_selects_balanced_pristine_existing_tasks_read_only(self):
        database_before = preparation.sha(self.root / "pipeline.sqlite")
        manifest = self._prepare()
        self.assertEqual(manifest["api_counts"], {"dividend": 6})
        self.assertEqual(manifest["market_counts"], {"BJ": 2, "SH": 2, "SZ": 2})
        self.assertTrue(all(row["tries"] == 0 for row in manifest["records"]))
        self.assertEqual(
            preparation.sha(self.root / "pipeline.sqlite"), database_before
        )
        self.assertNotIn(
            self.task_ids[0], {record["task_id"] for record in manifest["records"]}
        )

    def test_plan_only_needs_no_authority_credentials_or_network(self):
        manifest = self._prepare()
        result = runner.run_batch(
            self.output, preparation.sha(self.output), root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])
        self.assertEqual(
            manifest["source"]["preparation_sha256"], runner.preparation_sha256()
        )

    def test_manifest_and_release_tampering_fail_closed(self):
        self._prepare()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            preparation.verify_manifest(self.output, "0" * 64)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64}
            )
        )
        verified = preparation.verify_manifest(
            self.output, preparation.sha(self.output)
        )
        with self.assertRaisesRegex(ValueError, "current fixed release"):
            runner._verify_release(self.root, verified)

    def test_execute_is_exact_bounded_and_does_not_publish(self):
        manifest = self._prepare()
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
        self.assertEqual(calls, ["dividend"] * 3)
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
