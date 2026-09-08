#!/usr/bin/env python3
"""Offline event contracts: date-axis coverage, row preservation and valid params."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_equity_event_contracts import (  # noqa: E402
    EQUITY_EVENT_CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
    TOP10,
    iter_equity_event_jobs,
    equity_event_prerequisites,
)

IDS = {
    "stocks": [{"ts_code": "600000.SH", "list_status": "D"}, {"ts_code": "920000.BJ"}]
}


def dates(start, end):
    return {start + timedelta(days=i) for i in range((end - start).days + 1)}


def parse(value):
    return datetime.strptime(value, "%Y%m%d").date()


class EquityEvents(unittest.TestCase):
    def test_seven_exact_contracts_full_fields_and_no_invented_alias(self):
        apis = {
            "dividend",
            "stk_holdernumber",
            "stk_holdertrade",
            "repurchase",
            "share_float",
            "top10_holders",
            "top10_floatholders",
        }
        self.assertEqual(set(EQUITY_EVENT_CONTRACTS), apis)
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        for api, spec in EQUITY_EVENT_CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(set(FIELDS[api]), set(entry["output_fields"]))
            self.assertEqual(set(spec["extra_fields"]), set(FIELDS[api]))
            self.assertEqual(set(spec["input_fields"]), set(entry["input_fields"]))
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertNotIn("_row_identity", spec["extra_fields"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertEqual(spec["positive_fields"], [])
            self.assertNotIn("pagination", spec)
            self.assertNotIn("catalog_api", spec)
            self.assertNotIn("dataset_identity", spec)
            self.assertEqual(spec["preserve_distinct_rows"], api != "stk_holdernumber")
        self.assertEqual(
            EQUITY_EVENT_CONTRACTS["dividend"]["hidden_fields"],
            ["base_date", "base_share"],
        )
        self.assertEqual(
            EQUITY_EVENT_CONTRACTS["stk_holdertrade"]["hidden_fields"],
            ["begin_date", "close_date"],
        )
        self.assertEqual(
            EQUITY_EVENT_CONTRACTS["stk_holdernumber"]["keys"],
            ["ts_code", "ann_date", "end_date"],
        )
        self.assertIsNone(EQUITY_EVENT_CONTRACTS["dividend"]["split"])
        for api in TOP10 + ("repurchase",):
            self.assertFalse(EQUITY_EVENT_CONTRACTS[api]["row_cap_verified"])
            self.assertIn("cap_note", EQUITY_EVENT_CONTRACTS[api])

    def test_requests_only_use_documented_axes_and_preserve_types(self):
        config = {"equity_event_history_start": "20240227", "planning_epoch": "fixture"}
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            jobs = list(iter_equity_event_jobs(config, date(2024, 3, 12), IDS))
        for job in jobs:
            api, params = job["api_name"], job["params"]
            self.assertTrue(set(params) <= set(INPUT_FIELDS[api]), job)
            self.assertNotIn("offset", params)
            self.assertNotIn("limit", params)
            self.assertNotIn("trade_type", params)
            self.assertNotIn("holder_type", params)
            if api in TOP10:
                self.assertIn("ts_code", params)
            if api == "repurchase":
                self.assertNotIn("ts_code", params)
            if api == "dividend":
                self.assertEqual(len(params), 1)
                self.assertIn(
                    next(iter(params)), ("ts_code", "ann_date", "imp_ann_date")
                )
        self.assertEqual(
            jobs, list(iter_equity_event_jobs(config, date(2024, 3, 12), IDS))
        )
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(
            all(
                j["priority"] == 20 and j["epoch"] == "fixture"
                for j in jobs[:first_history]
            )
        )
        self.assertTrue(all(j["priority"] == 40 for j in jobs[first_history:]))
        dividend_history = [
            j["params"]
            for j in jobs
            if j["api_name"] == "dividend" and j["epoch"] == "history"
        ]
        self.assertEqual(
            dividend_history, [{"ts_code": "600000.SH"}, {"ts_code": "920000.BJ"}]
        )

    def test_announcement_and_unlock_axes_cover_leap_days_independently(self):
        begin, today = date(2024, 2, 27), date(2024, 3, 12)
        apis = ["stk_holdernumber", "stk_holdertrade", "repurchase", "share_float"]
        jobs = list(
            iter_equity_event_jobs(
                {"equity_event_apis": apis, "history_start": "20240227"}, today
            )
        )
        for api in apis:
            observed = []
            for j in jobs:
                p = j["params"]
                if j["api_name"] == api and "start_date" in p:
                    observed.extend(dates(parse(p["start_date"]), parse(p["end_date"])))
            self.assertEqual(set(observed), dates(begin, today))
            self.assertEqual(len(observed), len(set(observed)))
        # Historical AND recent announcements discover future unlock events.
        announced = [
            j["params"]
            for j in jobs
            if j["api_name"] == "share_float" and "ann_date" in j["params"]
        ]
        self.assertEqual({parse(p["ann_date"]) for p in announced}, dates(begin, today))
        self.assertTrue(all(set(p) == {"ann_date"} for p in announced))
        self.assertEqual(
            EQUITY_EVENT_CONTRACTS["share_float"]["split_axis"], "float_date"
        )
        self.assertEqual(
            EQUITY_EVENT_CONTRACTS["stk_holdernumber"]["split_axis"],
            "announcement_date",
        )
        self.assertIn("enddate", INPUT_FIELDS["stk_holdernumber"])

    def test_report_history_plus_400_day_refresh_have_exact_report_coverage(self):
        begin, today = date(2023, 1, 1), date(2025, 3, 9)
        jobs = list(
            iter_equity_event_jobs(
                {
                    "equity_event_apis": list(TOP10),
                    "equity_event_history_start": "20230101",
                },
                today,
                IDS,
            )
        )
        for api in TOP10:
            self.assertEqual(EQUITY_EVENT_CONTRACTS[api]["split_axis"], "report_period")
            for stock in ("600000.SH", "920000.BJ"):
                observed = []
                for j in jobs:
                    p = j["params"]
                    if j["api_name"] == api and p["ts_code"] == stock:
                        chunk = dates(parse(p["start_date"]), parse(p["end_date"]))
                        if j["epoch"] != "history":
                            self.assertEqual(len(chunk), 400)
                        else:
                            self.assertLessEqual(len(chunk), 366)
                        observed.extend(chunk)
                        self.assertNotIn("ann_date", p)
                self.assertEqual(set(observed), dates(begin, today))
                self.assertEqual(len(observed), len(set(observed)))

    def test_missing_stock_discovery_and_unknown_history_are_gaps(self):
        config = {"equity_event_apis": ["dividend", *TOP10, "repurchase"]}
        jobs = list(iter_equity_event_jobs(config, date(2026, 9, 9)))
        self.assertTrue(any(j["api_name"] == "dividend" for j in jobs))
        self.assertTrue(any(j["api_name"] == "repurchase" for j in jobs))
        self.assertFalse(any(j["api_name"] in TOP10 for j in jobs))
        gaps = equity_event_prerequisites(config=config)
        self.assertTrue(
            any(g["reason"] == "awaiting_stored_stock_discovery" for g in gaps)
        )
        self.assertTrue(
            any(
                g["reason"] == "unknown_history_start_requires_scope_or_discovery"
                for g in gaps
            )
        )
        discovered = equity_event_prerequisites(IDS, enabled_apis=["dividend", *TOP10])
        self.assertTrue(
            all(not g["universe_complete"] for g in discovered if g["dependencies"])
        )
        unknown = list(
            iter_equity_event_jobs(
                {"equity_event_apis": list(TOP10)}, date(2026, 9, 9), IDS
            )
        )
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code"}
                for j in unknown
                if j["epoch"] == "history"
            )
        )
        self.assertTrue(any(g["reason"] == "refresh_gap" for g in discovered))

    def test_configuration_validation_and_streaming(self):
        today = date(2026, 9, 9)
        for config in (
            {"equity_event_apis": "dividend"},
            {"equity_event_apis": ["income_vip"]},
            {"equity_event_apis": [[]]},
            {"equity_event_history_start": 19900101},
            {"equity_event_history_start": {"unknown": "19900101"}},
            {"history_start": "20260230"},
            {"history_start": "20260910"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(iter_equity_event_jobs(config, today, IDS))
        for ids in (
            [],
            {"stocks": "600000.SH"},
            {"stocks": ["600000.SH,920000.BJ"]},
            {"stocks": ["SH600000"]},
            {"stocks": [{}]},
        ):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                list(iter_equity_event_jobs({}, today, ids))
        jobs = list(
            iter_equity_event_jobs(
                {
                    "equity_event_apis": ["stk_holdernumber"],
                    "history_start": "19900101",
                    "equity_event_history_start": {"stk_holdernumber": "20260908"},
                },
                today,
            )
        )
        self.assertEqual(
            jobs[0]["params"], {"start_date": "20260908", "end_date": "20260909"}
        )
        stream = iter_equity_event_jobs({"history_start": "19000101"}, today, IDS)
        self.assertEqual(len(list(islice(stream, 100))), 100)
        self.assertEqual(
            list(iter_equity_event_jobs({"equity_event_apis": []}, today)), []
        )


if __name__ == "__main__":
    unittest.main()
