"""Offline schema/partition/history checks for the four trading-event candidates."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_trading_event_contracts import (  # noqa: E402
    TRADING_EVENT_CONTRACTS as CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
    iter_trading_event_jobs as jobs,
    trading_event_prerequisites as gaps,
)


class TradingEvents(unittest.TestCase):
    def test_complete_reviewed_schema_and_published_limits(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(
            set(CONTRACTS), {"top_list", "top_inst", "hm_list", "hm_detail"}
        )
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            if api != "hm_list":
                self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertEqual(spec["positive_fields"], [])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertNotIn("_row_identity", FIELDS[api])
            self.assertNotIn("offset", INPUT_FIELDS[api])
            self.assertNotIn("limit", INPUT_FIELDS[api])
        self.assertEqual(
            [CONTRACTS[a]["row_cap"] for a in CONTRACTS], [10000, 10000, 1000, 2000]
        )
        self.assertEqual(
            [CONTRACTS[a]["minimum_points"] for a in CONTRACTS],
            [2000, 5000, 5000, 10000],
        )
        self.assertEqual(sum(map(len, FIELDS.values())), 37)

    def test_hm_list_catalog_examples_are_not_output_schema(self):
        self.assertEqual(FIELDS["hm_list"], ["name", "desc", "orgs"])
        for name in ("zhouyu1933", "bike770", "Asking"):
            self.assertNotIn(name, CONTRACTS["hm_list"]["requested_fields"])
        self.assertIn("opaque", CONTRACTS["hm_list"]["field_note"])

    def test_hidden_tag_requested_and_required_but_nullable(self):
        spec = CONTRACTS["hm_detail"]
        self.assertEqual(spec["hidden_fields"], ["tag"])
        self.assertIn("tag", spec["required_fields"])
        self.assertIn("tag", spec["nullable_fields"])
        first = next(jobs({"trading_event_apis": ["hm_detail"]}, date(2026, 9, 9)))
        self.assertEqual(first["fields"].split(","), FIELDS["hm_detail"])
        self.assertTrue(
            any(
                g["reason"]
                == "explicit_hidden_field_request_and_response_schema_audit_required"
                for g in gaps()
            )
        )
        # A fields='' request does not meet this candidate's acquisition contract.
        self.assertNotEqual(first["fields"], "")

    def test_reason_side_and_org_labels_are_kept_in_candidate_keys(self):
        self.assertIn("reason", CONTRACTS["top_list"]["keys"])
        self.assertTrue(
            {"exalter", "side", "reason"} <= set(CONTRACTS["top_inst"]["keys"])
        )
        self.assertTrue(
            {"hm_name", "hm_orgs", "tag"} <= set(CONTRACTS["hm_detail"]["keys"])
        )
        for spec in CONTRACTS.values():
            self.assertIn("multiplicity", spec["multiplicity_gap"])

    def test_recent_and_history_cover_calendar_days_once_with_legal_params(self):
        today = date(2024, 3, 5)
        config = {"history_start": "20240227"}
        planned = list(jobs(config, today))
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        for api in ("top_list", "top_inst", "hm_detail"):
            rows = [j for j in planned if j["api_name"] == api]
            self.assertEqual({j["params"]["trade_date"] for j in rows}, expected)
            self.assertEqual(len(rows), len(expected))
            for row in rows:
                self.assertEqual(set(row["params"]), {"trade_date"})
                self.assertTrue(set(row["params"]) <= set(INPUT_FIELDS[api]))
                self.assertEqual(row["fields"].split(","), FIELDS[api])
        snapshots = [j for j in planned if j["api_name"] == "hm_list"]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["params"], {})
        priorities = [j["priority"] for j in planned]
        self.assertEqual(priorities, sorted(priorities))

    def test_documented_year_month_floor_and_unknown_history(self):
        self.assertEqual(CONTRACTS["top_list"]["history_precision"], "year")
        self.assertEqual(CONTRACTS["hm_detail"]["history_precision"], "month")
        plan = list(islice(jobs({}, date(2026, 9, 9)), 24))
        historical = [j for j in plan if j["epoch"] == "history"]
        self.assertEqual(
            [(j["api_name"], j["params"]) for j in historical],
            [
                ("top_list", {"trade_date": "20050101"}),
                ("hm_detail", {"trade_date": "20220801"}),
            ],
        )
        self.assertEqual(
            len(list(jobs({"trading_event_apis": ["top_inst"]}, date(2026, 9, 9)))), 7
        )
        self.assertTrue(
            any(
                g["api_name"] == "top_inst"
                and g["reason"] == "unknown_history_start_requires_scope_or_discovery"
                for g in gaps()
            )
        )

    def test_family_and_api_scopes_clamp_to_documented_floors(self):
        config = {
            "history_start": "20260901",
            "trading_event_history_start": {
                "top_list": "20000101",
                "hm_detail": "20000101",
                "top_inst": "20260907",
            },
        }
        plan = list(islice(jobs(config, date(2026, 9, 9)), 20))
        historical = [j for j in plan if j["epoch"] == "history"]
        self.assertEqual(
            [j["params"]["trade_date"] for j in historical[:2]],
            ["20050101", "20220801"],
        )
        self.assertEqual(len([j for j in plan if j["api_name"] == "top_inst"]), 3)
        same = list(
            jobs(
                {
                    "trading_event_apis": ["top_inst"],
                    "trading_event_history_start": "20260908",
                },
                date(2026, 9, 9),
            )
        )
        self.assertEqual(len(same), 2)

    def test_hm_list_never_fabricates_historical_snapshot(self):
        config = {
            "trading_event_apis": ["hm_list", "hm_list"],
            "history_start": "19000101",
            "planning_epoch": "fixed",
        }
        rows = list(jobs(config, datetime(2026, 9, 9, 10)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["epoch"], "fixed")
        self.assertEqual(rows[0]["params"], {})
        self.assertTrue(CONTRACTS["hm_list"]["snapshot_only"])

    def test_lazy_history_and_round_robin_are_independent_of_current_universe(self):
        config = {
            "trading_event_apis": ["top_inst", "top_list", "hm_detail"],
            "history_start": "19000101",
        }
        ids = {
            "stocks": [{"ts_code": "T600018.SH", "list_status": "D"}],
            "other": ["not-needed"],
        }
        before = json.dumps(ids, sort_keys=True)
        a = list(islice(jobs(config, date(2026, 9, 9), ids), 27))
        b = list(islice(jobs(config, date(2026, 9, 9)), 27))
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(ids, sort_keys=True), before)
        self.assertEqual(
            [j["api_name"] for j in a[21:]], ["top_inst", "top_list", "hm_detail"] * 2
        )
        self.assertEqual(a[21]["params"], {"trade_date": "19000101"})

    def test_invalid_configuration_is_rejected(self):
        for config in (
            {"trading_event_apis": "top_list"},
            {"trading_event_apis": ["unknown"]},
            {"trading_event_history_start": 1},
            {"trading_event_history_start": {"bad": "20260101"}},
            {"history_start": "20260230"},
            {"history_start": "2026-01-01"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(jobs(config, date(2026, 9, 9)))
        with self.assertRaises(ValueError):
            list(jobs({}, "20260909"))
        self.assertEqual(list(jobs({"trading_event_apis": []}, date(2026, 9, 9))), [])


if __name__ == "__main__":
    unittest.main()
