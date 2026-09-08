"""Offline THS/DC schema, current membership and distinct source namespaces."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_concept_extra_contracts import (  # noqa: E402
    CONCEPT_EXTRA_CONTRACTS as CONTRACTS,
    FIELDS,
    INPUT_FIELDS,
    DC_VARIANTS,
    concept_extra_prerequisites as gaps,
    iter_concept_extra_jobs as jobs,
)

IDS = {
    "ths_indices": [
        "885728.TI",
        {"ts_code": "HK_REFERENCE.TI", "exchange": "HK"},
        {"ts_code": "US_REFERENCE.TI", "exchange": "US"},
        {"ts_code": "OLD_REFERENCE.TI", "list_status": "D"},
    ],
    "stocks": ["600036.SH"],
    "dc_indices": ["BK1186.DC"],
}


class ConceptExtra(unittest.TestCase):
    def test_full_official_fields_parameters_and_unprobed_permissions(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(
            set(CONTRACTS), {"ths_index", "ths_daily", "ths_member", "dc_index"}
        )
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertEqual(spec["minimum_points"], 6000)
            self.assertIsNone(spec["independent_permission"])
            self.assertIsNone(spec["history_start"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertEqual(spec["positive_fields"], [])
        self.assertEqual(sum(map(len, FIELDS.values())), 40)
        self.assertEqual(
            [s["row_cap"] for s in CONTRACTS.values()], [5000, 3000, 5000, 5000]
        )
        self.assertFalse(CONTRACTS["ths_member"]["row_cap_verified"])
        self.assertTrue(
            all(
                s["row_cap_verified"] for a, s in CONTRACTS.items() if a != "ths_member"
            )
        )
        self.assertEqual(CONTRACTS["ths_member"]["documented_requests_per_minute"], 200)

    def test_hidden_columns_are_requested_and_unavailable_membership_is_not_history(
        self,
    ):
        self.assertEqual(
            CONTRACTS["ths_daily"]["hidden_fields"], ["total_mv", "float_mv"]
        )
        member = CONTRACTS["ths_member"]
        self.assertEqual(
            member["hidden_fields"], ["weight", "in_date", "out_date", "is_new"]
        )
        self.assertEqual(
            member["unavailable_fields"], ["weight", "in_date", "out_date"]
        )
        self.assertTrue(member["snapshot_only"])
        self.assertIsNone(member["date_field"])
        self.assertIsNone(member["split"])
        for api in ("ths_daily", "ths_member"):
            for field in CONTRACTS[api]["hidden_fields"]:
                self.assertIn(field, CONTRACTS[api]["required_fields"])
                self.assertIn(field, CONTRACTS[api]["nullable_fields"])
        for j in jobs({"concept_extra_apis": ["ths_member"]}, date(2026, 9, 9), IDS):
            self.assertEqual(set(j["params"]), {"ts_code"})
            self.assertTrue(set(member["hidden_fields"]) <= set(j["fields"].split(",")))
        self.assertNotIn("is_new", INPUT_FIELDS["ths_member"])
        self.assertTrue(any(g["reason"] == "cap_note" for g in gaps(IDS)))

    def test_master_is_one_unfiltered_snapshot_not_market_type_or_date_grid(self):
        config = {
            "concept_extra_apis": ["ths_index", "ths_index"],
            "history_start": "19000101",
            "planning_epoch": "fixed",
        }
        plan = list(jobs(config, date(2026, 9, 9), IDS))
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["params"], {})
        self.assertEqual(plan[0]["epoch"], "fixed")
        self.assertEqual(
            CONTRACTS["ths_index"]["documented_exchanges"], ["A", "HK", "US"]
        )
        self.assertEqual(
            CONTRACTS["ths_index"]["documented_types"],
            ["N", "I", "R", "S", "ST", "TH", "BB"],
        )
        self.assertNotIn("saturation_fallback", CONTRACTS["ths_index"])
        self.assertIn("not to loop", CONTRACTS["ths_index"]["discovery_gap"])

    def test_members_use_all_source_indices_without_stock_or_status_filtering(self):
        config = {"concept_extra_apis": ["ths_member"], "history_start": "19000101"}
        before = json.dumps(IDS, sort_keys=True)
        plan = list(jobs(config, date(2026, 9, 9), IDS))
        self.assertEqual(
            {j["params"]["ts_code"] for j in plan},
            {"885728.TI", "HK_REFERENCE.TI", "US_REFERENCE.TI", "OLD_REFERENCE.TI"},
        )
        self.assertEqual(CONTRACTS["ths_member"]["dependencies"], ["ths_indices"])
        self.assertEqual(json.dumps(IDS, sort_keys=True), before)
        self.assertEqual(list(jobs(config, date(2026, 9, 9))), [])
        missing = [g for g in gaps(config=config) if g.get("dependencies")]
        self.assertEqual(missing[0]["reason"], "awaiting_stored_ths_indices")
        self.assertFalse(missing[0]["universe_complete"])
        self.assertIn("foreign members", CONTRACTS["ths_member"]["namespace_note"])

    def test_dc_required_categories_identity_and_namespace_are_explicit(self):
        self.assertEqual(
            DC_VARIANTS, [{"idx_type": x} for x in ("行业板块", "概念板块", "地域板块")]
        )
        spec = CONTRACTS["dc_index"]
        self.assertEqual(spec["required_params"], ["idx_type"])
        self.assertEqual(spec["request_identity_fields"], ["idx_type"])
        self.assertEqual(spec["saturation_fallback"], "dc_indices")
        self.assertIn("BK1186.DC", spec["namespace_note"])
        self.assertIn("not demonstrated", spec["namespace_note"])
        self.assertNotIn("request_identity_fields", CONTRACTS["ths_index"])
        self.assertEqual(CONTRACTS["ths_daily"]["saturation_fallback"], "ths_indices")

    def test_recent_and_history_days_cover_leap_day_once_per_category(self):
        config = {"concept_extra_history_start": "20240227"}
        plan = list(jobs(config, date(2024, 3, 5), IDS))
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        self.assertEqual(len(plan), 37)  # 8 THS daily + 24 DC + 1 master + 4 members.
        for api in ("ths_daily", "dc_index"):
            rows = [j for j in plan if j["api_name"] == api]
            keys = [
                (j["params"]["trade_date"], j["params"].get("idx_type")) for j in rows
            ]
            variants = (
                ("行业板块", "概念板块", "地域板块") if api == "dc_index" else (None,)
            )
            self.assertEqual(set(keys), {(d, v) for d in expected for v in variants})
            self.assertEqual(len(keys), len(set(keys)))
        for j in plan:
            self.assertTrue(set(j["params"]) <= set(INPUT_FIELDS[j["api_name"]]))
            self.assertEqual(j["fields"].split(","), FIELDS[j["api_name"]])
            self.assertNotIn("offset", j["params"])
            self.assertNotIn("limit", j["params"])
        priorities = [j["priority"] for j in plan]
        self.assertEqual(priorities, sorted(priorities))

    def test_unknown_lower_bounds_and_lazy_round_robin_remain_bounded(self):
        plan = list(jobs({}, date(2026, 9, 9), IDS))
        self.assertEqual(len(plan), 33)  # 28 daily partitions + 1 master + 4 members.
        self.assertTrue(all(j["epoch"] != "history" for j in plan))
        history = list(
            islice(jobs({"history_start": "19000101"}, date(2026, 9, 9), IDS), 37)
        )[33:]
        self.assertEqual(
            [j["api_name"] for j in history], ["ths_daily", "dc_index"] * 2
        )
        self.assertEqual(history[0]["params"]["trade_date"], "19000101")
        self.assertEqual(history[1]["params"]["trade_date"], "19000101")
        unknown = {
            g["api_name"]
            for g in gaps(IDS)
            if g["reason"] == "unknown_history_start_requires_scope_or_discovery"
        }
        self.assertEqual(unknown, {"ths_daily", "dc_index"})

    def test_invalid_config_and_identifiers_only_validate_actual_dependency(self):
        for ids in (
            {"ths_indices": "885728.TI"},
            {"ths_indices": [""]},
            {"ths_indices": ["885728.TI,885001.TI"]},
            {"ths_indices": ["bad code"]},
            {"ths_indices": [{}]},
        ):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                list(
                    jobs({"concept_extra_apis": ["ths_member"]}, date(2026, 9, 9), ids)
                )
            self.assertEqual(
                len(
                    list(
                        jobs(
                            {"concept_extra_apis": ["ths_index"]}, date(2026, 9, 9), ids
                        )
                    )
                ),
                1,
            )
        for config in (
            {"concept_extra_apis": "ths_index"},
            {"concept_extra_apis": ["bad"]},
            {"concept_extra_history_start": 1},
            {"concept_extra_history_start": {"bad": "20260101"}},
            {"history_start": "20260230"},
            {"history_start": "2026-01-01"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(jobs(config, date(2026, 9, 9)))
        self.assertEqual(list(jobs({"concept_extra_apis": []}, date(2026, 9, 9))), [])


if __name__ == "__main__":
    unittest.main()
