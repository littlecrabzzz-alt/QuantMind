"""Offline risk-state contracts; no provider, database or production imports."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_risk_event_contracts import (  # noqa: E402
    FIELDS,
    INPUT_FIELDS,
    RISK_EVENT_CONTRACTS as CONTRACTS,
    iter_risk_event_jobs as jobs,
    risk_event_prerequisites as gaps,
)


class RiskEvents(unittest.TestCase):
    def test_complete_catalog_fields_inputs_caps_and_rights_unprobed(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        self.assertEqual(
            set(CONTRACTS),
            {"stock_st", "st", "stk_shock", "stk_high_shock", "stk_alert"},
        )
        self.assertEqual(sum(map(len, FIELDS.values())), 29)
        for api, spec in CONTRACTS.items():
            entry = next(e for e in catalog["entries"] if api in e["api_names"])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            for kind in ("requested_fields", "required_fields", "extra_fields"):
                self.assertEqual(spec[kind], FIELDS[api])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(spec["row_cap"], 1000)
            self.assertTrue(spec["row_cap_verified"])
            self.assertEqual(
                spec["minimum_points"], 3000 if api == "stock_st" else 6000
            )
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertIsNone(spec["documented_requests_per_minute"])
            self.assertIsNone(spec["documented_daily_requests"])
            self.assertFalse(spec["history_bound_verified"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertFalse({"offset", "limit"} & set(INPUT_FIELDS[api]))

    def test_request_axes_are_not_implementation_or_expiry_periods(self):
        self.assertIsNone(CONTRACTS["st"]["split"])
        self.assertEqual(CONTRACTS["st"]["date_field"], "pub_date")
        self.assertEqual(
            CONTRACTS["st"]["recent_request_axes"], ["pub_date", "imp_date"]
        )
        self.assertEqual(CONTRACTS["st"]["dependencies"], ["stocks"])
        self.assertEqual(CONTRACTS["stk_alert"]["date_field"], "start_date")
        self.assertEqual(CONTRACTS["stk_alert"]["split_axis"], "start_date")
        self.assertNotIn("trade_date", FIELDS["stk_alert"])
        for api in ("stk_shock", "stk_high_shock"):
            self.assertEqual(CONTRACTS[api]["date_field"], "trade_date")
            self.assertIn("announcement date", CONTRACTS[api]["date_axis_note"])
            self.assertIn("period", CONTRACTS[api]["keys"])
            self.assertIn(
                "YYYY-MM-DD", CONTRACTS[api]["documented_output_date_formats"]
            )
        today = date(2026, 9, 9)
        planned = list(jobs({"history_start": "20260903"}, today))
        self.assertEqual(len(planned), 42)
        for job in planned:
            api, params = job["api_name"], job["params"]
            self.assertEqual(
                set(params),
                {"pub_date"}
                if api == "st" and "pub_date" in params
                else {"imp_date"}
                if api == "st"
                else {"trade_date"},
            )
            self.assertNotIn("end_date", params)
            self.assertEqual(job["fields"], ",".join(FIELDS[api]))
            self.assertTrue(set(params) <= set(INPUT_FIELDS[api]))
        self.assertIn(
            "potentially after today", CONTRACTS["stk_alert"]["date_axis_note"]
        )

    def test_st_unknown_history_uses_all_observed_stock_identities_without_date_cutoff(
        self,
    ):
        ids = {
            "stocks": ["600001.SH", "T600001.SH", {"ts_code": "000001.SZ"}, "600001.SH"]
        }
        config = {"risk_event_apis": ["st"], "risk_event_history_start": "20260909"}
        planned = list(jobs(config, date(2026, 9, 9), ids))
        self.assertEqual(len(planned), 5)
        histories = [j for j in planned if j["epoch"] == "history"]
        self.assertEqual(
            [j["params"] for j in histories],
            [
                {"ts_code": "000001.SZ"},
                {"ts_code": "600001.SH"},
                {"ts_code": "T600001.SH"},
            ],
        )
        self.assertTrue(all("imp_date" not in j["params"] for j in histories))
        self.assertIn("unbounded", CONTRACTS["st"]["history_gap"])
        missing = gaps(enabled_apis=["st"])
        self.assertIn("awaiting_stored_stocks", {g["reason"] for g in missing})
        discovered = next(
            g for g in gaps(ids, enabled_apis=["st"]) if g["dependencies"]
        )
        self.assertEqual(discovered["observed_codes"], 3)
        self.assertFalse(discovered["universe_complete"])
        self.assertEqual(
            len(list(jobs({"risk_event_apis": ["st"]}, date(2026, 9, 9)))), 14
        )

    def test_unknown_starts_are_not_inferred_from_samples(self):
        enabled = ["stk_shock", "stk_high_shock", "stk_alert"]
        planned = list(jobs({"risk_event_apis": enabled}, date(2026, 9, 9)))
        self.assertEqual(len(planned), 21)
        self.assertTrue(all(j["epoch"] != "history" for j in planned))
        for api in enabled:
            self.assertIsNone(CONTRACTS[api]["history_start"])
            reasons = {g["reason"] for g in gaps(enabled_apis=[api])}
            self.assertTrue(
                {
                    "unknown_history_start_requires_scope_or_discovery",
                    "pit_gap",
                    "source_consistency_gap",
                }
                <= reasons
            )
        self.assertEqual(CONTRACTS["stock_st"]["history_start"], "20000101")
        self.assertEqual(CONTRACTS["stock_st"]["documented_update_time"], "09:20")
        self.assertFalse(CONTRACTS["stock_st"]["update_timezone_verified"])
        self.assertIn("cannot be completed", CONTRACTS["stock_st"]["history_note"])

    def test_date_coverage_is_once_across_leap_day_with_lazy_fair_history(self):
        config = {
            "risk_event_apis": ["stock_st", "stk_shock", "stk_high_shock", "stk_alert"],
            "history_start": "20240227",
            "planning_epoch": "anchor",
        }
        planned = list(jobs(config, date(2024, 3, 10)))
        days = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
            for i in range(13)
        }
        self.assertEqual(len(planned), 13 * 4)
        self.assertEqual(
            len(
                {
                    (j["api_name"], json.dumps(j["params"], sort_keys=True))
                    for j in planned
                }
            ),
            len(planned),
        )
        for api in config["risk_event_apis"]:
            self.assertEqual(
                {j["params"]["trade_date"] for j in planned if j["api_name"] == api},
                days,
            )
        head = list(
            islice(
                jobs(
                    {"history_start": "19000101"},
                    date(2026, 9, 9),
                    {"stocks": ["T600001.SH"]},
                ),
                47,
            )
        )
        self.assertEqual(len(head), 47)
        self.assertEqual([j["api_name"] for j in head[42:]], list(CONTRACTS))
        self.assertEqual(head[42]["params"], {"trade_date": "20000101"})
        self.assertEqual(head[43]["params"], {"ts_code": "T600001.SH"})
        self.assertEqual(head[44]["params"], {"trade_date": "19000101"})

    def test_alert_etf_future_end_and_saturation_uncertainty_are_explicit(self):
        spec = CONTRACTS["stk_alert"]
        self.assertEqual(spec["security_scope"], "stocks_and_etfs_at_least")
        self.assertTrue(
            {"stocks", "funds", "etfs", "risk_securities"}
            <= set(spec["saturation_dependencies"])
        )
        self.assertIn("513310.SH", spec["discovery_gap"])
        self.assertIn("after today", spec["future_gap"])
        for api, spec in CONTRACTS.items():
            self.assertEqual(spec["saturation_fallback"], "risk_securities")
            self.assertEqual(spec["saturation_param"], "ts_code")
            self.assertIn("terminal saturation", spec["pagination_gap"])
            if api != "st":
                self.assertEqual(
                    spec["split"],
                    {
                        "start_param": "start_date",
                        "end_param": "end_date",
                        "precision": "day",
                    },
                )
        self.assertIn("complete date inventory", CONTRACTS["st"]["saturation_gap"])

    def test_configured_start_mapping_scope_and_invalid_identifiers(self):
        config = {
            "risk_event_apis": ["stock_st", "stk_alert"],
            "risk_event_history_start": {"stock_st": "20260908"},
            "history_start": "20260909",
        }
        self.assertEqual(len(list(jobs(config, date(2026, 9, 9)))), 3)
        self.assertEqual(list(jobs({"risk_event_apis": []}, date(2026, 9, 9))), [])
        self.assertEqual(gaps(enabled_apis=[]), [])
        for config in (
            {"risk_event_apis": "st"},
            {"risk_event_apis": ["stock_basic"]},
            {"risk_event_history_start": 20000101},
            {"risk_event_history_start": {"bad": "20260909"}},
            {"history_start": "20260229"},
            {"history_start": "20270101"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                next(jobs(config, date(2026, 9, 9)))
        for ids in ({"stocks": ["SH600001"]}, {"stocks": ["600001.SH,000001.SZ"]}, []):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                next(jobs({"risk_event_apis": ["st"]}, date(2026, 9, 9), ids))
        # Unused stock metadata must not block independent daily date planners.
        self.assertEqual(
            len(
                list(
                    jobs(
                        {"risk_event_apis": ["stk_alert"]},
                        date(2026, 9, 9),
                        {"stocks": ["invalid"]},
                    )
                )
            ),
            7,
        )


if __name__ == "__main__":
    unittest.main()
