#!/usr/bin/env python3
"""Offline global contracts/planning verification; no API calls or data writes."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_global_contracts import (  # noqa: E402
    GLOBAL_CONTRACTS,
    FIELDS,
    global_prerequisites,
    iter_global_jobs,
)


class GlobalContracts(unittest.TestCase):
    def test_catalog_and_all_hidden_fields(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        self.assertEqual(len(GLOBAL_CONTRACTS), 17)
        for api, spec in GLOBAL_CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(set(FIELDS[api]), set(entry["output_fields"]))
            self.assertEqual(set(spec["extra_fields"]), set(FIELDS[api]))
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
        self.assertIn("enname", FIELDS["us_basic"])
        self.assertTrue(
            {"change", "turnover_ratio", "total_mv", "pe", "pb"}
            <= set(FIELDS["us_daily"])
        )

    def test_all_scopes_and_vendor_spelling(self):
        jobs = list(
            iter_global_jobs(
                {"global_apis": ["hk_basic", "us_basic"]}, date(2026, 9, 9)
            )
        )
        hk = [j["params"] for j in jobs if j["api_name"] == "hk_basic"]
        us = [j["params"] for j in jobs if j["api_name"] == "us_basic"]
        self.assertEqual({p["list_status"] for p in hk}, {"L", "D", "P"})
        self.assertEqual({p.get("list_stauts") for p in us}, {None, "L", "D", "P"})
        self.assertTrue(all("classify" not in p and "offset" not in p for p in us))
        self.assertTrue(all(p["limit"] == 6000 for p in us))

    def test_full_leap_range_recent_first_and_interleaved(self):
        config = {
            "global_apis": ["us_daily", "hk_tradecal", "monthly"],
            "global_history_start": "20240227",
            "planning_epoch": "20240312T03",
        }
        today = date(2024, 3, 12)
        with patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            jobs = list(iter_global_jobs(config, today))
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(all(j["priority"] == 20 for j in jobs[:first_history]))
        self.assertTrue(all(j["epoch"] == "20240312T03" for j in jobs[:first_history]))
        self.assertTrue(all(j["priority"] == 40 for j in jobs[first_history:]))
        self.assertEqual(
            [j["api_name"] for j in jobs[first_history : first_history + 3]],
            config["global_apis"],
        )
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
            for i in range(15)
        }
        for api in config["global_apis"]:
            rows = [j["params"] for j in jobs if j["api_name"] == api]
            actual = [p.get("trade_date", p.get("start_date")) for p in rows]
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(expected))
        calendars = [j["params"] for j in jobs if j["api_name"] == "hk_tradecal"]
        self.assertTrue(
            all(
                p["start_date"] == p["end_date"] and "is_open" not in p
                for p in calendars
            )
        )
        self.assertEqual(jobs, list(iter_global_jobs(config, today)))

    def test_current_incomplete_week_month_and_weekend(self):
        config = {"global_apis": ["stk_weekly_monthly", "stk_week_month_adj"]}
        jobs = list(iter_global_jobs(config, date(2026, 9, 9)))
        for api in config["global_apis"]:
            params = [j["params"] for j in jobs if j["api_name"] == api]
            self.assertIn({"trade_date": "20260911", "freq": "week"}, params)
            self.assertIn({"trade_date": "20260930", "freq": "month"}, params)
            self.assertEqual(
                len(params), len({json.dumps(p, sort_keys=True) for p in params})
            )
            self.assertTrue({"freq", "end_date"} <= set(GLOBAL_CONTRACTS[api]["keys"]))
        weekend = list(iter_global_jobs(config, date(2026, 9, 12)))
        self.assertFalse(
            any(
                j["params"] == {"trade_date": "20260918", "freq": "week"}
                for j in weekend
            )
        )

    def test_known_history_default_is_complete_and_lazy(self):
        jobs = iter_global_jobs({"global_apis": ["index_dailybasic"]}, date(2026, 9, 9))
        first = list(islice(jobs, 8))
        self.assertEqual(first[-1]["params"], {"trade_date": "20040101"})
        self.assertEqual(first[-1]["epoch"], "history")
        remainder = list(jobs)
        self.assertEqual(remainder[-1]["params"], {"trade_date": "20260902"})
        self.assertEqual(
            len(first) + len(remainder), (date(2026, 9, 9) - date(2004, 1, 1)).days + 1
        )

    def test_unknown_lower_bound_gap_and_per_api_scope(self):
        config = {
            "global_apis": ["hk_daily", "us_daily"],
            "global_history_start": {"hk_daily": "20260830"},
        }
        gaps = global_prerequisites(config=config)
        self.assertIn(
            {
                "api_name": "us_daily",
                "dependencies": [],
                "reason": "unknown_history_start_requires_explicit_scope_or_evidence",
            },
            gaps,
        )
        jobs = list(iter_global_jobs(config, date(2026, 9, 9)))
        self.assertEqual(
            {j["api_name"] for j in jobs if j["epoch"] == "history"}, {"hk_daily"}
        )
        self.assertIsNone(GLOBAL_CONTRACTS["hk_daily"]["history_start"])
        self.assertFalse(GLOBAL_CONTRACTS["hk_daily"]["history_bound_verified"])
        self.assertEqual(
            len(
                list(iter_global_jobs({"global_apis": ["us_daily"]}, date(2026, 9, 9)))
            ),
            7,
        )

    def test_saturation_families_include_retired_and_punctuation(self):
        ids = {
            "us_stocks": [{"ts_code": "BRK.B", "list_stauts": "D"}, "AAPL", "BF-A"],
            "hk_stocks": [{"ts_code": "00001.HK", "list_status": "D"}],
            "indexes": ["000001.SH"],
            "stocks": ["920061.BJ"],
        }
        gaps = global_prerequisites(
            ids,
            ["us_adjfactor", "hk_daily", "index_weekly", "monthly"],
            {"global_history_start": "20260901"},
        )
        self.assertEqual(gaps, [])
        self.assertEqual(
            GLOBAL_CONTRACTS["us_adjfactor"]["saturation_fallback"], "us_stocks"
        )
        self.assertEqual(
            GLOBAL_CONTRACTS["index_weekly"]["saturation_fallback"], "indexes"
        )
        self.assertIn("exchange", GLOBAL_CONTRACTS["us_adjfactor"]["keys"])
        self.assertIn("exchange", GLOBAL_CONTRACTS["us_daily_adj"]["keys"])
        all_us = list(
            iter_global_jobs({"global_apis": ["us_daily_adj"]}, date(2026, 9, 9), ids)
        )
        self.assertTrue(
            all(
                "exchange" not in j["params"] and j["params"]["limit"] == 8000
                for j in all_us
            )
        )

    def test_permissions_caps_and_adjustment_revisions(self):
        self.assertEqual(GLOBAL_CONTRACTS["monthly"]["row_cap"], 4500)
        self.assertEqual(GLOBAL_CONTRACTS["us_adjfactor"]["row_cap"], 15000)
        self.assertFalse(GLOBAL_CONTRACTS["hk_basic"]["row_cap_verified"])
        for api in (
            "hk_daily",
            "hk_daily_adj",
            "hk_adjfactor",
            "us_daily",
            "us_daily_adj",
            "us_adjfactor",
        ):
            self.assertTrue(GLOBAL_CONTRACTS[api]["independent_permission"])
        for api in (
            "hk_daily_adj",
            "us_daily_adj",
            "hk_adjfactor",
            "us_adjfactor",
            "stk_week_month_adj",
        ):
            self.assertIn("revision_note", GLOBAL_CONTRACTS[api])
        self.assertIn(
            "close_price", GLOBAL_CONTRACTS["us_adjfactor"]["nullable_fields"]
        )

    def test_validation_before_first_job(self):
        bad_configs = [
            {"global_apis": ["missing"]},
            {"global_apis": "us_daily"},
            {"global_history_start": "not-date"},
            {"global_history_start": {"missing": "20260101"}},
            {"global_history_start": "20270101"},
            {"global_history_start": 20260101},
        ]
        for config in bad_configs:
            with self.assertRaises(ValueError):
                next(iter_global_jobs(config, date(2026, 9, 9)))
        for ids in (
            {"hk_stocks": ["HK00001"]},
            {"us_stocks": ["AAPL,MSFT"]},
            {"stocks": ["SH600000"]},
        ):
            with self.assertRaises(ValueError):
                next(iter_global_jobs({}, date(2026, 9, 9), ids))
        self.assertEqual(
            list(iter_global_jobs({"global_apis": []}, date(2026, 9, 9))), []
        )


if __name__ == "__main__":
    unittest.main()
