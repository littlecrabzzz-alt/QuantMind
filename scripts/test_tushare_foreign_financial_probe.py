import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from backend.shared.tushare_pipeline import Pipeline


ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
SPEC = importlib.util.spec_from_file_location(
    "tushare_foreign_financial_probe",
    ROOT / "scripts/tushare_foreign_financial_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ForeignFinancialProbeTest(unittest.TestCase):
    def test_plan_is_finite_and_contract_pinned(self):
        requests = probe.planned_requests()
        self.assertEqual(len(requests), 8)
        self.assertEqual({row["api_name"] for row in requests}, set(probe.APIS))
        self.assertEqual(
            {row["params"]["ts_code"] for row in requests}, {"00700.HK", "AAPL"}
        )
        self.assertTrue(
            all(
                row["params"]["start_date"] == "20240101"
                and row["params"]["end_date"] == "20241231"
                for row in requests
            )
        )
        evidence = probe.contract_evidence()
        self.assertEqual(set(evidence), set(probe.APIS))
        self.assertRegex(probe.contract_sha256(evidence), r"^[a-f0-9]{64}$")

    def test_safe_result_does_not_copy_supplier_or_secret_text(self):
        safe = probe.safe_result(
            {
                "api_name": "hk_income",
                "status": "permission_denied",
                "code": 2002,
                "http_status": 200,
                "msg": "token synthetic-secret",
                "error": "synthetic-secret",
                "object_sha256": "a" * 64,
                "observation_sha256": "b" * 64,
                "observation": "c" * 32 + ".json",
            }
        )
        encoded = json.dumps(safe)
        self.assertNotIn("synthetic-secret", encoded)
        self.assertNotIn("msg", safe)
        self.assertEqual(safe["status"], "permission_denied")

    def test_exact_scope_records_all_eight_permission_results(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = Pipeline(Path(directory), CATALOG)
            try:
                pipeline.db.execute(
                    "INSERT INTO identifier_discovery_cache "
                    "(version,attempt_rowid,attempt_count,result,objects) "
                    "VALUES(4,0,0,?,?)",
                    (
                        json.dumps(
                            {
                                "hk_stocks": ["00700.HK"],
                                "us_stocks": ["AAPL"],
                            }
                        ),
                        "{}",
                    ),
                )
                self.assertEqual(
                    probe.seed_evidence(pipeline.db)["seed_presence"],
                    {"hk_stocks": True, "us_stocks": True},
                )
                task_ids = probe.reserve_jobs(pipeline, "fixture-probe")
                with httpx.Client(
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(
                            200,
                            json={
                                "code": -2002,
                                "msg": "没有访问该接口权限",
                                "data": None,
                            },
                        )
                    ),
                    trust_env=False,
                ) as client:
                    run = pipeline.run(
                        client,
                        "synthetic-token",
                        {
                            "rate_policy": "tiered_v1",
                            "requests_per_minute": 500,
                            "rollout_account_rpm": 500,
                            "acquisition_pipeline_depth": 1,
                            "acquisition_capture_execution": "thread",
                            "acquisition_capture_workers": 1,
                        },
                        max_requests=8,
                        max_seconds=15,
                        pause=0,
                        task_ids=task_ids,
                    )
                rows = probe.result_rows(pipeline, task_ids)
                self.assertEqual(run["requests"], 8)
                self.assertTrue(run["exact_task_scope"])
                self.assertEqual({row["state"] for row in rows}, {"permission_blocked"})
                self.assertEqual(
                    {row["result"]["status"] for row in rows}, {"permission_denied"}
                )
                self.assertEqual(
                    pipeline.db.execute(
                        "SELECT count(*) FROM capability "
                        "WHERE status='permission_denied'"
                    ).fetchone()[0],
                    8,
                )
            finally:
                pipeline.close()


if __name__ == "__main__":
    unittest.main()
