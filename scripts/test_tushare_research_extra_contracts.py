#!/usr/bin/env python3
"""Pure six-API contracts/plans: source-date semantics, preservation and bounds."""

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
from backend.shared.tushare_research_extra_contracts import (  # noqa: E402
    FIELDS,
    INPUT_FIELDS,
    RESEARCH_EXTRA_CONTRACTS as CONTRACTS,
    iter_research_extra_jobs as jobs,
    research_extra_prerequisites as prerequisites,
)


class ResearchExtraContracts(unittest.TestCase):
    def setUp(self):
        for target in (
            patch.object(
                socket.socket, "connect", side_effect=AssertionError("No network")
            ),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
        ):
            target.start()
            self.addCleanup(target.stop)

    def test_official_fields_and_parameters_complete(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        self.assertEqual(len(CONTRACTS), 6)
        for api, spec in CONTRACTS.items():
            entry = next(e for e in catalog if api in e["api_names"])
            self.assertEqual(set(FIELDS[api]), set(entry["output_fields"]))
            self.assertEqual(set(INPUT_FIELDS[api]), set(entry["input_fields"]))
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertFalse(spec["row_cap_verified"])
            self.assertFalse(spec["independent_permission"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertEqual(spec["attachment_fields"], [])
        self.assertEqual(CONTRACTS["disclosure_date"]["hidden_fields"], ["modify_date"])
        self.assertEqual(
            CONTRACTS["report_rc"]["hidden_fields"], ["imp_dg", "create_time"]
        )
        self.assertEqual(CONTRACTS["stk_surv"]["hidden_fields"], ["content"])
        self.assertIsNone(CONTRACTS["fina_audit"]["documented_row_cap"])

    def test_publication_report_survey_and_month_axes_are_distinct(self):
        scope = {"research_extra_history_start": "20260801"}
        all_jobs = list(jobs(scope, date(2026, 9, 9), {"stocks": ["600000.SH"]}))
        for job in all_jobs:
            api, params = job["api_name"], job["params"]
            self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
            self.assertNotIn("offset", params)
            self.assertNotIn("limit", params)
            if api == "fina_audit":
                self.assertIn("ts_code", params)
                self.assertNotIn("period", params)
            elif api == "fina_mainbz":
                self.assertIn(params["type"], ("P", "D", "I"))
                self.assertNotIn("ann_date", params)
            elif api == "disclosure_date":
                self.assertNotIn("start_date", params)
            elif api == "report_rc":
                self.assertEqual(set(params), {"report_date"})
            elif api == "stk_surv":
                self.assertEqual(set(params), {"trade_date"})
            elif api == "broker_recommend":
                self.assertEqual(set(params), {"month"})
                self.assertEqual(len(params["month"]), 6)
        first_history = next(
            i for i, j in enumerate(all_jobs) if j["epoch"] == "history"
        )
        self.assertTrue(all(j["priority"] == 20 for j in all_jobs[:first_history]))
        self.assertTrue(
            all(
                j["epoch"] == "history" and j["priority"] == 40
                for j in all_jobs[first_history:]
            )
        )

    def test_raw_supplier_code_retired_and_type_identities_are_retained(self):
        scope = {
            "research_extra_apis": ["fina_audit", "fina_mainbz"],
            "research_extra_history_start": "20250101",
        }
        ids = {
            "stocks": [
                "600018.SH",
                {"ts_code": "T600018.SH", "list_status": "D"},
                "920061.BJ",
                "T600018.SH",
            ]
        }
        result = list(jobs(scope, date(2026, 9, 9), ids))
        self.assertEqual(
            {j["params"]["ts_code"] for j in result},
            {"600018.SH", "T600018.SH", "920061.BJ"},
        )
        for code in ("600018.SH", "T600018.SH", "920061.BJ"):
            self.assertEqual(
                {
                    j["params"]["type"]
                    for j in result
                    if j["api_name"] == "fina_mainbz" and j["params"]["ts_code"] == code
                },
                {"P", "D", "I"},
            )
        self.assertEqual(
            len(
                [
                    j
                    for j in result
                    if j["api_name"] == "fina_audit" and j["priority"] == 20
                ]
            ),
            3,
        )
        self.assertEqual(CONTRACTS["fina_mainbz"]["request_identity_fields"], ["type"])
        self.assertTrue(
            {"bz_code", "bz_item", "curr_type"} <= set(CONTRACTS["fina_mainbz"]["keys"])
        )
        self.assertTrue(
            {"org_name", "author_name", "quarter", "report_title"}
            <= set(CONTRACTS["report_rc"]["keys"])
        )
        self.assertTrue(
            {"rece_org", "fund_visitors", "rece_place"}
            <= set(CONTRACTS["stk_surv"]["keys"])
        )
        self.assertIn("broker", CONTRACTS["broker_recommend"]["keys"])

    def test_known_report_history_and_no_assumed_original_report_entitlement(self):
        scope = {"research_extra_apis": ["report_rc"]}
        result = list(jobs(scope, date(2010, 1, 10)))
        dates = {j["params"]["report_date"] for j in result}
        self.assertEqual(dates, {f"201001{n:02d}" for n in range(1, 11)})
        self.assertEqual(
            result, list(jobs({**scope, "history_start": None}, date(2010, 1, 10)))
        )
        self.assertEqual(CONTRACTS["report_rc"]["minimum_points"], 8000)
        self.assertIn("research_report", CONTRACTS["report_rc"]["permission_note"])
        self.assertNotIn("research_report", CONTRACTS)

    def test_unknown_history_and_discovery_are_explicit(self):
        gaps = prerequisites()
        self.assertEqual(
            {
                g["api_name"]
                for g in gaps
                if g["reason"] == "unknown_history_start_requires_scope_or_discovery"
            },
            set(CONTRACTS) - {"report_rc"},
        )
        result = list(
            jobs(
                {"research_extra_apis": ["fina_audit", "fina_mainbz"]}, date(2026, 9, 9)
            )
        )
        self.assertEqual(result, [])
        ids = {"stocks": ["600000.SH"]}
        discovered = list(
            jobs(
                {"research_extra_apis": ["fina_audit", "fina_mainbz"]},
                date(2026, 9, 9),
                ids,
            )
        )
        history = [j for j in discovered if j["epoch"] == "history"]
        self.assertEqual(len(history), 4)
        self.assertTrue(all("start_date" not in j["params"] for j in history))
        scoped = prerequisites(ids, config={"research_extra_history_start": "19900101"})
        self.assertEqual(
            len(
                [
                    g
                    for g in scoped
                    if g["reason"]
                    == "configured_scope_does_not_prove_earlier_history_absent"
                ]
            ),
            5,
        )
        self.assertTrue(
            all(not g["universe_complete"] for g in scoped if "universe_complete" in g)
        )

    def test_main_business_fixed_years_weekly_refresh_and_full_scope(self):
        config = {
            "research_extra_apis": ["fina_mainbz"],
            "research_extra_history_start": "20200229",
        }
        ids = {"stocks": ["600000.SH"]}
        first = list(jobs(config, date(2026, 9, 9), ids))
        self.assertEqual(
            first,
            list(
                jobs({**config, "planning_epoch": "different"}, date(2026, 9, 10), ids)
            ),
        )
        ranges = sorted(
            (
                date.fromisoformat(j["params"]["start_date"]),
                date.fromisoformat(j["params"]["end_date"]),
            )
            for j in first
            if j["params"]["type"] == "P"
        )
        cursor = date(2020, 2, 29)
        for left, right in ranges:
            self.assertEqual(left, cursor)
            cursor = right + timedelta(days=1)
        self.assertEqual(cursor, date(2026, 9, 7))
        history = [j for j in first if j["epoch"] == "history"]
        later = list(jobs(config, date(2026, 10, 7), ids))
        self.assertTrue(all(j in later for j in history))

    def test_disclosure_quarter_history_future_snapshot_and_hidden_revision(self):
        scope = {
            "research_extra_apis": ["disclosure_date"],
            "research_extra_history_start": "20240229",
        }
        result = list(jobs(scope, date(2025, 1, 2)))
        self.assertEqual(result[0]["params"], {})
        periods = [j["params"]["end_date"] for j in result if j["epoch"] == "history"]
        self.assertEqual(periods, ["20240331", "20240630", "20240930", "20241231"])
        self.assertIsNone(CONTRACTS["disclosure_date"]["split"])
        self.assertEqual(CONTRACTS["disclosure_date"]["saturation_fallback"], "stocks")
        self.assertIn("future_gap", CONTRACTS["disclosure_date"])

    def test_monthly_recommendations_cover_year_boundary(self):
        scope = {
            "research_extra_apis": ["broker_recommend"],
            "research_extra_history_start": "20240229",
        }
        result = list(jobs(scope, date(2025, 1, 2)))
        self.assertEqual(
            [j["params"]["month"] for j in result[:2]], ["202501", "202412"]
        )
        self.assertEqual(
            {j["params"]["month"] for j in result},
            {f"2024{m:02d}" for m in range(2, 13)} | {"202501"},
        )
        self.assertNotIn("saturation_fallback", CONTRACTS["broker_recommend"])
        self.assertIsNone(CONTRACTS["broker_recommend"]["split"])

    def test_lazy_history_validates_inputs_before_first_job(self):
        for config in (
            {"research_extra_apis": "report_rc"},
            {"research_extra_apis": ["unknown"]},
            {"research_extra_history_start": "20270101"},
            {"research_extra_history_start": {"unknown": "20200101"}},
            {"research_extra_history_start": 20200101},
        ):
            with self.assertRaises(ValueError):
                next(jobs(config, date(2026, 9, 9)))
        for values in (
            ["SH600000"],
            ["600000.SH,000001.SZ"],
            ["600000.SH\n"],
            ["600000.sh"],
        ):
            with self.assertRaises(ValueError):
                next(jobs({}, date(2026, 9, 9), {"stocks": values}))
        with patch(
            "backend.shared.tushare_research_extra_contracts._history",
            side_effect=AssertionError("History eagerly consumed"),
        ):
            self.assertEqual(
                len(
                    list(
                        islice(
                            jobs(
                                {"research_extra_history_start": "19000101"},
                                date(2026, 9, 9),
                            ),
                            10,
                        )
                    )
                ),
                10,
            )
        self.assertEqual(list(jobs({"research_extra_apis": []}, date(2026, 9, 9))), [])


if __name__ == "__main__":
    unittest.main()
