import json
from datetime import date
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_catalog_delta_contracts import (
    CATALOG_DELTA_CONTRACTS,
    catalog_delta_prerequisites,
    iter_catalog_delta_jobs,
)
from backend.shared.tushare_rate_policy import resolved_api_rate
from backend.shared.tushare_registry import EXTENDED_CONTRACTS, PLANNERS

APIS = {
    "rt_hk_k",
    "etf_auction",
    "stk_seasoned",
    "fut_inv_weekly",
    "fut_rcpt_mat",
    "fut_trade_param",
    "vix_index",
}


class CatalogDeltaContractsTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "catalog_delta_apis": sorted(APIS),
            "catalog_delta_history_start": "20241230",
            "planning_epoch": "20260919",
        }
        self.identifiers = {"hk_stocks": ["00001.HK", {"ts_code": "00002.HK"}]}

    def test_exact_contract_set_and_registry_group(self):
        self.assertEqual(set(CATALOG_DELTA_CONTRACTS), APIS)
        self.assertIs(PLANNERS["catalog_delta"], iter_catalog_delta_jobs)
        for api in APIS:
            spec = EXTENDED_CONTRACTS[api]
            self.assertEqual(spec["group"], "catalog_delta")
            self.assertTrue(spec["source_url"].startswith("https://tushare.pro/document/2?doc_id="))
            self.assertTrue(spec["required_fields"])
            self.assertTrue(spec["extra_fields"])
        self.assertTrue(CATALOG_DELTA_CONTRACTS["rt_hk_k"]["independent_permission"])
        self.assertTrue(CATALOG_DELTA_CONTRACTS["etf_auction"]["independent_permission"])
        self.assertFalse(CATALOG_DELTA_CONTRACTS["vix_index"]["independent_permission"])

    def test_receipt_product_code_is_requested_without_hiding_documented_gap(self):
        spec = CATALOG_DELTA_CONTRACTS["fut_rcpt_mat"]
        self.assertIn("ts_code", spec["extra_fields"])
        self.assertIn("fut_name", spec["keys"])
        self.assertIn("fut_code", spec["documented_unavailable_fields"])
        self.assertNotIn("fut_code", spec.get("optional_requested_fields", ()))

    def test_planner_is_deterministic_recent_first_and_honors_floor(self):
        jobs = list(iter_catalog_delta_jobs(self.config, date(2026, 9, 19), self.identifiers))
        self.assertEqual(jobs, list(iter_catalog_delta_jobs(self.config, date(2026, 9, 19), self.identifiers)))
        snapshots = [j for j in jobs if j["api_name"] == "rt_hk_k"]
        self.assertEqual(
            [j["params"]["ts_code"] for j in snapshots],
            ["0*.HK", "1*.HK", "2*.HK", "4*.HK", "5*.HK", "6*.HK", "8*.HK"],
        )
        self.assertTrue(all(j["priority"] == 20 for j in jobs if j["epoch"] != "history"))
        self.assertTrue(all(j["priority"] == 40 for j in jobs if j["epoch"] == "history"))
        etf = [j for j in jobs if j["api_name"] == "etf_auction" and j["epoch"] == "history"]
        self.assertTrue(etf)
        self.assertGreaterEqual(min(j["params"]["trade_date"] for j in etf), "20250101")
        years = [j for j in jobs if j["api_name"] == "vix_index" and j["epoch"] == "history"]
        self.assertTrue(all(set(j["params"]) == {"start_date", "end_date"} for j in years))
        exact = [j for j in jobs if j["api_name"] == "fut_trade_param"]
        self.assertTrue(all(set(j["params"]) == {"trade_date"} for j in exact))


    def test_rt_hk_keeps_exact_fallback_for_unverified_prefixes(self):
        cfg = {"catalog_delta_apis": ["rt_hk_k"], "planning_epoch": "slot"}
        ids = {"hk_stocks": ["30000.HK", "70000.HK", "90000.HK"]}
        jobs = list(iter_catalog_delta_jobs(cfg, date(2026, 9, 19), ids))
        self.assertEqual(
            [j["params"]["ts_code"] for j in jobs[-3:]],
            ["30000.HK", "70000.HK", "90000.HK"],
        )
        self.assertTrue(all(j["epoch"] == "slot" for j in jobs))

    def test_unknown_history_is_a_gap_and_produces_only_recent(self):
        cfg = {"catalog_delta_apis": ["stk_seasoned"]}
        gaps = catalog_delta_prerequisites({}, config=cfg)
        self.assertEqual(gaps[0]["reason"], "unknown_history_start_requires_explicit_scope")
        jobs = list(iter_catalog_delta_jobs(cfg, date(2026, 9, 19), {}))
        self.assertTrue(jobs)
        self.assertNotIn("history", {j["epoch"] for j in jobs})

    def test_independent_rights_never_inherit_points_rate(self):
        config = {"rate_policy": "tiered_v1", "requests_per_minute": 500}
        self.assertEqual(resolved_api_rate("rt_hk_k", EXTENDED_CONTRACTS["rt_hk_k"], config)["source"], "unknown_permission_conservative")
        regular = resolved_api_rate("vix_index", EXTENDED_CONTRACTS["vix_index"], config)
        self.assertEqual(regular["rpm"], 500)
        self.assertEqual(regular["source"], "points_regular_allowlist_doc290")

    def test_public_catalog_and_ledger_track_all_new_leaf_apis(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_text())
        self.assertEqual(catalog["entry_count"], 270)
        self.assertEqual(ledger["entry_count"], 270)
        catalog_apis = {a for row in catalog["entries"] for a in row["api_names"]}
        ledger_apis = {a for row in ledger["entries"] for a in row["api_names"]}
        self.assertTrue(APIS <= catalog_apis)
        self.assertTrue(APIS <= ledger_apis)


if __name__ == "__main__":
    unittest.main()
