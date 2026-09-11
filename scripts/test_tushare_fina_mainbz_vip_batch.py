"""Exact fina_mainbz_vip batches preserve quarter, type and terminal-cap gaps."""

import json
from datetime import date
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared.tushare_pipeline import contract_for
from backend.shared.tushare_registry import PLANNERS
from backend.shared.tushare_research_extra_contracts import (
    fina_mainbz_vip_prerequisites,
    iter_fina_mainbz_vip_jobs,
)
from scripts import prepare_tushare_fina_mainbz_vip_batch as preparation
from scripts import run_tushare_fina_mainbz_vip_batch as runner


class FinaMainbzVipBatchTest(unittest.TestCase):
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
        for period in ("20241231", "20240930", "20240630"):
            for kind in preparation.TYPES:
                self.tasks.append(
                    pipeline.enqueue(
                        preparation.API,
                        {"period": period, "type": kind},
                        priority=40,
                        epoch=preparation.EPOCH,
                    )
                )
        attempted = self.tasks[-1]
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (attempted, 1, '{"status":"transport_error"}'),
        )
        self.unrelated = pipeline.enqueue(
            "fina_audit", {"ts_code": "600999.SH"}, priority=40, epoch="history"
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
        (self.root / "pipeline-config.json").write_bytes(json_bytes(self.config))
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
            self.root, self.output, self.release_id, self.release_sha, periods=2
        )
        self.manifest_sha = preparation.sha(self.output)
        self.manifest = preparation.verify_manifest(self.output, self.manifest_sha)

    def _execute(self, responder, max_requests=1):
        client = httpx.Client(transport=httpx.MockTransport(responder))
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
            return runner.run_batch(
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
                max_requests=max_requests,
                max_seconds=10,
                execute=True,
            )

    def test_runtime_contract_is_vip_only(self):
        spec = contract_for(preparation.API)
        self.assertEqual(spec["minimum_points"], 5000)
        self.assertEqual(spec["row_cap"], 100)
        self.assertEqual(spec["input_fields"], ["period", "type"])
        self.assertFalse(spec["split"])
        self.assertNotIn("pagination", spec)
        self.assertEqual(spec["group"], preparation.API)
        self.assertIs(PLANNERS[preparation.API], iter_fina_mainbz_vip_jobs)

    def test_planner_generates_complete_quarters_and_preserves_gaps(self):
        jobs = list(
            iter_fina_mainbz_vip_jobs(
                {"fina_mainbz_vip_history_start": "20240101"}, date(2025, 2, 1)
            )
        )
        self.assertEqual(len(jobs), 12)
        self.assertTrue(all(job["epoch"] == "history" for job in jobs))
        self.assertEqual(
            {job["params"]["period"] for job in jobs},
            {"20240331", "20240630", "20240930", "20241231"},
        )
        for period in {job["params"]["period"] for job in jobs}:
            self.assertEqual(
                {
                    job["params"]["type"]
                    for job in jobs
                    if job["params"]["period"] == period
                },
                set(preparation.TYPES),
            )
        gaps = fina_mainbz_vip_prerequisites(
            config={"fina_mainbz_vip_history_start": "20240101"}
        )
        self.assertEqual(
            {gap["reason"] for gap in gaps},
            {
                "configured_scope_does_not_prove_earlier_history_absent",
                "pagination_gap",
                "pit_unverified",
            },
        )
        with self.assertRaisesRegex(ValueError, "must be configured"):
            list(iter_fina_mainbz_vip_jobs({}, date(2025, 2, 1)))

    def test_prepare_is_read_only_pristine_and_complete_pdi(self):
        before = (self.root / "pipeline.sqlite").read_bytes()
        copy = self.base / "copy.json"
        preparation.prepare(
            self.root, copy, self.release_id, self.release_sha, periods=2
        )
        self.assertEqual(copy.read_bytes(), self.output.read_bytes())
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        self.assertEqual(
            self.manifest["selected"]["type_counts"], {"D": 2, "I": 2, "P": 2}
        )
        self.assertEqual(self.manifest["selected"]["quarter_count"], 2)
        self.assertTrue(self.manifest["selected"]["complete_pdi_per_quarter"])
        self.assertEqual(self.manifest["selected"]["report_period_min"], "20240930")
        self.assertEqual(self.manifest["selected"]["report_period_max"], "20241231")
        self.assertEqual(
            self.manifest["rate_contracts"]["api"],
            {
                "rpm": 500,
                "source": "points_regular_allowlist_doc290",
                "minimum_points": 5000,
            },
        )
        self.assertFalse(self.manifest["boundaries"]["pit_verified"])
        self.assertFalse(self.manifest["boundaries"]["known_at_verified"])
        self.assertFalse(self.manifest["boundaries"]["history_completeness_verified"])

    def test_plan_only_needs_no_authority_credentials_network_or_writes(self):
        result = runner.run_batch(
            self.output, self.manifest_sha, root=self.base / "missing"
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
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

    def test_execute_is_exact_and_100_rows_becomes_terminal_gap(self):
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            fields = body["fields"].split(",")
            item = [None] * len(fields)
            item[fields.index("ts_code")] = "600001.SH"
            item[fields.index("end_date")] = body["params"]["period"]
            item[fields.index("bz_item")] = "segment"
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": [item] * 100}}
            )

        pointer = (self.root / "CURRENT.json").read_bytes()
        result = self._execute(respond)
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(requests[0]["params"]), {"period", "type"})
        self.assertEqual(result["upstream_calls"], 1)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            task_id = self.manifest["records"][0]["task_id"]
            state, saved = db.execute(
                "SELECT state,result FROM jobs WHERE id=?", (task_id,)
            ).fetchone()
            self.assertEqual(state, "blocked")
            self.assertEqual(json.loads(saved)["status"], "possibly_truncated")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM partition_splits WHERE parent_id=?",
                    (task_id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (self.unrelated,)
                ).fetchone()[0],
                "pending",
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
            {"period": "20240331", "type": "P"},
            priority=40,
            epoch=preparation.EPOCH,
        )
        pipeline.db.commit()
        pipeline.close()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority"),
            self.assertRaisesRegex(ValueError, "eligible task inventory changed"),
        ):
            self._execute(lambda request: httpx.Response(500))


if __name__ == "__main__":
    unittest.main()
