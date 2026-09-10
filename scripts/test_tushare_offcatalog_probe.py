"""Offline bounded probe checks; no credentials, provider, or authority access."""

from argparse import Namespace
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from backend.shared.tushare_pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "offcatalog_probe", REPO / "scripts/tushare_offcatalog_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class OffCatalogProbeTest(unittest.TestCase):
    def setUp(self):
        guard = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_exact_bounded_plan_and_runtime_contracts(self):
        evidence = probe.contract_evidence()
        self.assertEqual(tuple(evidence), probe.APIS)
        self.assertNotIn("tmt_twincome", evidence)
        self.assertNotIn("tmt_twincomedetail", evidence)
        self.assertEqual(probe.MAX_REQUESTS, 11)
        self.assertEqual(
            hashlib.sha256(probe.canonical(evidence).encode()).hexdigest(),
            probe.EXPECTED_CONTRACT_SHA256,
        )
        self.assertEqual(len(probe.BASE_REQUESTS), 8)
        self.assertEqual(
            probe.FILTER_APIS, {"film_record", "teleplay_record", "fund_sales_vol"}
        )
        self.assertEqual(
            dict(probe.BASE_REQUESTS)["film_record"],
            {"start_date": "20181014", "end_date": "20181214"},
        )
        self.assertEqual(dict(probe.BASE_REQUESTS)["fund_sales_ratio"], {})
        self.assertEqual(
            sum(len(item["requested_fields"]) for item in evidence.values()), 73
        )
        self.assertTrue(
            all(
                item["permission_status_before_probe"] == "unprobed"
                for item in evidence.values()
            )
        )

    def test_filters_use_only_actual_response_values(self):
        film = [{"ann_date": "20181101", "film_name": "x"}]
        teleplay = [
            {"report_date": "201905", "org": "fixture org", "name": "fixture name"}
        ]
        fund = [{"year": 2021, "quarter": "Q1", "inst_name": "fixture institution"}]
        self.assertEqual(
            probe.filter_request("film_record", film), {"ann_date": "20181101"}
        )
        self.assertEqual(
            probe.filter_request("teleplay_record", teleplay),
            {"report_date": "201905", "org": "fixture org", "name": "fixture name"},
        )
        self.assertEqual(
            probe.filter_request("fund_sales_vol", fund),
            {"year": "2021", "quarter": "Q1", "name": "fixture institution"},
        )
        self.assertIsNone(probe.filter_request("fund_sales_ratio", fund))
        self.assertIsNone(
            probe.filter_request("film_record", [{"ann_date": "guessed"}])
        )
        assessment = probe.assess_filter(
            "fund_sales_vol",
            {"year": "2021", "quarter": "Q1", "name": "fixture institution"},
            fund,
            fund,
        )
        self.assertEqual(assessment["status"], "filter_match_observed")
        self.assertTrue(assessment["all_rows_match_requested_filter"])
        self.assertTrue(assessment["returned_rows_subset_of_base_observation"])

    def test_result_report_is_strictly_sanitized(self):
        result = probe.safe_result(
            {
                "status": "api_error",
                "api_name": "film_record",
                "message": "secret provider prose",
                "token": "secret-token",
                "code": 50101,
                "http_status": 200,
                "object_sha256": "a" * 64,
                "observation": "b" * 32 + ".json",
                "observation_sha256": "c" * 64,
                "requested_missing_fields": ["ann_date"],
                "unexpected_returned_fields": ["new_field"],
            }
        )
        self.assertNotIn("message", result)
        self.assertNotIn("token", result)
        self.assertNotIn("code", result)
        self.assertEqual(result["status"], "api_error")
        self.assertEqual(result["requested_missing_fields"], ["ann_date"])

    def test_dry_run_is_zero_call_and_needs_no_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "not-created.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts/tushare_offcatalog_probe.py"),
                    "--root",
                    str(Path(tmp) / "absent"),
                    "--report",
                    str(report),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            output = json.loads(proc.stdout)
            self.assertEqual(output["status"], "prepared_only")
            self.assertEqual(output["actual_upstream_calls"], 0)
            self.assertEqual(output["max_requests"], 11)
            self.assertFalse(output["authority_accessed"])
            self.assertFalse(output["token_accessed"])
            self.assertFalse(report.exists())
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts/tushare_offcatalog_probe.py"),
                    "--root",
                    str(Path(tmp) / "absent"),
                    "--report",
                    str(report),
                    "--execute",
                    "--expected-helper-sha256",
                    "0" * 64,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("reviewed helper SHA256", rejected.stderr)
            self.assertFalse(report.exists())

    def test_schema6_is_read_only_and_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipeline.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=5")
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "schema6"):
                probe.require_schema6(path)
            self.assertEqual(path.read_bytes(), before)
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=6")
            before = path.read_bytes()
            probe.require_schema6(path)
            self.assertEqual(path.read_bytes(), before)
            link = Path(tmp) / "linked.sqlite"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "authority queue"):
                probe.require_schema6(link)

    def test_synthetic_eleven_call_capture_and_filter_assessment(self):
        values = {
            "film_record": {
                "rec_no": "fixture-rec",
                "film_name": "fixture-film",
                "ann_date": "20181101",
            },
            "teleplay_record": {
                "name": "fixture-teleplay",
                "org": "fixture-org",
                "report_date": "201905",
                "license_key": "fixture-license",
            },
            "bo_monthly": {"date": "20180901", "name": "fixture", "rank": 1},
            "bo_weekly": {"date": "20181008", "name": "fixture", "rank": 1},
            "bo_daily": {"date": "20181014", "name": "fixture", "rank": 1},
            "bo_cinema": {"date": "20181014", "c_name": "fixture", "rank": 1},
            "fund_sales_ratio": {"year": 2021},
            "fund_sales_vol": {
                "year": 2021,
                "quarter": "Q1",
                "inst_name": "fixture-institution",
                "rank": 1,
            },
        }

        def handler(request):
            body = json.loads(request.content)
            api, fields = body["api_name"], body["fields"].split(",")
            row = [values[api].get(field, 1) for field in fields]
            return httpx.Response(
                200,
                json={"code": 0, "data": {"fields": fields, "items": [row]}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "validation").mkdir()
            catalog = json.loads((REPO / "config/tushare-catalog.json").read_bytes())
            pipeline = Pipeline(root, catalog)
            self.addCleanup(pipeline.close)
            report_path = root / "validation/probe.json"
            args = Namespace(
                report=report_path,
                seconds=120,
                epoch="probe-fixture",
                helper_sha256="a" * 64,
            )
            token_getter = Mock(return_value="synthetic-token")
            with (
                patch.object(probe, "resolved_gates", return_value=(500, 500, 0)),
                patch.object(probe.time, "sleep"),
                httpx.Client(
                    transport=httpx.MockTransport(handler), trust_env=False
                ) as client,
            ):
                report = probe.collect(
                    pipeline,
                    {"rate_policy": "tiered_v1", "requests_per_minute": 500},
                    client,
                    token_getter,
                    args,
                )
            self.assertEqual(report["actual_upstream_calls"], 11)
            self.assertEqual(len(report["results"]), 11)
            self.assertEqual(token_getter.call_count, 1)
            filters = [
                result
                for result in report["results"]
                if result["phase"] == "actual_row_filter"
            ]
            self.assertEqual(
                {result["api_name"] for result in filters}, probe.FILTER_APIS
            )
            self.assertTrue(
                all(
                    result["filter_assessment"]["status"] == "filter_match_observed"
                    for result in filters
                )
            )
            bases = [
                result for result in report["results"] if result["phase"] == "base"
            ]
            self.assertEqual(len(bases), 8)
            self.assertTrue(all("base_filter_assessment" in result for result in bases))
            self.assertTrue(
                all(
                    result["base_filter_assessment"]["status"]
                    in {"filter_match_observed", "unfiltered_base_request"}
                    for result in bases
                )
            )
            saved = report_path.read_text()
            self.assertNotIn("synthetic-token", saved)
            self.assertFalse(report["automatic_activation_permitted"])
            self.assertFalse(report["configuration_changed"])
            self.assertFalse(report["history_complete"])
            self.assertFalse(report["pit_verified"])
            self.assertEqual(report["authority_schema_version"], 6)


if __name__ == "__main__":
    unittest.main()
