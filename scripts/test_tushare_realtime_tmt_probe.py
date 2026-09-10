# ruff: noqa: E402
"""Offline checks for the bounded realtime/TMT probe."""

from argparse import Namespace
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location(
    "realtime_tmt_probe", REPO / "scripts/tushare_realtime_tmt_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

from backend.shared.tushare_intake import json_bytes
from backend.shared.tushare_pipeline import Pipeline
from backend.shared.tushare_registry import contract_for


def digest(body):
    return hashlib.sha256(body).hexdigest()


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="realtime-tmt-probe-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "fixed"
        self.root.mkdir()
        self.files = {}
        self.number = 0
        for obj, attr in ((socket.socket, "connect"), (socket, "getaddrinfo")):
            guard = patch.object(
                obj, attr, side_effect=AssertionError("network forbidden")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def put(self, name, body):
        path = self.root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        self.files[name] = {"sha256": digest(body), "bytes": len(body)}

    def observed(self, api, params, rows):
        fields = list(rows[0])
        body = json_bytes(
            {
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [[row[field] for field in fields] for row in rows],
                },
            }
        )
        object_sha = digest(body)
        self.put("objects/" + object_sha + ".json", body)
        self.number += 1
        name = f"{self.number:032x}.json"
        observation = json_bytes(
            {
                "request": {
                    "api_name": api,
                    "params": params,
                    "fields": ",".join(fields),
                },
                "object_sha256": object_sha,
                "requested_at": "2026-09-10T01:00:00+00:00",
                "fetched_at": "2026-09-10T01:00:00+00:00",
            }
        )
        self.put("observations/" + name, observation)
        return name

    def seeds(self):
        today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
        recent = (today - timedelta(days=1)).strftime("%Y%m%d")
        old = (today - timedelta(days=20)).strftime("%Y%m%d")
        sources = {}
        choices = {
            "stock": ("stock_basic", {"list_status": "L"}, {"ts_code": "600000.SH"}),
            "etf": ("etf_basic", {}, {"ts_code": "159001.SZ"}),
            "index": ("index_basic", {}, {"ts_code": "000001.SH"}),
            "sw": ("index_classify", {}, {"index_code": "801001.SI"}),
            "future": (
                "fut_basic",
                {},
                {
                    "ts_code": "CU2610.SHF",
                    "list_date": "20250101",
                    "delist_date": "20271001",
                },
            ),
        }
        for family, (api, params, row) in choices.items():
            observation = self.observed(api, params, [row])
            sources[family] = {
                "observation": observation,
                "value": row.get("ts_code", row.get("index_code")),
            }
        calendar = self.observed(
            "trade_cal",
            {"exchange": "SSE"},
            [{"cal_date": value, "is_open": 1} for value in (recent, old)],
        )
        manifest = {
            "files": self.files,
            "datasets": [],
            "coverage_by_api": [],
            "history_complete": False,
            "historical_versions_complete": True,
        }
        manifest_body = json_bytes(manifest)
        release_id = "data-" + digest(manifest_body)
        release = self.root / "releases" / release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(manifest_body)
        recipe = {
            "release_id": release_id,
            "sources": sources,
            "calendar": {
                "observation": calendar,
                "recent": recent,
                "history_start": old,
                "history_end": old,
            },
        }
        path = Path(self.temp.name) / "seeds.json"
        path.write_bytes(json_bytes(recipe))
        return path, digest(path.read_bytes())

    def test_contracts_and_exact_bound(self):
        evidence = probe.contract_evidence()
        self.assertEqual(tuple(evidence), probe.APIS)
        self.assertEqual(probe.MAX_REQUESTS, 7)
        self.assertEqual(
            digest(probe.canonical(evidence).encode()),
            probe.EXPECTED_CONTRACT_SHA256,
        )
        self.assertTrue(all(not item["default_enabled"] for item in evidence.values()))
        self.assertTrue(
            all(
                item["permission_status_before_probe"] == "unprobed"
                for item in evidence.values()
            )
        )
        self.assertEqual(
            sum(len(item["requested_fields"]) for item in evidence.values()), 32
        )

    def test_frozen_actual_seed_plan_and_tmt_limits(self):
        path, sha = self.seeds()
        planned, recipe = probe.seed_requests(self.root, path, sha)
        self.assertEqual(len(planned), 5)
        self.assertEqual({api for api, _ in planned}, set(probe.APIS))
        self.assertEqual(
            dict(planned)["rt_min"], {"ts_code": "600000.SH", "freq": "1MIN"}
        )
        self.assertEqual(
            dict(planned)["rt_etf_min_daily"],
            {"ts_code": "159001.SZ", "freq": "1MIN"},
        )
        self.assertEqual(dict(planned)["tmt_twincome"]["item"], "8")
        self.assertEqual(
            dict(planned)["tmt_twincome"],
            {"item": "8", "start_date": "20160201", "end_date": "20180731"},
        )
        self.assertEqual(
            recipe["release_id"], json.loads(path.read_bytes())["release_id"]
        )
        with self.assertRaisesRegex(ValueError, "Invalid frozen seed recipe"):
            probe.seed_requests(self.root, path, "0" * 64)

    def test_dynamic_filters_only_accept_actual_contract_values(self):
        aggregate = [{"date": "20180731", "item": "8", "op_income": 1.0}]
        detail = [
            {
                "date": "20180731",
                "item": "8",
                "symbol": "6156",
                "op_income": 1.0,
                "consop_income": None,
            }
        ]
        self.assertEqual(
            probe.filter_request("tmt_twincome", aggregate),
            {"date": "20180731", "item": "8"},
        )
        self.assertEqual(
            probe.filter_request("tmt_twincomedetail", detail),
            {"date": "20180731", "item": "8", "symbol": "6156"},
        )
        self.assertIsNone(
            probe.filter_request("tmt_twincome", [{"date": "20180731", "item": "66"}])
        )
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            probe.validate_request(
                "tmt_twincome",
                {"date": "20180731", "item": "8", "start_date": "20180101"},
                dynamic=True,
            )

    def test_safe_report_drops_provider_prose_and_secret(self):
        result = probe.safe_result(
            {
                "status": "api_error",
                "api_name": "rt_min",
                "message": "provider secret prose",
                "token": "synthetic-secret",
                "http_status": 200,
                "object_sha256": "a" * 64,
                "observation": "b" * 32 + ".json",
                "observation_sha256": "c" * 64,
                "requested_missing_fields": ["time"],
            }
        )
        self.assertEqual(result["status"], "api_error")
        self.assertNotIn("message", result)
        self.assertNotIn("token", result)
        self.assertNotIn("http_status", result)
        self.assertEqual(result["requested_missing_fields"], ["time"])

    def test_dry_run_validates_fixed_sources_but_never_token_or_report(self):
        path, sha = self.seeds()
        report = Path(self.temp.name) / "not-created.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts/tushare_realtime_tmt_probe.py"),
                "--root",
                str(self.root),
                "--seeds",
                str(path),
                "--seeds-sha256",
                sha,
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
        self.assertEqual(output["max_requests"], 7)
        self.assertFalse(output["token_accessed"])
        self.assertFalse(report.exists())
        rejected = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts/tushare_realtime_tmt_probe.py"),
                "--root",
                str(self.root),
                "--seeds",
                str(path),
                "--seeds-sha256",
                sha,
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

    def test_synthetic_seven_call_capture_gates_and_filters(self):
        seed_path, seed_sha = self.seeds()
        planned, recipe = probe.seed_requests(self.root, seed_path, seed_sha)
        pipeline = Pipeline(
            self.root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        self.addCleanup(pipeline.close)
        report_path = self.root / "validation" / "probe.json"
        report_path.parent.mkdir(exist_ok=True)
        args = Namespace(
            report=report_path,
            seconds=120,
            epoch="snapshot-20260910T010000Z",
            helper_sha256="a" * 64,
            seeds_sha256=seed_sha,
            source_seeds=recipe,
            planned_requests=planned,
        )
        values = {
            "rt_min": {"ts_code": "600000.SH", "time": "2026-09-10 09:31:00"},
            "rt_etf_min": {"ts_code": "159001.SZ", "time": "2026-09-10 09:31:00"},
            "rt_etf_min_daily": {
                "ts_code": "159001.SZ",
                "time": "2026-09-10 09:31:00",
            },
            "tmt_twincome": {"date": "20180731", "item": "8", "op_income": 1.0},
            "tmt_twincomedetail": {
                "date": "20180731",
                "item": "8",
                "symbol": "6156",
                "op_income": 1.0,
                "consop_income": 1.0,
            },
        }
        seen = []

        def handler(request):
            body = json.loads(request.content)
            api = body["api_name"]
            seen.append((api, body["params"]))
            fields = body["fields"].split(",")
            row = values[api]
            payload = [
                row.get(
                    field,
                    1.0
                    if field in {"open", "close", "high", "low", "vol", "amount"}
                    else None,
                )
                for field in fields
            ]
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": [payload]}}
            )

        token_getter = Mock(return_value="synthetic-token")
        with (
            patch.object(probe.common, "resolved_gates", return_value=(500, 30, 0)),
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
        self.assertEqual(report["actual_upstream_calls"], 7)
        self.assertEqual(len(seen), 7)
        self.assertEqual(token_getter.call_count, 1)
        self.assertEqual(
            {api for api, _ in seen},
            set(probe.APIS),
        )
        filters = [
            item for item in report["results"] if item["phase"] == "actual_row_filter"
        ]
        self.assertEqual({item["api_name"] for item in filters}, probe.FILTER_APIS)
        self.assertTrue(
            all(
                item["filter_assessment"]["status"] == "filter_match_observed"
                for item in filters
            )
        )
        saved = report_path.read_text()
        self.assertNotIn("synthetic-token", saved)
        self.assertFalse(report["automatic_activation_permitted"])
        self.assertFalse(report["enable_performed"])
        self.assertFalse(report["configuration_changed"])
        self.assertEqual(report["authority_schema_version"], 6)

    def test_permission_denial_has_no_retry_or_tmt_followup(self):
        seed_path, seed_sha = self.seeds()
        planned, recipe = probe.seed_requests(self.root, seed_path, seed_sha)
        pipeline = Pipeline(
            self.root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        self.addCleanup(pipeline.close)
        report_path = self.root / "validation" / "denied.json"
        report_path.parent.mkdir(exist_ok=True)
        args = Namespace(
            report=report_path,
            seconds=120,
            epoch="snapshot-20260910T010001Z",
            helper_sha256="a" * 64,
            seeds_sha256=seed_sha,
            source_seeds=recipe,
            planned_requests=planned,
        )
        captured = []

        def denied(client, token, job, root):
            captured.append(job["api_name"])
            return {
                "api_name": job["api_name"],
                "status": "permission_denied",
                "row_count": 0,
            }

        with (
            patch.object(probe.common, "resolved_gates", return_value=(500, 30, 0)),
            patch.object(probe.time, "sleep"),
            patch("backend.shared.tushare_intake.capture_sample", side_effect=denied),
        ):
            report = probe.collect(
                pipeline,
                {"rate_policy": "tiered_v1", "requests_per_minute": 500},
                None,
                lambda: "synthetic-token",
                args,
            )
        self.assertEqual(captured, list(probe.APIS))
        self.assertEqual(report["actual_upstream_calls"], 5)
        self.assertFalse(
            any(item["phase"] == "actual_row_filter" for item in report["results"])
        )


if __name__ == "__main__":
    unittest.main()
