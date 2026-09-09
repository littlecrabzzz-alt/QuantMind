"""Offline DC field completeness, distinct date axes and lazy scope planning."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_dc_extra_contracts import (  # noqa: E402
    FIELDS,
    INPUT_FIELDS,
    DAILY_VARIANTS,
    DC_EXTRA_CONTRACTS as CONTRACTS,
    iter_dc_extra_jobs as jobs,
    dc_extra_prerequisites as gaps,
)


class DcExtraContracts(unittest.TestCase):
    def test_all_official_columns_inputs_and_permission_uncertainty(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        self.assertEqual(set(CONTRACTS), {"dc_member", "dc_daily"})
        self.assertEqual(sum(map(len, FIELDS.values())), 17)
        for api, spec in CONTRACTS.items():
            entry = next(e for e in catalog["entries"] if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["extra_fields"], FIELDS[api])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertEqual(spec["minimum_points"], 6000)
            self.assertIsNone(spec["independent_permission"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertIsNone(spec["documented_daily_requests"])
            self.assertTrue(spec["row_cap_verified"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertEqual(spec["positive_fields"], [])
        self.assertEqual(CONTRACTS["dc_member"]["row_cap"], 5000)
        self.assertEqual(CONTRACTS["dc_daily"]["row_cap"], 2000)

    def test_source_identity_dates_units_and_no_fake_member_history(self):
        member, daily = CONTRACTS["dc_member"], CONTRACTS["dc_daily"]
        self.assertEqual(member["keys"], ["trade_date", "ts_code", "con_code"])
        self.assertEqual(daily["keys"], ["ts_code", "trade_date", "category"])
        self.assertEqual(daily["request_identity_fields"], ["idx_type"])
        self.assertEqual(daily["required_params"], ["idx_type"])
        self.assertIn("idx_type is optional", daily["category_gap"])
        self.assertNotIn("idx_type", FIELDS["dc_daily"])
        self.assertIn("category", FIELDS["dc_daily"])
        self.assertIn("vol is shares", daily["unit_note"])
        self.assertIn("amount is CNY", daily["unit_note"])
        self.assertEqual(set(DAILY_VARIANTS[0]), {"idx_type"})
        self.assertEqual(
            {v["idx_type"] for v in DAILY_VARIANTS},
            {"概念板块", "行业板块", "地域板块"},
        )
        for spec in CONTRACTS.values():
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertEqual(spec["split_axis"], "trade_date")
            self.assertEqual(spec["date_field"], "trade_date")
            self.assertEqual(
                spec["split"],
                {
                    "start_param": "start_date",
                    "end_param": "end_date",
                    "precision": "day",
                },
            )
            self.assertEqual(spec["saturation_fallback"], "dc_indices")
            self.assertEqual(spec["saturation_param"], "ts_code")
            self.assertEqual(spec["dependencies"], [])
            self.assertIn("opaque DC board", spec["namespace_note"])
        self.assertIn("con_code", INPUT_FIELDS["dc_member"])
        self.assertIn("single-axis runtime", member["saturation_gap"])
        self.assertIn("source_con_code", member["member_namespace_note"])
        self.assertFalse(
            {"is_new", "in_date", "out_date", "weight"}
            & set(INPUT_FIELDS["dc_member"] + FIELDS["dc_member"])
        )

    def test_recent_and_history_dates_are_contiguous_once_for_all_categories(self):
        today, start = date(2025, 1, 5), date(2024, 12, 20)
        planned = list(jobs({"history_start": "20241220"}, today))
        self.assertEqual(len(planned), 17 * 4)
        self.assertEqual(
            len(
                {
                    (j["api_name"], json.dumps(j["params"], sort_keys=True))
                    for j in planned
                }
            ),
            len(planned),
        )
        expected = {(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(17)}
        for api in CONTRACTS:
            actual = [j for j in planned if j["api_name"] == api]
            self.assertEqual({j["params"]["trade_date"] for j in actual}, expected)
            for day in expected:
                variants = [
                    j["params"].get("idx_type")
                    for j in actual
                    if j["params"]["trade_date"] == day
                ]
                self.assertEqual(
                    set(variants),
                    {v["idx_type"] for v in DAILY_VARIANTS}
                    if api == "dc_daily"
                    else {None},
                )
            for job in actual:
                self.assertEqual(job["fields"], ",".join(FIELDS[api]))
                self.assertTrue(set(job["params"]) <= set(INPUT_FIELDS[api]))
                self.assertNotIn("ts_code", job["params"])
                recent = job["params"]["trade_date"] >= "20241230"
                self.assertEqual(job["priority"], 20 if recent else 55)
                self.assertEqual(job["epoch"], "20250105" if recent else "history")

    def test_documented_floors_and_configured_scope_remain_unverified(self):
        planned = list(jobs({"history_start": "19000101"}, date(2025, 1, 1)))
        for api, floor in (("dc_member", "20241220"), ("dc_daily", "20200101")):
            self.assertEqual(
                min(j["params"]["trade_date"] for j in planned if j["api_name"] == api),
                floor,
            )
        config = {
            "dc_extra_history_start": {"dc_member": "20250101"},
            "history_start": "20241231",
        }
        planned = list(jobs(config, date(2025, 1, 2)))
        self.assertEqual(
            min(
                j["params"]["trade_date"]
                for j in planned
                if j["api_name"] == "dc_member"
            ),
            "20250101",
        )
        self.assertEqual(
            min(
                j["params"]["trade_date"]
                for j in planned
                if j["api_name"] == "dc_daily"
            ),
            "20241231",
        )
        recorded = gaps(config=config)
        scopes = {
            g["api_name"]: g
            for g in recorded
            if g["reason"] == "configured_scope_not_verified_complete"
        }
        self.assertEqual(scopes["dc_member"]["planned_start"], "20250101")
        self.assertEqual(scopes["dc_daily"]["documented_start_precision"], "year")
        self.assertEqual(scopes["dc_member"]["documented_start_precision"], "day")
        for api in CONTRACTS:
            reasons = {g["reason"] for g in recorded if g["api_name"] == api}
            self.assertTrue(
                {
                    "pit_gap",
                    "history_gap",
                    "refresh_gap",
                    "discovery_gap",
                    "pagination_gap",
                }
                <= reasons
            )
        self.assertIn(
            "saturation_gap",
            {g["reason"] for g in recorded if g["api_name"] == "dc_member"},
        )

    def test_leap_day_and_empty_selection(self):
        planned = list(
            jobs(
                {"dc_extra_apis": ["dc_daily"], "history_start": "20240227"},
                date(2024, 3, 2),
            )
        )
        self.assertEqual(len(planned), 5 * 3)
        self.assertEqual(
            sum(j["params"]["trade_date"] == "20240229" for j in planned), 3
        )
        self.assertEqual(list(jobs({"dc_extra_apis": []}, date(2026, 9, 9))), [])
        self.assertEqual(gaps(enabled_apis=[]), [])

    def test_lazy_fair_history_does_not_wait_for_current_catalog(self):
        today = date(2026, 9, 9)
        head = list(islice(jobs({"planning_epoch": "frozen"}, today, {}), 34))
        self.assertEqual(len(head), 34)
        self.assertTrue(all(j["epoch"] == "frozen" for j in head[:28]))
        self.assertEqual(
            [j["api_name"] for j in head[28:]], ["dc_member", "dc_daily"] * 3
        )
        self.assertEqual(head[28]["params"], {"trade_date": "20241220"})
        self.assertEqual(
            head[29]["params"], {"trade_date": "20200101", "idx_type": "概念板块"}
        )
        self.assertEqual(
            head,
            list(
                islice(
                    jobs(
                        {"planning_epoch": "frozen"},
                        today,
                        {"dc_indices": ["current_only.DC"]},
                    ),
                    34,
                )
            ),
        )

    def test_invalid_config_and_api_selection_fail_before_first_request(self):
        for config in (
            {"dc_extra_apis": "dc_daily"},
            {"dc_extra_apis": ["dc_index"]},
            {"dc_extra_history_start": 20250101},
            {"dc_extra_history_start": {"wrong": "20250101"}},
            {"history_start": "20250229"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                next(jobs(config, date(2026, 9, 9)))
        self.assertEqual(
            len(
                list(
                    jobs(
                        {
                            "dc_extra_apis": ["dc_member", "dc_member"],
                            "history_start": "20260909",
                        },
                        date(2026, 9, 9),
                    )
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
