#!/usr/bin/env python3
"""Offline contract and coverage checks; never reads credentials or calls APIs."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_other_contracts import (  # noqa: E402
    OTHER_CONTRACTS,
    FIELDS,
    CURRENCIES,
    OPTION_EXCHANGES,
    iter_other_jobs,
    other_prerequisites,
)


class OtherContracts(unittest.TestCase):
    def test_catalog_fields_and_digit_named_terms(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        self.assertEqual(len(OTHER_CONTRACTS), 15)
        for api, spec in OTHER_CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertTrue(set(entry["output_fields"]) <= set(FIELDS[api]))
            self.assertEqual(set(FIELDS[api]), set(spec["extra_fields"]))
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertEqual(spec["positive_fields"], [])
            self.assertNotIn("pagination", spec)
        self.assertEqual(
            set(FIELDS["libor"]),
            {"date", "curr_type", "on", "1w", "1m", "2m", "3m", "6m", "12m"},
        )
        self.assertEqual(
            set(FIELDS["hibor"]),
            {"date", "on", "1w", "2w", "1m", "2m", "3m", "6m", "12m"},
        )
        self.assertIn("exchange", FIELDS["fx_daily"])
        self.assertIn("traget_spread", FIELDS["fx_obasic"])
        self.assertEqual(
            OTHER_CONTRACTS["us_tycr"]["field_history_start"], {"m4": "20221019"}
        )
        self.assertEqual(OTHER_CONTRACTS["opt_daily"]["row_cap"], 15000)
        self.assertFalse(OTHER_CONTRACTS["opt_basic"]["row_cap_verified"])

    def test_discovery_unfiltered_and_no_active_status_bias(self):
        jobs = list(
            iter_other_jobs(
                {"other_apis": ["opt_basic", "sge_basic", "fx_obasic"]},
                date(2026, 9, 9),
            )
        )
        for api in ("opt_basic", "sge_basic", "fx_obasic"):
            self.assertIn({}, [j["params"] for j in jobs if j["api_name"] == api])
        exchanges = {j["params"]["exchange"] for j in jobs if "exchange" in j["params"]}
        self.assertEqual(exchanges, set(OPTION_EXCHANGES))
        self.assertTrue(
            all(
                not {
                    "list_status",
                    "classify",
                    "offset",
                    "limit",
                    "start_date",
                    "end_date",
                }
                & j["params"].keys()
                for j in jobs
            )
        )
        listed = [j for j in jobs if "list_date" in j["params"]]
        self.assertEqual(len(listed), 7)
        self.assertEqual(OTHER_CONTRACTS["opt_daily"]["saturation_fallback"], "options")

    def test_exact_leap_coverage_no_range_overlap_and_currency_loss(self):
        config = {
            "other_apis": [
                "opt_basic",
                "opt_daily",
                "sge_daily",
                "fx_daily",
                "libor",
                "hibor",
                "us_tbr",
            ],
            "other_history_start": "20231229",
            "planning_epoch": "stable",
        }
        today = date(2024, 3, 9)
        with patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            jobs = list(iter_other_jobs(config, today))
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(
            all(
                j["priority"] == 20 and j["epoch"] == "stable"
                for j in jobs[:first_history]
            )
        )
        self.assertTrue(all(j["priority"] == 40 for j in jobs[first_history:]))
        expected = {
            date(2023, 12, 29) + timedelta(days=i)
            for i in range((today - date(2023, 12, 29)).days + 1)
        }
        for api in config["other_apis"]:
            for currency in CURRENCIES if api == "libor" else (None,):
                actual = []
                for j in jobs:
                    p = j["params"]
                    if j["api_name"] != api or p.get("curr_type") != currency:
                        continue
                    if "start_date" in p:
                        start = datetime.strptime(p["start_date"], "%Y%m%d").date()
                        end = datetime.strptime(p["end_date"], "%Y%m%d").date()
                        self.assertLessEqual((end - start).days + 1, 366)
                        actual.extend(
                            start + timedelta(days=i)
                            for i in range((end - start).days + 1)
                        )
                    elif "list_date" in p or "trade_date" in p:
                        actual.append(
                            datetime.strptime(
                                p.get("list_date", p.get("trade_date")), "%Y%m%d"
                            ).date()
                        )
                self.assertEqual(set(actual), expected, (api, currency))
                self.assertEqual(len(actual), len(expected), (api, currency))
        self.assertEqual(jobs, list(iter_other_jobs(config, today)))

    def test_missing_bounds_do_not_invent_history(self):
        config = {"other_apis": ["opt_daily", "fx_daily", "us_tycr", "gz_index"]}
        jobs = list(iter_other_jobs(config, date(2026, 9, 9)))
        self.assertTrue(all(j["epoch"] != "history" for j in jobs))
        self.assertIn({}, [j["params"] for j in jobs if j["api_name"] == "gz_index"])
        gaps = other_prerequisites(config=config)
        self.assertEqual(
            {g["api_name"] for g in gaps if g["reason"].startswith("unknown_history")},
            set(config["other_apis"]),
        )
        later = other_prerequisites(
            config={"other_apis": ["libor"], "history_start": "19900101"}
        )
        self.assertIn(
            "configured_start_excludes_documented_history", {g["reason"] for g in later}
        )
        scoped = other_prerequisites(
            config={"other_apis": ["us_tycr"], "other_history_start": "19000101"}
        )
        self.assertEqual(
            scoped[0]["reason"],
            "configured_scope_does_not_prove_earlier_history_absent",
        )

    def test_known_history_defaults_efficiency_and_raw_identifiers(self):
        jobs = list(
            iter_other_jobs({"other_apis": ["libor", "hibor"]}, date(2026, 9, 9))
        )
        libor = [j for j in jobs if j["api_name"] == "libor"]
        self.assertEqual(min(j["params"]["start_date"] for j in libor), "19860101")
        self.assertEqual({j["params"]["curr_type"] for j in libor}, set(CURRENCIES))
        self.assertLess(len(jobs), 300)
        ids = {
            "options": [{"ts_code": "M1707-C-2400.DCE", "delist_date": "20170607"}],
            "spot_metals": ["Au(T+D)", "Au99.95"],
            "fx_instruments": ["BTCUSD.FXCM", "USDCNH.FXCM"],
        }
        gaps = other_prerequisites(ids, ["opt_daily", "sge_daily", "fx_daily"])
        self.assertFalse(any(g["dependencies"] for g in gaps))
        self.assertEqual(OTHER_CONTRACTS["libor"]["keys"], ["date", "curr_type"])

    def test_reject_bad_scope_and_stream_full_history(self):
        today = date(2026, 9, 9)
        for config in (
            {"other_apis": "opt_daily"},
            {"other_apis": ["save_portfolio"]},
            {"other_apis": [[]]},
            {"other_history_start": {"unknown": "20000101"}},
            {"history_start": "20260910"},
            {"other_history_start": "20260230"},
            {"other_history_start": 19860101},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(iter_other_jobs(config, today))
        for ids in (
            [],
            {"options": "M1707-C-2400.DCE"},
            {"spot_metals": ["Au99.95,Au99.99"]},
            {"fx_instruments": ["USD CNY"]},
            {"options": [{}]},
        ):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                list(iter_other_jobs({}, today, ids))
        first = list(islice(iter_other_jobs({"history_start": "19000101"}, today), 100))
        self.assertEqual(len(first), 100)
        # A scalar family override takes precedence over generic history_start.
        jobs = list(
            iter_other_jobs(
                {
                    "other_apis": ["us_tbr"],
                    "history_start": "20000101",
                    "other_history_start": {"us_tbr": "20260908"},
                },
                today,
            )
        )
        self.assertEqual(
            jobs[0]["params"], {"start_date": "20260908", "end_date": "20260909"}
        )


if __name__ == "__main__":
    unittest.main()
