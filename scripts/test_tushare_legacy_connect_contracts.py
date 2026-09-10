"""Offline contracts, planning and fixed-release reads for retained Connect APIs."""

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
from backend.shared.tushare_legacy_connect_contracts import (
    FIELDS,
    INPUT_FIELDS,
    LEGACY_CONNECT_CONTRACTS,
    iter_legacy_connect_jobs,
    legacy_connect_prerequisites,
)
from backend.shared.tushare_pipeline import CONTRACTS as PIPELINE_CONTRACTS, Pipeline
from backend.shared.tushare_portfolio_read_contracts import PORTFOLIO_READ_CONTRACTS
from backend.shared.tushare_realtime_extra_contracts import ADJACENT_API_OBLIGATIONS
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, PLANNERS, contract_for
from backend.shared.tushare_store import KEYS, dataset_schema, read_dataset


class LegacyConnectContractsTest(unittest.TestCase):
    def setUp(self):
        guard = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_retained_fields_sources_and_gaps_are_registered(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        entries = {
            api: entry
            for entry in ledger["discovered_entries"]
            for api in entry.get("api_names", [])
        }
        self.assertEqual(
            set(LEGACY_CONNECT_CONTRACTS),
            {"moneyflow_hsgt", "ggt_daily", "ggt_top10"},
        )
        for api, spec in LEGACY_CONNECT_CONTRACTS.items():
            entry = entries[api]
            self.assertEqual(spec["source_url"], entry["url"])
            self.assertEqual(spec["source_html_sha256"], entry["source_sha256"])
            self.assertEqual(spec["permission_status"], "available_observed")
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["input_fields"], INPUT_FIELDS[api])
            self.assertFalse(spec["row_cap_verified"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertTrue(spec["history_gap"])
            self.assertTrue(spec["pit_gap"])
            self.assertTrue(spec["hidden_field_gap"])
            self.assertEqual(contract_for(api)["group"], "legacy_connect")
            self.assertEqual(KEYS[api], tuple(spec["keys"]))
            self.assertIn(api, EXTENDED_CONTRACTS)
        self.assertEqual(
            INPUT_FIELDS["ggt_daily"], ["trade_date", "start_date", "end_date"]
        )
        self.assertFalse(LEGACY_CONNECT_CONTRACTS["ggt_daily"]["observed_has_more"])
        self.assertTrue(
            LEGACY_CONNECT_CONTRACTS["ggt_daily"]["previous_unfiltered_observation"][
                "has_more"
            ]
        )

    def test_default_empty_then_explicit_bounded_plans(self):
        self.assertIn("legacy_connect", PLANNERS)
        self.assertEqual(list(iter_legacy_connect_jobs({}, date(2026, 9, 10))), [])
        jobs = list(
            iter_legacy_connect_jobs(
                {
                    "legacy_connect_apis": [
                        "moneyflow_hsgt",
                        "ggt_daily",
                        "ggt_top10",
                    ],
                    "legacy_connect_history_start": "20260901",
                    "planning_epoch": "fixture",
                },
                date(2026, 9, 10),
            )
        )
        self.assertEqual(len(jobs), 30)
        for api in ("moneyflow_hsgt", "ggt_daily", "ggt_top10"):
            selected = [job for job in jobs if job["api_name"] == api]
            self.assertEqual(len(selected), 10)
            self.assertEqual(
                {job["params"]["trade_date"] for job in selected},
                {f"202609{day:02d}" for day in range(1, 11)},
            )
            self.assertTrue(
                all(set(job["params"]) == {"trade_date"} for job in selected)
            )
        with self.assertRaises(ValueError):
            list(
                iter_legacy_connect_jobs(
                    {"legacy_connect_apis": ["ggt_monthly"]}, date(2026, 9, 10)
                )
            )
        reasons = {
            gap["reason"]
            for gap in legacy_connect_prerequisites(
                {"legacy_connect_apis": ["ggt_daily"]}
            )
        }
        self.assertNotIn("acquisition_gap", reasons)
        self.assertIn("saturation_gap", reasons)

    def test_synthetic_acquire_publish_and_local_query(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertIn(body["api_name"], LEGACY_CONNECT_CONTRACTS)
            fields = body["fields"].split(",")
            values = {
                "trade_date": "20260904",
                "ggt_ss": -1.0,
                "ggt_sz": 2.0,
                "hgt": 3.0,
                "sgt": 4.0,
                "north_money": 5.0,
                "south_money": 6.0,
                "buy_amount": 7.0,
                "buy_volume": 8.0,
                "sell_amount": 9.0,
                "sell_volume": 10.0,
                "ts_code": "000001.SH",
                "name": "fixture",
                "close": 11.0,
                "p_change": -1.0,
                "rank": 1,
                "market_type": 1,
                "amount": 12.0,
                "net_amount": 13.0,
                "sh_amount": 14.0,
                "sh_net_amount": 15.0,
                "sh_buy": 16.0,
                "sh_sell": 17.0,
                "sz_amount": 18.0,
                "sz_net_amount": 19.0,
                "sz_buy": 20.0,
                "sz_sell": 21.0,
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
            for api in LEGACY_CONNECT_CONTRACTS:
                pipeline.enqueue(api, {"trade_date": "20260904"})
            pipeline.db.commit()
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = pipeline.run(
                    client,
                    "synthetic-token",
                    {"priority_start": "20200101", "enable_legacy_connect": True},
                    max_requests=3,
                    pause=0,
                )
            self.assertEqual(result["done"], 3)
            release = pipeline.publish()
            pipeline.close()
            for api, spec in LEGACY_CONNECT_CONTRACTS.items():
                table = read_dataset(tmp, release, api)
                self.assertEqual(table.num_rows, 1)
                self.assertEqual(dataset_schema(tmp, release, api)["keys"], spec["keys"])
                metadata = json.loads(table.schema.metadata[b"tushare"])
                self.assertEqual(metadata["upstream_calls"], 0)
                self.assertFalse(metadata["history_bound_verified"])
                self.assertEqual(set(metadata["field_gaps"]), set(FIELDS[api]))

    def test_current_scope_diff_drops_only_the_two_evidenced_apis(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        result = audit(
            ledger,
            EXTENDED_CONTRACTS,
            PIPELINE_CONTRACTS,
            KEYS,
            PORTFOLIO_READ_CONTRACTS,
            ADJACENT_API_OBLIGATIONS,
        )
        self.assertEqual(result["counts"]["not_registered_in_scope"], 6)
        remaining = {
            row["api_name"]
            for row in result["apis"]
            if row["implementation"] != "runtime_readable"
        }
        self.assertEqual(
            remaining,
            {
                "ggt_monthly",
                "p_list",
                "p_get",
                "p_save",
                "p_delete",
                "pro_bar",
            },
        )


if __name__ == "__main__":
    unittest.main()
