#!/usr/bin/env python3
"""Pure planning checks; isolated from acquisition, credentials and production."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_supplement_contracts import (  # noqa: E402
    SUPPLEMENT_CONTRACTS,
    FIELDS,
    iter_supplement_jobs,
    supplement_prerequisites,
)


class SupplementContracts(unittest.TestCase):
    def test_exact_reviewed_scope_all_fields_and_source_identity(self):
        expected = {
            "moneyflow_mkt_dc",
            "moneyflow_dc",
            "moneyflow_ths",
            "etf_share_size",
            "mkt_idx_bmk",
        }
        self.assertEqual(set(SUPPLEMENT_CONTRACTS), expected)
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        for api, spec in SUPPLEMENT_CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(set(FIELDS[api]), set(entry["output_fields"]))
            self.assertEqual(set(spec["extra_fields"]), set(entry["output_fields"]))
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertNotIn("pagination", spec)
            self.assertNotIn("catalog_api", spec)
            self.assertNotIn("dataset_identity", spec)
            self.assertEqual(spec["positive_fields"], [])
        self.assertEqual(
            SUPPLEMENT_CONTRACTS["moneyflow_mkt_dc"]["keys"], ["trade_date"]
        )
        self.assertEqual(SUPPLEMENT_CONTRACTS["moneyflow_mkt_dc"]["amount_unit"], "CNY")
        self.assertEqual(
            SUPPLEMENT_CONTRACTS["moneyflow_dc"]["amount_unit"], "10000 CNY"
        )
        self.assertEqual(
            SUPPLEMENT_CONTRACTS["etf_share_size"]["hidden_fields"], ["nav", "close"]
        )
        self.assertIn("net_d5_amount", FIELDS["moneyflow_ths"])
        self.assertEqual(
            SUPPLEMENT_CONTRACTS["mkt_idx_bmk"]["keys"], ["ts_code", "bmk_level"]
        )

    def test_complete_leap_and_year_boundaries_with_recent_priority(self):
        config = {
            "supplement_apis": [
                "moneyflow_mkt_dc",
                "moneyflow_dc",
                "moneyflow_ths",
                "etf_share_size",
            ],
            "supplement_history_start": "20231229",
            "planning_epoch": "fixture",
        }
        today = date(2024, 3, 9)
        with (
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            jobs = list(iter_supplement_jobs(config, today))
        expected = {
            date(2023, 12, 29) + timedelta(days=i)
            for i in range((today - date(2023, 12, 29)).days + 1)
        }
        for api in config["supplement_apis"]:
            observed = []
            for job in jobs:
                if job["api_name"] != api:
                    continue
                params = job["params"]
                if "trade_date" in params:
                    observed.append(
                        datetime.strptime(params["trade_date"], "%Y%m%d").date()
                    )
                    self.assertEqual(set(params), {"trade_date"})
                else:
                    begin = datetime.strptime(params["start_date"], "%Y%m%d").date()
                    end = datetime.strptime(params["end_date"], "%Y%m%d").date()
                    self.assertLessEqual((end - begin).days + 1, 366)
                    observed.extend(
                        begin + timedelta(days=i) for i in range((end - begin).days + 1)
                    )
                    self.assertEqual(set(params), {"start_date", "end_date"})
            self.assertEqual(set(observed), expected, api)
            self.assertEqual(len(observed), len(expected), api)
        index = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(
            all(j["priority"] == 20 and j["epoch"] == "fixture" for j in jobs[:index])
        )
        self.assertTrue(all(j["priority"] == 40 for j in jobs[index:]))
        self.assertEqual(
            [j["api_name"] for j in jobs[index : index + 4]], config["supplement_apis"]
        )
        self.assertEqual(jobs, list(iter_supplement_jobs(config, today)))

    def test_discovery_unfiltered_levels_and_low_request_volume(self):
        jobs = list(
            iter_supplement_jobs({"supplement_apis": ["mkt_idx_bmk"]}, date(2026, 9, 9))
        )
        self.assertEqual(
            [j["params"] for j in jobs],
            [{}, {"bmk_level": "一类库"}, {"bmk_level": "二类库"}],
        )
        self.assertTrue(all("bmk_type" not in j["params"] for j in jobs))
        totals = list(
            iter_supplement_jobs(
                {"supplement_apis": ["moneyflow_mkt_dc"], "history_start": "19900101"},
                date(2026, 9, 9),
            )
        )
        self.assertLess(len(totals), 40)
        self.assertTrue(all("ts_code" not in j["params"] for j in totals))
        self.assertEqual(
            SUPPLEMENT_CONTRACTS["mkt_idx_bmk"]["discovery_family"], "indexes"
        )

    def test_known_floor_unknown_prefix_and_override_order(self):
        dc = list(
            iter_supplement_jobs(
                {"supplement_apis": ["moneyflow_dc"], "history_start": "19900101"},
                date(2023, 9, 13),
            )
        )
        self.assertEqual(
            {j["params"]["trade_date"] for j in dc},
            {"20230911", "20230912", "20230913"},
        )
        self.assertEqual(
            list(
                iter_supplement_jobs(
                    {"supplement_apis": ["moneyflow_dc"]}, date(2023, 9, 10)
                )
            ),
            [],
        )
        unknown = ["moneyflow_mkt_dc", "moneyflow_ths", "etf_share_size"]
        jobs = list(
            iter_supplement_jobs({"supplement_apis": unknown}, date(2026, 9, 9))
        )
        self.assertTrue(all(j["epoch"] != "history" for j in jobs))
        gaps = supplement_prerequisites(config={"supplement_apis": unknown})
        self.assertEqual(
            {g["api_name"] for g in gaps if not g["dependencies"]}, set(unknown)
        )
        clipped = supplement_prerequisites(
            config={"supplement_apis": ["moneyflow_dc"], "history_start": "20250101"}
        )
        self.assertIn(
            "configured_start_excludes_documented_history",
            {g["reason"] for g in clipped},
        )
        later = list(
            iter_supplement_jobs(
                {
                    "supplement_apis": ["etf_share_size"],
                    "history_start": "20000101",
                    "supplement_history_start": {"etf_share_size": "20260908"},
                },
                date(2026, 9, 9),
            )
        )
        self.assertEqual(
            [j["params"] for j in later],
            [{"trade_date": "20260908"}, {"trade_date": "20260909"}],
        )

    def test_fallback_discovery_is_not_full_universe_proof(self):
        ids = {
            "stocks": [{"ts_code": "600000.SH", "list_status": "D"}],
            "funds": ["510330.SH"],
            "indexes": [{"index_code": "000171.CSI"}],
        }
        gaps = supplement_prerequisites(ids)
        discovery = [g for g in gaps if g["dependencies"]]
        self.assertEqual(len(discovery), 4)
        self.assertTrue(
            all(
                g["observed_codes"] == 1 and not g["universe_complete"]
                for g in discovery
            )
        )
        self.assertEqual(
            {g["dependencies"][0] for g in discovery}, {"stocks", "funds", "indexes"}
        )
        missing = supplement_prerequisites({}, ["moneyflow_dc"])
        self.assertEqual(
            missing[0]["reason"], "awaiting_complete_stored_discovery_for_saturation"
        )
        # A market-wide total never depends on a malformed unrelated stock universe.
        self.assertTrue(
            list(
                iter_supplement_jobs(
                    {"supplement_apis": ["moneyflow_mkt_dc"]},
                    date(2026, 9, 9),
                    {"stocks": ["bad code"]},
                )
            )
        )

    def test_bad_configuration_and_streaming(self):
        today = date(2026, 9, 9)
        for config in (
            {"supplement_apis": "moneyflow_dc"},
            {"supplement_apis": ["save_portfolio"]},
            {"supplement_apis": [[]]},
            {"supplement_history_start": 19900101},
            {"supplement_history_start": {"unknown": "19900101"}},
            {"history_start": "20260230"},
            {"history_start": "20260910"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(iter_supplement_jobs(config, today))
        for ids in (
            [],
            {"stocks": "600000.SH"},
            {"stocks": ["600000.SH,600001.SH"]},
            {"indexes": ["../000171.CSI"]},
            {"funds": [{}]},
        ):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                list(iter_supplement_jobs({}, today, ids))
        stream = iter_supplement_jobs({"history_start": "19000101"}, today)
        self.assertEqual(len(list(islice(stream, 100))), 100)
        self.assertEqual(list(iter_supplement_jobs({"supplement_apis": []}, today)), [])


if __name__ == "__main__":
    unittest.main()
