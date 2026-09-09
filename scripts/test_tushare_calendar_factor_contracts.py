"""Offline schema, legal date-axis and source-discovery checks for calendar/factors."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_calendar_extra_contracts as cal
from backend.shared import tushare_factor_library_contracts as fac


class CalendarFactorContracts(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            mock = patch(
                target, side_effect=AssertionError("pure planner must stay offline")
            )
            mock.start()
            self.addCleanup(mock.stop)
        self.today = date(2026, 9, 9)
        self.ids = {
            "factor_library_factors": [
                {"factor_name": "Observed_CASE", "asset_type": "STK"},
                {"factor_name": "实际来源名称", "asset_type": "STK"},
            ]
        }

    def test_all26_fields_and_catalog_known_explanatory_gap(self):
        entries = {
            a: e
            for e in json.loads((ROOT / "config/tushare-catalog.json").read_text())[
                "entries"
            ]
            for a in e["api_names"]
        }
        total = 0
        for mod, contracts in (
            (cal, cal.CALENDAR_EXTRA_CONTRACTS),
            (fac, fac.FACTOR_LIBRARY_CONTRACTS),
        ):
            for api, spec in contracts.items():
                total += len(mod.FIELDS[api])
                self.assertEqual(spec["requested_fields"], spec["required_fields"])
                self.assertEqual(spec["extra_fields"], mod.FIELDS[api])
                self.assertEqual(mod.INPUT_FIELDS[api], entries[api]["input_fields"])
                self.assertEqual(spec["hidden_fields"], [])
                self.assertEqual(set(spec["field_gaps"]), set(mod.FIELDS[api]))
                self.assertEqual(spec["permission_status"], "unprobed")
                self.assertIsNone(spec["history_start"])
                self.assertEqual(len(spec["source_html_sha256"]), 64)
                if api == "factor_list":
                    expected_extra = {
                        "Alpha101",
                        "Growth",
                        "Liquidity",
                        "Momentum",
                        "Quality",
                        "Reversal",
                        "Risk",
                        "Size",
                        "Value",
                    }
                    actual_extra = set(entries[api]["output_fields"]) - set(
                        mod.FIELDS[api]
                    )
                    # Parent may fix the catalog independently. No other drift accepted.
                    self.assertIn(actual_extra, (expected_extra, set()))
                    self.assertFalse(
                        set(mod.FIELDS[api]) - set(entries[api]["output_fields"])
                    )
                else:
                    self.assertEqual(mod.FIELDS[api], entries[api]["output_fields"])
        self.assertEqual(total, 26)
        self.assertEqual(
            fac.FIELDS["factor_list"],
            ["factor_name", "asset_type", "factor_type", "factor_desc"],
        )

    def test_calendar_day_month_axes_all_source_and_future_bounds(self):
        jobs = list(cal.iter_calendar_extra_jobs({}, self.today))
        by = {a: [j["params"] for j in jobs if j["api_name"] == a] for a in cal.FIELDS}
        self.assertEqual(
            by["eco_cal"],
            [
                {"date": (self.today + timedelta(days=i)).strftime("%Y%m%d")}
                for i in range(-6, 8)
            ],
        )
        self.assertEqual(
            by["cn_schedule"], [{"m": "202608"}, {"m": "202609"}, {"m": "202610"}]
        )
        self.assertEqual(
            by["idx_anns"],
            [
                {"ann_date": (self.today + timedelta(days=i)).strftime("%Y%m%d")}
                for i in range(-6, 1)
            ],
        )
        self.assertTrue(all(j["epoch"] != "history" for j in jobs))
        self.assertEqual(
            set(jobs[0]), {"api_name", "params", "fields", "epoch", "priority"}
        )

    def test_leap_boundary_scope_no_date_or_month_overlap(self):
        today = date(2024, 3, 3)
        jobs = list(cal.iter_calendar_extra_jobs({"history_start": "20240117"}, today))
        for api in ("eco_cal", "idx_anns"):
            axis = cal.CALENDAR_EXTRA_CONTRACTS[api]["exact_date_param"]
            values = [j["params"][axis] for j in jobs if j["api_name"] == api]
            end = today + timedelta(days=7 if api == "eco_cal" else 0)
            expected = [
                (date(2024, 1, 17) + timedelta(days=i)).strftime("%Y%m%d")
                for i in range((end - date(2024, 1, 17)).days + 1)
            ]
            self.assertEqual(sorted(values), expected)
            self.assertIn("20240229", values)
        months = [j["params"]["m"] for j in jobs if j["api_name"] == "cn_schedule"]
        self.assertEqual(sorted(months), ["202401", "202402", "202403", "202404"])
        newyear = list(
            cal.iter_calendar_extra_jobs(
                {"calendar_extra_apis": ["cn_schedule"]}, date(2026, 1, 1)
            )
        )
        self.assertEqual(
            [j["params"]["m"] for j in newyear], ["202512", "202601", "202602"]
        )

    def test_actual_factor_records_only_no_demo_or_ids(self):
        no_ids = list(
            fac.iter_factor_library_jobs({"history_start": "19900101"}, self.today)
        )
        self.assertEqual(len(no_ids), 1)
        self.assertEqual(no_ids[0]["api_name"], "factor_list")
        self.assertEqual(no_ids[0]["params"], {})
        jobs = list(fac.iter_factor_library_jobs({}, self.today, self.ids))
        values = [j for j in jobs if j["api_name"] == "factor_value"]
        self.assertEqual(len(values), 14)
        self.assertEqual(
            {j["params"]["factor_name"] for j in values},
            {"Observed_CASE", "实际来源名称"},
        )
        for j in values:
            self.assertEqual(set(j["params"]), {"factor_name", "trade_date"})
        with self.assertRaises(ValueError):
            list(
                fac.iter_factor_library_jobs(
                    {}, self.today, {"factor_library_factors": ["MACD"]}
                )
            )
        with self.assertRaises(ValueError):
            list(
                fac.iter_factor_library_jobs(
                    {},
                    self.today,
                    {"factor_library_factors": [{"factor_id": 1, "asset_type": "STK"}]},
                )
            )

    def test_factor_unsupported_assets_collision_and_duplicate_names(self):
        records = self.ids["factor_library_factors"] + [
            {"factor_name": "Observed_CASE", "asset_type": "STK"},
            {"factor_name": "collision", "asset_type": "STK"},
            {"factor_name": "collision", "asset_type": "ETF"},
            {"factor_name": "future_index", "asset_type": "IDX"},
        ]
        ids = {"factor_library_factors": records}
        jobs = list(fac.iter_factor_library_jobs({}, self.today, ids))
        self.assertEqual(len(jobs), 15)
        gaps = fac.factor_library_prerequisites(ids)
        blocked = [
            g for g in gaps if g["reason"] == "unsupported_or_ambiguous_factor_asset"
        ]
        self.assertEqual(
            {g["factor_name"] for g in blocked}, {"collision", "future_index"}
        )
        self.assertTrue(all(not g["universe_complete"] for g in blocked))

    def test_factor_history_covers_every_day_without_snapshot_history(self):
        jobs = list(
            fac.iter_factor_library_jobs(
                {"history_start": "20260830", "planning_epoch": "stable"},
                self.today,
                self.ids,
            )
        )
        self.assertEqual(len([j for j in jobs if j["api_name"] == "factor_list"]), 1)
        for name in ("Observed_CASE", "实际来源名称"):
            selected = [j for j in jobs if j["params"].get("factor_name") == name]
            self.assertEqual(len(selected), 11)
            self.assertEqual(len({j["params"]["trade_date"] for j in selected}), 11)
            self.assertEqual({j["epoch"] for j in selected}, {"stable", "history"})
        self.assertEqual(
            jobs,
            list(
                fac.iter_factor_library_jobs(
                    {"history_start": "20260830", "planning_epoch": "stable"},
                    self.today,
                    self.ids,
                )
            ),
        )

    def test_gaps_remain_despite_configured_scope(self):
        for _module, prereq in (
            (cal, cal.calendar_extra_prerequisites),
            (fac, fac.factor_library_prerequisites),
        ):
            gaps = prereq(config={"history_start": "19900101"})
            self.assertIn(
                "configured_scope_not_verified_complete", {g["reason"] for g in gaps}
            )
            self.assertIn("permission_gap", {g["reason"] for g in gaps})
            self.assertIn("pit_gap", {g["reason"] for g in gaps})
        self.assertIsNone(cal.CALENDAR_EXTRA_CONTRACTS["cn_schedule"]["split"])
        self.assertIsNone(fac.FACTOR_LIBRARY_CONTRACTS["factor_list"]["split"])
        self.assertFalse(
            fac.FACTOR_LIBRARY_CONTRACTS["factor_list"]["row_cap_verified"]
        )
        self.assertEqual(fac.FACTOR_LIBRARY_CONTRACTS["factor_value"]["row_cap"], 6000)
        self.assertEqual(cal.CALENDAR_EXTRA_CONTRACTS["eco_cal"]["row_cap"], 100)
        self.assertEqual(
            cal.CALENDAR_EXTRA_CONTRACTS["idx_anns"]["attachment_fields"], ["url"]
        )

    def test_config_validation_disabled_and_legal_params(self):
        for family, planner in (
            ("calendar_extra", cal.iter_calendar_extra_jobs),
            ("factor_library", fac.iter_factor_library_jobs),
        ):
            for bad in (family, ["does_not_exist"]):
                with self.assertRaises(ValueError):
                    list(planner({family + "_apis": bad}, self.today))
            with self.assertRaises(ValueError):
                list(planner({"history_start": "20260910"}, self.today))
            self.assertEqual(list(planner({family + "_apis": []}, self.today)), [])
        for mod, planner in (
            (cal, cal.iter_calendar_extra_jobs),
            (fac, fac.iter_factor_library_jobs),
        ):
            for job in planner({"history_start": "20260901"}, self.today, self.ids):
                self.assertLessEqual(
                    set(job["params"]), set(mod.INPUT_FIELDS[job["api_name"]])
                )
                self.assertEqual(job["fields"].split(","), mod.FIELDS[job["api_name"]])
                self.assertNotIn("offset", job["params"])

    def test_lazy_large_scope_and_per_api_scope(self):
        jobs = list(
            islice(
                fac.iter_factor_library_jobs(
                    {"history_start": "19900101"}, self.today, self.ids
                ),
                16,
            )
        )
        self.assertEqual(jobs[-1]["epoch"], "history")
        self.assertEqual(jobs[-1]["params"]["trade_date"], "19900101")
        jobs = list(
            cal.iter_calendar_extra_jobs(
                {
                    "calendar_extra_apis": ["idx_anns"],
                    "calendar_extra_history_start": {"idx_anns": "20260908"},
                },
                self.today,
            )
        )
        self.assertEqual(
            [j["params"] for j in jobs],
            [{"ann_date": "20260908"}, {"ann_date": "20260909"}],
        )


if __name__ == "__main__":
    unittest.main()
