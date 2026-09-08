#!/usr/bin/env python3
"""Pure market planning checks; no credentials, API calls or authority writes."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_market_contracts import (  # noqa: E402
    MARKET_CONTRACTS,
    iter_market_jobs,
    market_prerequisites,
)


def day(value):
    return datetime.strptime(value, "%Y%m%d").date()


class MarketPlanning(unittest.TestCase):
    def test_month_windows_cover_every_date_without_gaps_or_future(self):
        config = {
            "history_start": "20240227",
            "market_apis": ["index_weight", "sw_daily", "fund_nav"],
        }
        ids = {
            "indexes": [{"ts_code": "000300.SH"}],
            "funds": [{"ts_code": "000001.OF", "status": "D"}],
        }
        jobs = list(iter_market_jobs(config, date(2024, 3, 12), ids))
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(all(j["epoch"] == "history" for j in jobs[first_history:]))
        expected = {date(2024, 2, 27) + timedelta(days=i) for i in range(14)}
        for api in ("index_weight", "fund_nav"):
            actual = []
            for job in jobs:
                if job["api_name"] == api:
                    params = job["params"]
                    a, b = day(params["start_date"]), day(params["end_date"])
                    actual.extend(
                        a + timedelta(days=i) for i in range((b - a).days + 1)
                    )
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(expected))
        self.assertEqual(
            {
                day(j["params"]["trade_date"])
                for j in jobs
                if j["api_name"] == "sw_daily"
            },
            expected,
        )

    def test_all_foundation_variants_and_old_unknown_statuses(self):
        config = {
            "history_start": "20240101",
            "market_apis": [
                "fund_basic",
                "fut_basic",
                "index_classify",
                "fund_div",
                "index_member_all",
            ],
        }
        ids = {
            "funds": [
                {"ts_code": "000001.OF", "status": "D"},
                {"ts_code": "000002.OF", "status": "UNKNOWN"},
            ],
            "sw_l3": [
                {"index_code": "850111.SI", "level": "L3"},
                {"index_code": "801010.SI", "level": "L1"},
            ],
        }
        jobs = list(iter_market_jobs(config, date(2024, 1, 3), ids))
        basic = [j["params"] for j in jobs if j["api_name"] == "fund_basic"]
        self.assertEqual(len(basic), 8)
        self.assertEqual({p.get("status") for p in basic}, {"D", "I", "L", None})
        self.assertEqual(len([j for j in jobs if j["api_name"] == "fut_basic"]), 12)
        self.assertTrue(all("list_date" not in j["params"] for j in jobs))
        self.assertEqual(len([j for j in jobs if j["api_name"] == "index_classify"]), 6)
        self.assertEqual(
            {j["params"]["ts_code"] for j in jobs if j["api_name"] == "fund_div"},
            {"000001.OF", "000002.OF"},
        )
        members = [j["params"] for j in jobs if j["api_name"] == "index_member_all"]
        self.assertEqual({p["l3_code"] for p in members}, {"850111.SI"})
        self.assertEqual({p["is_new"] for p in members}, {"Y", "N"})

    def test_documented_fields_params_and_cap_routes(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())
        schemas = {a: e for e in catalog["entries"] for a in e["api_names"]}
        ids = {
            "funds": ["000001.OF"],
            "indexes": ["000300.SH"],
            "bonds": ["113001.SH"],
            "sw_l3": ["850111.SI"],
        }
        jobs = list(
            iter_market_jobs({"history_start": "20240101"}, date(2024, 1, 3), ids)
        )
        self.assertEqual({j["api_name"] for j in jobs}, set(MARKET_CONTRACTS))
        for job in jobs:
            self.assertTrue(
                set(job["params"]) <= set(schemas[job["api_name"]]["input_fields"]), job
            )
        for api, spec in MARKET_CONTRACTS.items():
            fields = set(schemas[api]["output_fields"]) | set(spec["extra_fields"])
            self.assertTrue(set(spec["keys"]) <= fields, api)
            self.assertTrue(set(spec["required_fields"]) <= fields, api)
            if spec["split"]:
                self.assertTrue(
                    {spec["split"]["start_param"], spec["split"]["end_param"]}
                    <= set(schemas[api]["input_fields"])
                )
            if spec.get("saturation_param"):
                self.assertIn(spec["saturation_param"], schemas[api]["input_fields"])
        self.assertIn("src", schemas["index_classify"]["output_fields"])
        self.assertIn("trade_time_desc", schemas["fut_basic"]["output_fields"])
        self.assertIn("wh_id", MARKET_CONTRACTS["fut_wsr"]["keys"])
        manager = next(j for j in jobs if j["api_name"] == "fund_manager")
        self.assertEqual(manager["params"], {"offset": 0, "limit": 1000})
        self.assertNotIn("saturation_param", MARKET_CONTRACTS["index_weight"])

    def test_dependencies_and_invalid_identifiers(self):
        self.assertEqual(
            {g["api_name"] for g in market_prerequisites({}, ["fund_nav", "cb_rate"])},
            {"fund_nav", "cb_rate"},
        )
        self.assertFalse(market_prerequisites({}, []))
        with self.assertRaises(ValueError):
            list(
                iter_market_jobs(
                    {"history_start": "20240101"},
                    date(2024, 1, 3),
                    {"bonds": [{"name": "missing code"}]},
                )
            )
        with self.assertRaises(ValueError):
            list(iter_market_jobs({"history_start": "20240230"}, date(2024, 3, 3)))


if __name__ == "__main__":
    unittest.main()
