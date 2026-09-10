"""Offline contracts, planning, storage and scope for current off-catalog APIs."""

from datetime import date
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit_tushare_scope_gaps import audit
from backend.shared.tushare_offcatalog_contracts import (
    FIELDS,
    INPUT_FIELDS,
    OFFCATALOG_CONTRACTS,
    iter_offcatalog_jobs,
    offcatalog_prerequisites,
)
from backend.shared.tushare_pipeline import CONTRACTS as PIPELINE_CONTRACTS, Pipeline
from backend.shared.tushare_portfolio_read_contracts import PORTFOLIO_READ_CONTRACTS
from backend.shared.tushare_realtime_extra_contracts import ADJACENT_API_OBLIGATIONS
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, PLANNERS, contract_for
from backend.shared.tushare_store import KEYS, dataset_schema, read_dataset


APIS = {
    "film_record",
    "teleplay_record",
    "bo_monthly",
    "bo_weekly",
    "bo_daily",
    "bo_cinema",
    "fund_sales_ratio",
    "fund_sales_vol",
    "tmt_twincome",
    "tmt_twincomedetail",
}


class OffCatalogContractsTest(unittest.TestCase):
    def setUp(self):
        guard = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_current_fields_sources_and_gaps_are_registered(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        entries = {
            api: entry
            for entry in ledger["discovered_entries"]
            for api in entry.get("api_names", [])
        }
        self.assertEqual(set(OFFCATALOG_CONTRACTS), APIS)
        self.assertEqual(sum(map(len, FIELDS.values())), 81)
        for api, spec in OFFCATALOG_CONTRACTS.items():
            entry = entries[api]
            self.assertEqual(spec["source_url"], entry["url"])
            self.assertEqual(spec["source_html_sha256"], entry["source_sha256"])
            self.assertEqual(spec["requested_fields"], entry["output_fields"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["input_fields"], INPUT_FIELDS[api])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertFalse(spec["independent_permission"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertTrue(spec["history_gap"])
            self.assertTrue(spec["pit_gap"])
            self.assertEqual(contract_for(api)["group"], "offcatalog")
            self.assertEqual(KEYS[api], tuple(spec["keys"]))
            self.assertIn(api, EXTENDED_CONTRACTS)
        self.assertEqual(INPUT_FIELDS["fund_sales_ratio"], [])
        self.assertFalse(OFFCATALOG_CONTRACTS["bo_daily"]["row_cap_verified"])

    def test_default_empty_then_recent_first_round_robin_history(self):
        self.assertIn("offcatalog", PLANNERS)
        today = date(2026, 9, 10)
        self.assertEqual(list(iter_offcatalog_jobs({}, today)), [])
        starts = {
            "film_record": "20260701",
            "teleplay_record": "20260701",
            "bo_monthly": "20260701",
            "bo_weekly": "20260824",
            "bo_daily": "20260901",
            "bo_cinema": "20260901",
            "fund_sales_ratio": "20200101",
            "fund_sales_vol": "20260101",
            "tmt_twincome": "20200101",
            "tmt_twincomedetail": "20260101",
        }
        jobs = list(
            iter_offcatalog_jobs(
                {
                    "offcatalog_apis": list(OFFCATALOG_CONTRACTS),
                    "offcatalog_history_start": starts,
                    "planning_epoch": "fixture",
                },
                today,
            )
        )
        recent = [job for job in jobs if job["priority"] == 20]
        history = [job for job in jobs if job["priority"] == 40]
        self.assertEqual(len(recent), 220)
        self.assertTrue(all(job["epoch"] == "fixture" for job in recent))
        self.assertTrue(all(job["epoch"] == "history" for job in history))
        self.assertEqual(
            [job["api_name"] for job in history[:9]],
            [
                "film_record",
                "teleplay_record",
                "bo_monthly",
                "bo_weekly",
                "bo_daily",
                "bo_cinema",
                "fund_sales_vol",
                "tmt_twincome",
                "tmt_twincomedetail",
            ],
        )
        identities = [
            (job["api_name"], json.dumps(job["params"], sort_keys=True)) for job in jobs
        ]
        self.assertEqual(len(identities), len(set(identities)))
        ratio = [job for job in jobs if job["api_name"] == "fund_sales_ratio"]
        self.assertEqual(
            ratio,
            [
                {
                    "api_name": "fund_sales_ratio",
                    "params": {},
                    "priority": 20,
                    "epoch": "fixture",
                }
            ],
        )
        with self.assertRaises(ValueError):
            list(iter_offcatalog_jobs({"offcatalog_apis": ["rt_min"]}, today))

    def test_prerequisites_keep_permission_and_completeness_unresolved(self):
        gaps = offcatalog_prerequisites({"offcatalog_apis": list(APIS)})
        by_api = {api: set() for api in APIS}
        for gap in gaps:
            by_api[gap["api_name"]].add(gap["reason"])
        for reasons in by_api.values():
            self.assertIn("permission_unprobed", reasons)
            self.assertIn("history_gap", reasons)
            self.assertIn("pit_gap", reasons)
            self.assertIn("refresh_gap", reasons)
        self.assertIn("acquisition_gap", by_api["fund_sales_ratio"])
        self.assertIn("saturation_gap", by_api["bo_cinema"])
        self.assertIn("universe_gap", by_api["tmt_twincome"])
        self.assertIn("universe_gap", by_api["tmt_twincomedetail"])

    def test_tmt_uses_all_documented_products_and_bounded_month_windows(self):
        jobs = list(
            iter_offcatalog_jobs(
                {
                    "offcatalog_apis": ["tmt_twincome", "tmt_twincomedetail"],
                    "offcatalog_history_start": "20200115",
                },
                date(2026, 9, 10),
            )
        )
        self.assertEqual(
            {job["params"]["item"] for job in jobs}, {str(i) for i in range(1, 66)}
        )
        for job in jobs:
            start = date.fromisoformat(
                job["params"]["start_date"][:4]
                + "-"
                + job["params"]["start_date"][4:6]
                + "-"
                + job["params"]["start_date"][6:]
            )
            end = date.fromisoformat(
                job["params"]["end_date"][:4]
                + "-"
                + job["params"]["end_date"][4:6]
                + "-"
                + job["params"]["end_date"][6:]
            )
            months = (end.year - start.year) * 12 + end.month - start.month + 1
            limit = 30 if job["api_name"] == "tmt_twincome" else 1
            self.assertLessEqual(months, limit)

    def test_synthetic_acquire_publish_and_local_query(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertIn(body["api_name"], OFFCATALOG_CONTRACTS)
            fields = body["fields"].split(",")
            values = {
                field: (
                    2026
                    if field == "year"
                    else 1
                    if field == "rank"
                    else "Q2"
                    if field == "quarter"
                    else "20260901"
                    if field in {"date", "ann_date"}
                    else "202609"
                    if field == "report_date"
                    else "fixture"
                )
                for field in fields
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[values[field] for field in fields]],
                    },
                },
            )

        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(tmp, catalog)
            for api in OFFCATALOG_CONTRACTS:
                params = next(
                    iter_offcatalog_jobs({"offcatalog_apis": [api]}, date(2026, 9, 10))
                )["params"]
                pipeline.enqueue(api, params)
            pipeline.db.commit()
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False
            ) as client:
                result = pipeline.run(
                    client,
                    "synthetic-token",
                    {"priority_start": "20200101", "enable_offcatalog": True},
                    max_requests=len(OFFCATALOG_CONTRACTS),
                    pause=0,
                )
            self.assertEqual(result["done"], len(OFFCATALOG_CONTRACTS))
            release = pipeline.publish()
            pipeline.close()
            for api, spec in OFFCATALOG_CONTRACTS.items():
                table = read_dataset(tmp, release, api)
                self.assertEqual(table.num_rows, 1)
                self.assertEqual(
                    dataset_schema(tmp, release, api)["keys"],
                    spec["keys"] + ["_row_identity"],
                )
                metadata = json.loads(table.schema.metadata[b"tushare"])
                self.assertEqual(metadata["upstream_calls"], 0)
                self.assertFalse(metadata["history_bound_verified"])
                self.assertEqual(set(metadata["field_gaps"]), set(FIELDS[api]))
            self.assertEqual(
                read_dataset(
                    tmp, release, "teleplay_record",
                    start_date="2026-09-01", end_date="2026-09-30",
                ).num_rows,
                1,
            )
            self.assertEqual(
                read_dataset(
                    tmp, release, "fund_sales_vol",
                    start_date="2026-04-01", end_date="2026-06-30",
                ).num_rows,
                1,
            )

    def test_current_scope_diff_is_exact_and_classified(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        result = audit(
            ledger,
            EXTENDED_CONTRACTS,
            PIPELINE_CONTRACTS,
            KEYS,
            PORTFOLIO_READ_CONTRACTS,
            ADJACENT_API_OBLIGATIONS,
        )
        self.assertEqual(result["counts"]["total_named_scope"], 249)
        self.assertEqual(result["counts"]["registered_union"], 243)
        self.assertEqual(result["counts"]["not_registered_in_scope"], 6)
        remaining = {
            row["api_name"]: row["implementation"]
            for row in result["apis"]
            if row["implementation"] != "runtime_readable"
        }
        self.assertEqual(
            remaining,
            {
                "ggt_monthly": "public_read_only_contract_blocked",
                "p_list": "pure_contract_only_private",
                "p_get": "pure_contract_only_private",
                "p_save": "excluded_mutation",
                "p_delete": "excluded_mutation",
                "pro_bar": "sdk_only",
            },
        )

    def test_mirror_installer_bundles_offcatalog_contract(self):
        installer = (ROOT / "scripts/tushare_mirror.py").read_text()
        self.assertIn('"backend/shared/tushare_offcatalog_contracts.py"', installer)


if __name__ == "__main__":
    unittest.main()
