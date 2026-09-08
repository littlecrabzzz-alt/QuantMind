#!/usr/bin/env python3
"""Offline planner coverage checks; no production data, credentials or network."""

import json
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_structured_contracts import (  # noqa: E402
    STRUCTURED_CONTRACTS,
    iter_structured_jobs,
    structured_prerequisites,
)


class StructuredPlanning(unittest.TestCase):
    def test_calendar_coverage_priority_and_stable_old_requests(self):
        config = {
            "history_start": "20240227",
            "structured_apis": ["daily", "adj_factor", "shibor"],
        }
        today = date(2024, 3, 10)
        jobs = list(iter_structured_jobs(config, today))
        recent = [i for i, j in enumerate(jobs) if j["epoch"] != "history"]
        history = [i for i, j in enumerate(jobs) if j["epoch"] == "history"]
        self.assertLess(max(recent), min(history))
        for api in ("daily", "adj_factor"):
            days = [j["params"]["trade_date"] for j in jobs if j["api_name"] == api]
            expected = {
                (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
                for i in range(12)
            }
            self.assertEqual(set(days), expected)
            self.assertEqual(len(days), len(expected))
        later = list(iter_structured_jobs(config, today + timedelta(days=1)))
        old = next(
            j
            for j in jobs
            if j["api_name"] == "daily" and j["params"]["trade_date"] == "20240229"
        )
        self.assertIn(old, later)
        self.assertFalse(any(j["params"].get("trade_date") == "20240310" for j in jobs))

    def test_foundation_statuses_alias_fields_and_report_types(self):
        jobs = list(
            iter_structured_jobs({"history_start": "20240301"}, date(2024, 4, 2))
        )
        basic = [j["params"] for j in jobs if j["api_name"] == "stock_basic"]
        self.assertEqual(len(basic), 15)
        self.assertEqual({j["list_status"] for j in basic}, {"L", "D", "P", "G", "UN"})
        for api in ("income_vip", "balancesheet_vip", "cashflow_vip"):
            reports = [j["params"] for j in jobs if j["api_name"] == api]
            self.assertEqual(
                {j["report_type"] for j in reports}, {str(n) for n in range(1, 13)}
            )
            self.assertEqual({j["period"] for j in reports}, {"20240331"})
            self.assertFalse(any("start_date" in j for j in reports))
        self.assertEqual(
            STRUCTURED_CONTRACTS["fina_indicator_vip"]["split_axis"], "report_period"
        )
        self.assertIn("5y", STRUCTURED_CONTRACTS["shibor_lpr"]["extra_fields"])

    def test_discovery_missing_and_unsupported_index(self):
        self.assertEqual(len(structured_prerequisites()), 2)
        # Supplier codes here are deliberately confined to outbound API fixtures.
        ids = {"stocks": ["600000.SH"], "indexes": ["000300.SH", "801010.SI"]}
        jobs = list(
            iter_structured_jobs(
                {
                    "history_start": "20240101",
                    "structured_apis": ["namechange", "index_daily"],
                },
                date(2024, 1, 3),
                ids,
            )
        )
        self.assertFalse(structured_prerequisites(ids))
        self.assertTrue(any(j["api_name"] == "namechange" for j in jobs))
        self.assertEqual(
            {j["params"]["ts_code"] for j in jobs if j["api_name"] == "index_daily"},
            {"000300.SH"},
        )
        with self.assertRaises(ValueError):
            list(
                iter_structured_jobs(
                    {"history_start": "20240101"},
                    date(2024, 1, 3),
                    {"stocks": ["SH600000"]},
                )
            )

    def test_all_catalog_items_retained_and_alias_schema_resolvable(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_text())
        self.assertEqual(len(ledger["entries"]), 263)
        self.assertEqual(
            {e["doc_id"] for e in ledger["entries"]},
            {e["doc_id"] for e in catalog["entries"]},
        )
        schemas = {
            a: e["output_fields"] for e in catalog["entries"] for a in e["api_names"]
        }
        for api, spec in STRUCTURED_CONTRACTS.items():
            self.assertIn(spec.get("catalog_api", api), schemas)
            self.assertTrue(
                set(spec["required_fields"])
                <= set(schemas[spec.get("catalog_api", api)])
                | set(spec["extra_fields"])
            )
        mutations = {
            a
            for e in ledger["entries"]
            if e["status"] == "excluded_mutation"
            for a in e["api_names"]
        }
        self.assertEqual(mutations, {"p_save", "p_delete"})
        self.assertTrue(all(e["next_action"] for e in ledger["entries"]))


if __name__ == "__main__":
    unittest.main()
