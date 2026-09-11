import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_index_daily_batch as preparation
from scripts import run_tushare_index_daily_batch as runner


class IndexDailyBatchTest(unittest.TestCase):
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
        self.tasks = {}
        for code in ("000001.SH", "000300.SH", "399001.SZ", "931000.CSI"):
            for year in (2023, 2024, 2025):
                task_id = pipeline.enqueue(
                    preparation.API,
                    {
                        "ts_code": code,
                        "start_date": f"{year}0101",
                        "end_date": f"{year}1231",
                    },
                    priority=45,
                    epoch=preparation.EPOCH,
                )
                self.tasks[code, year] = task_id
        self.attempted = self.tasks["000001.SH", 2025]
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (self.attempted, 1, '{"status":"transport_error"}'),
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
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_bytes(json_bytes(self.config))
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

    def test_prepare_pins_pristine_source_and_interleaves_index_codes(self):
        database_before = preparation.sha(self.root / "pipeline.sqlite")
        manifest = self._prepare()
        records = manifest["records"]
        pairs = [
            (row["job"]["params"]["ts_code"], row["job"]["params"]["end_date"])
            for row in records
        ]
        self.assertEqual(manifest["source"]["eligible_jobs"], 11)
        self.assertEqual(manifest["selected"]["unique_index_codes"], 4)
        self.assertEqual(
            {code for code, _day in pairs}, {code for code, _ in self.tasks}
        )
        self.assertEqual(sum(day == "20251231" for _code, day in pairs), 3)
        self.assertNotIn(self.attempted, {row["task_id"] for row in records})
        self.assertTrue(all(row["tries"] == 0 for row in records))
        self.assertEqual(
            preparation.sha(self.root / "pipeline.sqlite"), database_before
        )
        self.assertEqual(manifest["source"]["rate_gate"]["api_rpm"], 500)

    def test_plan_only_has_zero_external_or_write_access(self):
        manifest = self._prepare()
        result = runner.run_batch(
            self.output, preparation.sha(self.output), root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
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

    def test_manifest_release_and_rate_tampering_fail_closed(self):
        self._prepare()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            preparation.verify_manifest(self.output, "0" * 64)
        verified = preparation.verify_manifest(
            self.output, preparation.sha(self.output)
        )
        (self.root / "CURRENT.json").write_bytes(
            json_bytes({"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64})
        )
        with self.assertRaisesRegex(ValueError, "current fixed release"):
            runner._verify_release(self.root, verified)
        value = json.loads(self.output.read_bytes())
        value["source"]["rate_gate"]["api_rpm"] = 300
        self.output.write_bytes(json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid batch source"):
            preparation.verify_manifest(self.output, preparation.sha(self.output))
        with self.assertRaisesRegex(ValueError, "500 rpm gate"):
            preparation.rate_gate({**self.config, "rollout_account_rpm": 300})

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
        self.assertEqual(calls, [preparation.API] * 3)
        self.assertEqual(result["upstream_calls"], 3)
        self.assertEqual(result["rate_gate"]["api_rpm"], 500)
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

    def test_execute_requires_all_pins_and_hard_bounds(self):
        self._prepare()
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
