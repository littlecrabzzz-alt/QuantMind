"""Offline price-limit schema, pool identity and causal date-scope checks."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_limit_extra_contracts import (  # noqa: E402
    FIELDS,
    INPUT_FIELDS,
    VARIANTS,
    HIDDEN_THS_FIELDS,
    LIMIT_EXTRA_CONTRACTS as CONTRACTS,
    iter_limit_extra_jobs as jobs,
    limit_extra_prerequisites as gaps,
)


class LimitExtra(unittest.TestCase):
    def test_all_official_fields_inputs_limits_and_permission_uncertainty(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(
            set(CONTRACTS),
            {"limit_list_ths", "limit_list_d", "limit_step", "limit_cpt_list"},
        )
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["positive_fields"], [])
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertEqual(spec["split_axis"], "trade_date")
        self.assertEqual(sum(map(len, FIELDS.values())), 55)
        self.assertEqual(
            [s["row_cap"] for s in CONTRACTS.values()], [4000, 2500, 2000, 2000]
        )
        self.assertEqual(
            [s["minimum_points"] for s in CONTRACTS.values()], [8000, 5000, 8000, 8000]
        )
        self.assertEqual(
            CONTRACTS["limit_list_d"]["documented_daily_requests"]["5000_points"], 10000
        )

    def test_six_hidden_ths_columns_require_presence_allow_pool_nulls(self):
        self.assertEqual(
            HIDDEN_THS_FIELDS,
            [
                "first_lu_time",
                "last_lu_time",
                "first_ld_time",
                "last_ld_time",
                "rise_rate",
                "sum_float",
            ],
        )
        spec = CONTRACTS["limit_list_ths"]
        for field in HIDDEN_THS_FIELDS:
            self.assertIn(field, spec["required_fields"])
            self.assertIn(field, spec["nullable_fields"])
        self.assertIn("lu_limit_order", spec["nullable_fields"])
        for job in islice(jobs({}, date(2026, 9, 9)), 35):
            self.assertEqual(job["api_name"], "limit_list_ths")
            self.assertTrue(set(HIDDEN_THS_FIELDS) <= set(job["fields"].split(",")))
        self.assertTrue(
            any(
                g["reason"]
                == "hidden_fields_require_explicit_request_and_response_audit"
                for g in gaps()
            )
        )
        for api in ("limit_list_d", "limit_step", "limit_cpt_list"):
            self.assertEqual(CONTRACTS[api]["hidden_fields"], [])

    def test_all_five_source_pool_literals_and_three_directions_are_explicit(self):
        self.assertEqual(
            VARIANTS["limit_list_ths"],
            [
                {"limit_type": x}
                for x in ("涨停池", "连扳池", "冲刺涨停", "炸板池", "跌停池")
            ],
        )
        self.assertEqual(
            VARIANTS["limit_list_d"], [{"limit_type": x} for x in ("U", "D", "Z")]
        )
        plan = list(jobs({"history_start": "20260909"}, date(2026, 9, 9)))
        self.assertEqual(len(plan), 10)
        for api in ("limit_list_ths", "limit_list_d"):
            self.assertEqual(CONTRACTS[api]["request_identity_fields"], ["limit_type"])
            self.assertEqual(
                [
                    {k: v for k, v in j["params"].items() if k != "trade_date"}
                    for j in plan
                    if j["api_name"] == api
                ],
                VARIANTS[api],
            )
        self.assertIn("limit", CONTRACTS["limit_list_d"]["keys"])
        self.assertNotIn("limit_type", FIELDS["limit_list_d"])

    def test_pool_by_date_coverage_is_exact_through_leap_day(self):
        plan = list(jobs({"limit_extra_history_start": "20240227"}, date(2024, 3, 5)))
        dates = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        self.assertEqual(len(plan), 80)
        for api in CONTRACTS:
            actual = [
                (j["params"]["trade_date"], j["params"].get("limit_type"))
                for j in plan
                if j["api_name"] == api
            ]
            expected = {(d, v.get("limit_type")) for d in dates for v in VARIANTS[api]}
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(expected))
        priorities = [j["priority"] for j in plan]
        self.assertEqual(priorities, sorted(priorities))
        for j in plan:
            self.assertTrue(set(j["params"]) <= set(INPUT_FIELDS[j["api_name"]]))
            self.assertNotIn("offset", j["params"])
            self.assertNotIn("limit", j["params"])
            self.assertEqual(j["fields"].split(","), FIELDS[j["api_name"]])

    def test_unknown_histories_remain_gaps_known_floors_are_not_examples(self):
        plan = list(islice(jobs({}, date(2026, 9, 9)), 74))
        history = plan[70:]
        self.assertEqual(
            [j["api_name"] for j in history], ["limit_list_ths", "limit_list_d"] * 2
        )
        self.assertEqual(history[0]["params"]["trade_date"], "20231101")
        self.assertEqual(history[1]["params"]["trade_date"], "20200101")
        self.assertEqual(CONTRACTS["limit_list_d"]["history_precision"], "year")
        unknown = {
            g["api_name"]
            for g in gaps()
            if g["reason"] == "unknown_history_start_requires_scope_or_discovery"
        }
        self.assertEqual(unknown, {"limit_step", "limit_cpt_list"})
        self.assertIsNone(CONTRACTS["limit_step"]["history_start"])

    def test_st_exclusion_and_concept_namespace_do_not_leak_to_other_apis(self):
        self.assertEqual(
            CONTRACTS["limit_list_d"]["coverage_exclusions"], ["ST stocks"]
        )
        self.assertNotIn("coverage_exclusions", CONTRACTS["limit_step"])
        self.assertIn("ST names", CONTRACTS["limit_step"]["coverage_note"])
        self.assertEqual(
            CONTRACTS["limit_cpt_list"]["saturation_fallback"], "limit_concepts"
        )
        self.assertIn("885728.TI", CONTRACTS["limit_cpt_list"]["namespace_note"])
        self.assertIn(
            "rank is documented as string", CONTRACTS["limit_cpt_list"]["category_note"]
        )
        self.assertIn(
            "nums is a source string", CONTRACTS["limit_step"]["category_note"]
        )
        ids = {"stocks": ["T600018.SH", "920000.BJ"], "limit_concepts": ["885728.TI"]}
        self.assertEqual(
            list(islice(jobs({}, date(2026, 9, 9), ids), 72)),
            list(islice(jobs({}, date(2026, 9, 9)), 72)),
        )

    def test_per_api_scopes_and_lazy_history_keep_recent_epoch(self):
        config = {
            "limit_extra_apis": ["limit_step", "limit_cpt_list"],
            "history_start": "19000101",
            "limit_extra_history_start": {"limit_step": "20260908"},
            "planning_epoch": "fixed",
        }
        plan = list(islice(jobs(config, date(2026, 9, 9)), 12))
        self.assertEqual(len([j for j in plan if j["api_name"] == "limit_step"]), 2)
        self.assertEqual(plan[9]["params"], {"trade_date": "19000101"})
        self.assertTrue(all(j["epoch"] == "fixed" for j in plan[:9]))
        self.assertTrue(all(j["epoch"] == "history" for j in plan[9:]))

    def test_invalid_config_and_mutation_free_variants(self):
        before = json.dumps(VARIANTS, ensure_ascii=False, sort_keys=True)
        list(islice(jobs({}, date(2026, 9, 9)), 72))
        self.assertEqual(
            json.dumps(VARIANTS, ensure_ascii=False, sort_keys=True), before
        )
        for config in (
            {"limit_extra_apis": "limit_step"},
            {"limit_extra_apis": ["bad"]},
            {"limit_extra_history_start": 1},
            {"limit_extra_history_start": {"bad": "20260101"}},
            {"history_start": "20260230"},
            {"history_start": "2026-01-01"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                list(jobs(config, date(2026, 9, 9)))
        self.assertEqual(list(jobs({"limit_extra_apis": []}, date(2026, 9, 9))), [])


if __name__ == "__main__":
    unittest.main()
