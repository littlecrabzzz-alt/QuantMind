"""Offline reviewed schema, source namespaces and issuance/history date planning."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_listing_extra_contracts import (  # noqa: E402
    DAILY_INFO_STARTS,
    FIELDS,
    INPUT_FIELDS,
    LISTING_EXTRA_CONTRACTS as CONTRACTS,
    iter_listing_extra_jobs as jobs,
    listing_extra_prerequisites as gaps,
)


class ListingExtra(unittest.TestCase):
    def test_all_reviewed_fields_limits_and_unprobed_rights(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(
            set(CONTRACTS), {"bak_basic", "new_share", "bse_mapping", "daily_info"}
        )
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            if api != "daily_info":
                self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertEqual(spec["positive_fields"], [])
            self.assertEqual(spec["dependencies"], [])
            self.assertTrue(spec["preserve_distinct_rows"])
        self.assertEqual(sum(map(len, FIELDS.values())), 54)
        self.assertEqual(
            [CONTRACTS[a]["row_cap"] for a in CONTRACTS], [7000, 2000, 1000, 4000]
        )
        self.assertEqual(
            [CONTRACTS[a]["minimum_points"] for a in CONTRACTS], [5000, 120, 2000, 600]
        )

    def test_category_table_is_not_parameters_or_stock_identities(self):
        self.assertEqual(len(DAILY_INFO_STARTS), 31)
        self.assertEqual(
            INPUT_FIELDS["daily_info"],
            ["trade_date", "ts_code", "exchange", "start_date", "end_date", "fields"],
        )
        self.assertFalse(
            set(DAILY_INFO_STARTS).intersection(INPUT_FIELDS["daily_info"])
        )
        self.assertEqual(DAILY_INFO_STARTS["SH_A"], "19910102")
        self.assertEqual(DAILY_INFO_STARTS["SH_MARKET"], "20190102")
        self.assertEqual(DAILY_INFO_STARTS["SZ_SME"], "20040602")
        self.assertEqual(DAILY_INFO_STARTS["SH_FUND_METF"], "19901219")
        self.assertEqual(CONTRACTS["daily_info"]["history_start"], "19901219")
        self.assertIn("tr", CONTRACTS["daily_info"]["nullable_fields"])
        self.assertNotIn("saturation_fallback", CONTRACTS["daily_info"])

    def test_issuance_listing_and_mapping_effective_dates_are_not_aliases(self):
        spec = CONTRACTS["new_share"]
        self.assertEqual(spec["date_field"], "ipo_date")
        self.assertEqual(spec["split_axis"], "ipo_date")
        self.assertIn("issue_date", spec["nullable_fields"])
        self.assertNotIn("ts_code", INPUT_FIELDS["new_share"])
        self.assertNotIn("saturation_fallback", spec)
        self.assertEqual(CONTRACTS["bse_mapping"]["keys"], ["o_code", "n_code"])
        self.assertIsNone(CONTRACTS["bse_mapping"]["date_field"])
        self.assertNotIn("ts_code", FIELDS["bse_mapping"])
        self.assertIn("subscription", spec["namespace_note"])
        self.assertIn("not code-change", CONTRACTS["bse_mapping"]["date_axis_note"])

    def test_recent_history_dates_are_continuous_through_leap_day(self):
        config = {"listing_extra_history_start": "20240227"}
        plan = list(jobs(config, date(2024, 3, 5)))
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        for api in ("bak_basic", "daily_info"):
            selected = [p for p in plan if p["api_name"] == api]
            self.assertEqual({p["params"]["trade_date"] for p in selected}, expected)
            self.assertEqual(len(selected), len(expected))
        issuance = set()
        for job in plan:
            api, params = job["api_name"], job["params"]
            self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
            self.assertEqual(job["fields"].split(","), FIELDS[api])
            self.assertNotIn("offset", params)
            self.assertNotIn("limit", params)
            if api == "new_share" and params:
                day, last = (
                    datetime.strptime(params[k], "%Y%m%d").date()
                    for k in ("start_date", "end_date")
                )
                while day <= last:
                    self.assertNotIn(day.strftime("%Y%m%d"), issuance)
                    issuance.add(day.strftime("%Y%m%d"))
                    day += timedelta(days=1)
        self.assertEqual(issuance, expected)
        priorities = [j["priority"] for j in plan]
        self.assertEqual(priorities, sorted(priorities))

    def test_unknown_ipo_history_keeps_unfiltered_future_discovery_and_gap(self):
        config = {"listing_extra_apis": ["new_share"], "planning_epoch": "anchor"}
        plan = list(jobs(config, date(2026, 9, 9)))
        self.assertEqual(
            [j["params"] for j in plan],
            [{}, {"start_date": "20260903", "end_date": "20260909"}],
        )
        self.assertTrue(all(j["epoch"] == "anchor" for j in plan))
        self.assertTrue(
            any(
                g["reason"] == "unknown_history_start_requires_scope_or_discovery"
                for g in gaps(config=config)
            )
        )
        self.assertIn("future horizon", CONTRACTS["new_share"]["discovery_gap"])
        self.assertIn("illegal", CONTRACTS["new_share"]["terminal_gap"])

    def test_historical_floors_and_lazy_round_robin(self):
        plan = list(islice(jobs({"history_start": "19000101"}, date(2026, 9, 9)), 22))
        history = [j for j in plan if j["epoch"] == "history"]
        self.assertEqual(
            [j["api_name"] for j in history[:3]],
            ["bak_basic", "new_share", "daily_info"],
        )
        self.assertEqual(history[0]["params"], {"trade_date": "20160101"})
        self.assertEqual(
            history[1]["params"], {"start_date": "19000101", "end_date": "19000131"}
        )
        self.assertEqual(history[2]["params"], {"trade_date": "19901219"})
        self.assertEqual(CONTRACTS["bak_basic"]["history_precision"], "year")
        self.assertEqual(
            CONTRACTS["daily_info"]["history_precision"], "per_category_day"
        )
        self.assertEqual(history[3]["params"], {"trade_date": "20160102"})

    def test_snapshot_has_no_fabricated_date_or_current_stock_dependency(self):
        config = {
            "listing_extra_apis": ["bse_mapping", "bse_mapping"],
            "history_start": "19000101",
        }
        plan = list(
            jobs(config, date(2026, 9, 9), {"stocks": ["T600018.SH", "920163.BJ"]})
        )
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["params"], {})
        self.assertEqual(plan, list(jobs(config, date(2026, 9, 9))))
        self.assertIn("effective interval", CONTRACTS["bse_mapping"]["date_axis_note"])
        self.assertEqual(
            CONTRACTS["bak_basic"]["saturation_dependencies"],
            ["stocks", "historical_listing_securities"],
        )

    def test_per_api_start_fallback_and_invalid_configuration(self):
        config = {
            "listing_extra_apis": ["bak_basic", "new_share"],
            "history_start": "20260907",
            "listing_extra_history_start": {"bak_basic": "20260908"},
        }
        plan = list(jobs(config, date(2026, 9, 9)))
        self.assertEqual(len([j for j in plan if j["api_name"] == "bak_basic"]), 2)
        self.assertIn(
            {"start_date": "20260907", "end_date": "20260909"},
            [j["params"] for j in plan],
        )
        for config in (
            {"listing_extra_apis": "bak_basic"},
            {"listing_extra_apis": ["bad"]},
            {"listing_extra_history_start": 1},
            {"listing_extra_history_start": {"bad": "20260101"}},
            {"history_start": "2026-01-01"},
            {"history_start": "20260230"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(jobs(config, date(2026, 9, 9)))
        with self.assertRaises(ValueError):
            list(jobs({}, "20260909"))
        self.assertEqual(list(jobs({"listing_extra_apis": []}, date(2026, 9, 9))), [])


if __name__ == "__main__":
    unittest.main()
