#!/usr/bin/env python3
"""Pure PCF source fields, date coverage, identity and no guessed history."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_etf_basket_contracts import (  # noqa: E402
    ETF_BASKET_CONTRACTS as CONTRACTS,
    INPUT_FIELDS,
    etf_basket_prerequisites as prerequisites,
    iter_etf_basket_jobs as jobs,
)


class EtfBasketContracts(unittest.TestCase):
    def setUp(self):
        for target in (
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("No network")
            ),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.ids = {"etfs": ["517030.SH", "159051.SZ"]}

    def test_complete_source_fields_and_cash_semantics(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        self.assertEqual(set(CONTRACTS), {"etf_sh_cons", "etf_sz_cons"})
        for api, spec in CONTRACTS.items():
            entry = next(e for e in catalog if api in e["api_names"])
            self.assertEqual(set(spec["extra_fields"]), set(entry["output_fields"]))
            self.assertEqual(set(INPUT_FIELDS[api]), set(entry["input_fields"]))
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(spec["row_cap"], 3000)
            self.assertFalse(spec["row_cap_verified"])
            self.assertEqual(spec["minimum_points"], 8000)
            self.assertIsNone(spec["independent_permission"])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertTrue(
                {"ts_code", "trade_date", "con_code", "exchange"} <= set(spec["keys"])
            )
            self.assertEqual(spec["positive_fields"], [])
            self.assertIn("qty", spec["nullable_fields"])
            self.assertEqual(spec["units"]["qty"], "shares")
            self.assertNotIn("known_at", spec["extra_fields"])
            self.assertIsNone(spec["history_start"])
        self.assertNotEqual(
            CONTRACTS["etf_sh_cons"]["cash_semantics"]["cpr"],
            CONTRACTS["etf_sz_cons"]["cash_semantics"]["cpr"],
        )
        self.assertIn("sca", CONTRACTS["etf_sh_cons"]["raw_numeric_fields"])
        self.assertTrue(
            {"sub_cc", "red_cc"} <= set(CONTRACTS["etf_sz_cons"]["raw_numeric_fields"])
        )

    def test_recent_then_history_complete_scoped_dates_including_leap_day(self):
        start, today = date(2024, 1, 17), date(2024, 3, 5)
        result = list(jobs({"etf_basket_history_start": "20240117"}, today, self.ids))
        self.assertEqual(
            [j["api_name"] for j in result[:2]], ["etf_sh_cons", "etf_sz_cons"]
        )
        self.assertEqual([j["priority"] for j in result[:2]], [20, 20])
        self.assertTrue(
            all(j["priority"] == 40 and j["epoch"] == "history" for j in result[2:])
        )
        expected = {start + timedelta(days=i) for i in range((today - start).days + 1)}
        for api in CONTRACTS:
            observed = []
            for job in result:
                if job["api_name"] != api:
                    continue
                params = job["params"]
                self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
                left, right = (
                    date.fromisoformat(params[k]) for k in ("start_date", "end_date")
                )
                observed += [
                    left + timedelta(days=i) for i in range((right - left).days + 1)
                ]
            self.assertEqual(set(observed), expected)
            self.assertEqual(len(observed), len(expected))
            self.assertIn(date(2024, 2, 29), observed)

    def test_stable_old_windows_daily_tail_and_epoch_override(self):
        config = {"etf_basket_history_start": "20200115", "planning_epoch": "refresh-1"}
        first = list(jobs(config, date(2026, 9, 9), self.ids))
        second = list(jobs(config, date(2026, 9, 10), self.ids))

        def old(seq):
            return {
                json.dumps(j, sort_keys=True) for j in seq if j["epoch"] == "history"
            }

        self.assertTrue(old(first) < old(second))
        self.assertEqual(len(old(second) - old(first)), 2)
        self.assertEqual(first[0]["epoch"], "refresh-1")
        self.assertTrue(
            any(
                j["params"].get("start_date") == "20200115"
                and j["params"]["end_date"] == "20201231"
                for j in first
            )
        )
        self.assertEqual(first, list(jobs(config, date(2026, 9, 9), self.ids)))

    def test_unknown_history_uses_only_unfiltered_discovery_no_fake_start(self):
        result = list(jobs({}, date(2026, 9, 9), self.ids))
        self.assertEqual(len(result), 4)
        self.assertTrue(
            all(
                set(j["params"]) == {"ts_code"}
                for j in result
                if j["epoch"] == "history"
            )
        )
        reasons = {g["reason"] for g in prerequisites(self.ids)}
        self.assertIn("unknown_history_start_requires_discovery", reasons)
        self.assertIn("publication_gap", reasons)
        self.assertIn("pagination_gap", reasons)
        self.assertIn("basket_scope_gap", reasons)
        scoped = prerequisites(
            self.ids, config={"etf_basket_history_start": "20260101"}
        )
        self.assertIn(
            "configured_scope_does_not_prove_earlier_history_absent",
            {g["reason"] for g in scoped},
        )

    def test_opaque_etf_and_unsupported_market_are_preserved(self):
        ids = {
            "etfs": [
                "517030.SH",
                "T517030.SH",
                {"ts_code": "159051.SZ", "list_status": "D"},
                "900001.BJ",
                "517030.SH",
            ]
        }
        result = list(jobs({}, date(2026, 9, 9), ids))
        self.assertEqual(
            {j["params"]["ts_code"] for j in result},
            {"517030.SH", "T517030.SH", "159051.SZ"},
        )
        gap = next(
            g
            for g in prerequisites(ids)
            if g["reason"] == "no_documented_basket_endpoint_for_etf_market"
        )
        self.assertEqual(gap["codes"], ["900001.BJ"])
        self.assertEqual(list(jobs({}, date(2026, 9, 9))), [])
        self.assertIn(
            "awaiting_stored_etf_discovery", {g["reason"] for g in prerequisites()}
        )

    def test_legal_date_split_contract_and_large_history_is_lazy(self):
        result = list(
            islice(
                jobs(
                    {"etf_basket_history_start": "19000101"}, date(2026, 9, 9), self.ids
                ),
                6,
            )
        )
        self.assertEqual(len(result), 6)
        for spec in CONTRACTS.values():
            self.assertEqual(
                spec["split"],
                {
                    "start_param": "start_date",
                    "end_param": "end_date",
                    "precision": "day",
                },
            )
            self.assertNotIn("offset", spec["input_fields"])
            self.assertIn("con_code", spec["input_fields"])
            self.assertNotIn("stocks", spec["dependencies"])
        for config in (
            {"etf_basket_apis": ["fake"]},
            {"etf_basket_history_start": "20270101"},
            {"etf_basket_history_start": {"fake": "20200101"}},
        ):
            with self.assertRaises(ValueError):
                list(jobs(config, date(2026, 9, 9), self.ids))
        with self.assertRaises(ValueError):
            list(jobs({}, date(2026, 9, 9), {"etfs": ["SH.517030"]}))


if __name__ == "__main__":
    unittest.main()
