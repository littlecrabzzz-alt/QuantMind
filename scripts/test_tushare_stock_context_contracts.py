"""Offline stock-context schema, source-date and unresolved-scope checks."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
import math
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_stock_context_contracts import (
    FIELDS,
    INPUT_FIELDS,
    FIELD_METADATA,
    STOCK_CONTEXT_CONTRACTS as CONTRACTS,
    iter_stock_context_jobs as jobs,
    stock_context_prerequisites as gaps,
)
from test_tushare_limit_extra_contracts import existing_pure_function


class StockContext(unittest.TestCase):
    def test_complete_catalog_schemas_and_hidden_resume(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        counts = [7, 12, 7, 9, 9, 13, 11]
        self.assertEqual(list(map(len, FIELDS.values())), counts)
        self.assertEqual(sum(counts), 68)
        for api, spec in CONTRACTS.items():
            entry = next(e for e in entries if e["api_names"] == [api])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(set(spec["field_gaps"]), set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertTrue(spec["preserve_distinct_rows"])
        self.assertEqual(CONTRACTS["stk_managers"]["hidden_fields"], ["resume"])
        self.assertEqual(FIELD_METADATA["stk_managers"]["resume"]["default"], "N")
        self.assertIn("resume", CONTRACTS["stk_managers"]["nullable_fields"])
        for job in islice(jobs({}, date(2026, 9, 9)), 42):
            self.assertEqual(job["fields"].split(","), FIELDS[job["api_name"]])

    def test_legitimate_date_axes_nineturn_timestamp_and_rewards_unbounded(self):
        today = date(2026, 9, 9)
        config = {"history_start": "20260830", "planning_epoch": "fixed"}
        codes = {"stocks": ["T600000.SH", "600000.SH", "830001.BJ"]}
        plan = list(jobs(config, today, codes))
        seen = set()
        for job in plan:
            api, params = job["api_name"], job["params"]
            self.assertFalse(params.keys() - set(INPUT_FIELDS[api]))
            self.assertFalse({"offset", "limit"} & params.keys())
            if api == "stk_rewards":
                self.assertEqual(set(params), {"ts_code"})
            elif api == "stk_managers":
                self.assertEqual(set(params), {"ann_date"})
            elif api == "stk_nineturn":
                self.assertEqual(params["freq"], "daily")
                self.assertEqual(
                    datetime.strptime(params["trade_date"], "%Y-%m-%d %H:%M:%S").hour, 0
                )
                self.assertTrue(params["trade_date"].endswith(" 00:00:00"))
            else:
                self.assertEqual(set(params), {"trade_date"})
            identity = (api, json.dumps(params, sort_keys=True))
            self.assertNotIn(identity, seen)
            seen.add(identity)
            self.assertEqual(job["fields"].split(","), FIELDS[api])
        rewards = [j for j in plan if j["api_name"] == "stk_rewards"]
        self.assertEqual(
            {j["params"]["ts_code"] for j in rewards}, set(codes["stocks"])
        )
        self.assertTrue(all(j["epoch"] == "fixed" for j in rewards))
        self.assertEqual(CONTRACTS["stk_rewards"]["date_field"], "ann_date")
        self.assertIsNone(CONTRACTS["stk_rewards"]["split"])
        self.assertIn("REPORT PERIOD", CONTRACTS["stk_rewards"]["date_axis_note"])
        self.assertIn("ANNOUNCEMENT", CONTRACTS["stk_managers"]["date_axis_note"])

    def test_leap_days_continuous_distinct_dates_without_fabricated_history(self):
        apis = [
            "stk_premarket",
            "stk_managers",
            "stk_auction_o",
            "stk_auction_c",
            "stk_nineturn",
        ]
        plan = list(
            jobs(
                {"stock_context_apis": apis, "history_start": "20240227"},
                date(2024, 3, 5),
            )
        )
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).isoformat() for i in range(8)
        }
        for api in apis:
            ds = []
            for j in plan:
                if j["api_name"] != api:
                    continue
                value = j["params"].get("ann_date", j["params"].get("trade_date"))
                ds.append(
                    datetime.strptime(
                        value,
                        "%Y-%m-%d %H:%M:%S" if api == "stk_nineturn" else "%Y%m%d",
                    )
                    .date()
                    .isoformat()
                )
            self.assertEqual(set(ds), expected)
            self.assertEqual(len(ds), len(expected))
        unknown = {
            g["api_name"]
            for g in gaps()
            if g["reason"] == "unknown_history_start_requires_scope"
        }
        self.assertEqual(
            unknown, {"stk_premarket", "stk_managers", "stk_auction_o", "stk_auction_c"}
        )
        first = list(islice(jobs({"history_start": "19900101"}, date(2026, 9, 9)), 48))
        history = [j for j in first if j["epoch"] == "history"]
        self.assertEqual(history[0]["params"], {"trade_date": "19900101"})
        self.assertEqual(
            next(j for j in history if j["api_name"] == "stk_nineturn")["params"][
                "trade_date"
            ],
            "2023-01-01 00:00:00",
        )
        self.assertEqual(
            next(j for j in history if j["api_name"] == "stk_ah_comparison")["params"][
                "trade_date"
            ],
            "20250812",
        )

    def test_dependencies_isolated_and_no_guessed_minute_scope(self):
        plan = list(islice(jobs({}, date(2026, 9, 9)), 42))
        self.assertEqual(len(plan), 42)
        self.assertFalse(any(j["api_name"] == "stk_rewards" for j in plan))
        pending = [g for g in gaps() if g.get("dependencies")]
        self.assertEqual([g["api_name"] for g in pending], ["stk_rewards"])
        self.assertFalse(pending[0]["universe_complete"])
        self.assertEqual(
            CONTRACTS["stk_nineturn"]["supported_planned_freqs"], ["daily"]
        )
        self.assertTrue(any(g["reason"] == "frequency_gap" for g in gaps()))
        self.assertTrue(any(g["reason"] == "intraday_gap" for g in gaps()))
        invalid_ids = {"stocks": ["SH600000"]}
        self.assertTrue(
            any(
                g["reason"] == "malformed_stock_supplier_identifiers"
                for g in gaps(invalid_ids)
            )
        )
        self.assertFalse(
            any(
                j["api_name"] == "stk_rewards"
                for j in jobs({}, date(2026, 9, 9), invalid_ids)
            )
        )
        self.assertEqual(
            len(
                list(
                    jobs(
                        {
                            "stock_context_apis": ["stk_managers"],
                            "history_start": "20260909",
                        },
                        date(2026, 9, 9),
                        {"stocks": ["bad"]},
                    )
                )
            ),
            1,
        )
        self.assertEqual(
            list(
                jobs({"stock_context_apis": []}, date(2026, 9, 9), {"stocks": ["bad"]})
            ),
            [],
        )

    def test_endpoint_specific_permissions_caps_pairs_and_units(self):
        for api in ("stk_premarket", "stk_auction_o", "stk_auction_c"):
            self.assertTrue(CONTRACTS[api]["independent_permission"])
            self.assertIsNone(CONTRACTS[api]["minimum_points"])
        self.assertEqual(
            CONTRACTS["stk_premarket"]["documented_requests_per_minute"], 500
        )
        self.assertIsNone(CONTRACTS["stk_auction_o"]["documented_requests_per_minute"])
        for api in ("stk_managers", "stk_rewards"):
            self.assertFalse(CONTRACTS[api]["row_cap_verified"])
            self.assertIn("local saturation guard", CONTRACTS[api]["cap_note"])
        self.assertEqual(
            CONTRACTS["stk_ah_comparison"]["keys"], ["ts_code", "hk_code", "trade_date"]
        )
        self.assertIn("FX conversion", CONTRACTS["stk_ah_comparison"]["unit_note"])
        self.assertIn("birthday", CONTRACTS["stk_managers"]["date_axis_note"])
        self.assertIn("yuan", CONTRACTS["stk_rewards"]["unit_note"])
        self.assertIn("after close", CONTRACTS["stk_auction_c"]["date_axis_note"])

    def test_existing_assessment_requires_resume_and_caps_remain_unresolved(self):
        assess = existing_pure_function(
            "backend/shared/tushare_intake.py",
            "assess_response",
            {"math": math, "re": re},
        )
        for api, spec in CONTRACTS.items():
            values = [
                "600000.SH"
                if f == "ts_code"
                else "daily"
                if f == "freq"
                else "00001.HK"
                if f == "hk_code"
                else "20260904"
                if f == spec["date_field"]
                else None
                for f in FIELDS[api]
            ]
            payload = {
                "code": 0,
                "data": {"fields": FIELDS[api], "items": [values] * spec["row_cap"]},
            }
            self.assertEqual(
                assess(
                    payload,
                    spec["row_cap"],
                    spec["required_fields"],
                    spec["nullable_fields"],
                )["status"],
                "possibly_truncated",
            )
        spec = CONTRACTS["stk_managers"]
        fields = [f for f in FIELDS["stk_managers"] if f != "resume"]
        payload = {
            "code": 0,
            "data": {
                "fields": fields,
                "items": [
                    [
                        "600000.SH"
                        if f == "ts_code"
                        else "20260904"
                        if f == "ann_date"
                        else None
                        for f in fields
                    ]
                ],
            },
        }
        self.assertEqual(
            assess(
                payload,
                spec["row_cap"],
                spec["required_fields"],
                spec["nullable_fields"],
            )["status"],
            "schema_gap",
        )

    def test_existing_splits_keep_request_date_axis_frequency_and_pair_filters(self):
        split = existing_pure_function(
            "backend/shared/tushare_pipeline.py",
            "date_children",
            {
                "datetime": datetime,
                "timedelta": timedelta,
                "contract_for": CONTRACTS.__getitem__,
            },
            owner="Pipeline",
        )
        children = split(
            None,
            {
                "api_name": "stk_managers",
                "params": {
                    "ts_code": "T600000.SH",
                    "start_date": "20240228",
                    "end_date": "20240229",
                },
            },
        )
        self.assertEqual(
            children,
            [
                {
                    "ts_code": "T600000.SH",
                    "start_date": "20240228",
                    "end_date": "20240228",
                },
                {
                    "ts_code": "T600000.SH",
                    "start_date": "20240229",
                    "end_date": "20240229",
                },
            ],
        )
        children = split(
            None,
            {
                "api_name": "stk_nineturn",
                "params": {
                    "ts_code": "T600000.SH",
                    "freq": "daily",
                    "start_date": "2026-09-04 00:00:00",
                    "end_date": "2026-09-04 00:00:01",
                },
            },
        )
        self.assertEqual(len(children), 2)
        self.assertTrue(
            all(c["freq"] == "daily" and c["ts_code"] == "T600000.SH" for c in children)
        )
        children = split(
            None,
            {
                "api_name": "stk_ah_comparison",
                "params": {
                    "hk_code": "00001.HK",
                    "ts_code": "600000.SH",
                    "start_date": "20260903",
                    "end_date": "20260904",
                },
            },
        )
        self.assertTrue(
            all(
                c["hk_code"] == "00001.HK" and c["ts_code"] == "600000.SH"
                for c in children
            )
        )
        self.assertIsNone(
            split(
                None,
                {
                    "api_name": "stk_rewards",
                    "params": {"ts_code": "T600000.SH", "end_date": "20260630"},
                },
            )
        )

    def test_configuration_validation(self):
        for cfg in (
            {"stock_context_apis": "stk_managers"},
            {"stock_context_apis": ["unknown"]},
            {"stock_context_history_start": {"unknown": "19900101"}},
            {"stock_context_history_start": 1990},
            {"history_start": "20260230"},
            {"history_start": "20270101"},
        ):
            with self.assertRaises(ValueError):
                list(jobs(cfg, date(2026, 9, 9)))
        with self.assertRaises(ValueError):
            list(jobs({}, "20260909"))
        self.assertEqual(
            len(
                list(
                    jobs(
                        {
                            "stock_context_apis": ["stk_managers", "stk_managers"],
                            "stock_context_history_start": {"stk_managers": "20260909"},
                        },
                        date(2026, 9, 9),
                    )
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
