"""Pure official schema/identity and bounded lazy date/category planning checks."""

from datetime import date, datetime, timedelta
from itertools import islice
import json
import math
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_market_sentiment_contracts as module
from test_tushare_limit_extra_contracts import existing_pure_function

C = module.MARKET_SENTIMENT_CONTRACTS


class MarketSentiment(unittest.TestCase):
    def test_complete_seven_official_schemas_and_no_default_field_omission(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())[
            "entries"
        ]
        self.assertEqual(
            list(map(len, module.FIELDS.values())), [9, 4, 38, 24, 7, 11, 8]
        )
        self.assertEqual(sum(map(len, module.FIELDS.values())), 101)
        for api, spec in C.items():
            entry = next(e for e in entries if api in e["api_names"])
            if api == "tdx_daily":
                # Catalog extraction omitted digit-leading names; a future
                # audited catalog correction may add them without renaming.
                self.assertLessEqual(
                    set(module.FIELDS[api]) - set(entry["output_fields"]),
                    {"3day", "5day", "10day", "20day", "60day", "1year"},
                )
                self.assertEqual(
                    [f for f in module.FIELDS[api] if f in entry["output_fields"]],
                    entry["output_fields"],
                )
            else:
                self.assertEqual(module.FIELDS[api], entry["output_fields"])
            self.assertEqual(module.INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(spec["required_fields"], module.FIELDS[api])
            self.assertEqual(spec["requested_fields"], module.FIELDS[api])
            self.assertEqual(set(spec["field_gaps"]), set(module.FIELDS[api]))
            self.assertEqual(spec["hidden_fields"], [])
            self.assertTrue(
                all(
                    meta["default"] == "Y"
                    for meta in module.FIELD_METADATA[api].values()
                )
            )
            self.assertTrue(
                all(
                    meta["required"] == "N"
                    for meta in module.INPUT_METADATA[api].values()
                )
            )
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertTrue(spec["preserve_distinct_rows"])
            self.assertRegex(spec["source_html_sha256"], "^[a-f0-9]{64}$")

    def test_all_rank_markets_times_and_kp_tags_are_distinct_requests(self):
        jobs = list(
            module.iter_market_sentiment_jobs(
                {"history_start": "20260909", "planning_epoch": "frozen"},
                date(2026, 9, 9),
            )
        )
        self.assertEqual(len(jobs), 46)
        by_api = {api: [j for j in jobs if j["api_name"] == api] for api in C}
        self.assertEqual([len(by_api[api]) for api in C], [4, 1, 1, 5, 1, 18, 16])
        for api, group in by_api.items():
            seen = set()
            for job in group:
                params = job["params"]
                self.assertEqual(job["fields"].split(","), module.FIELDS[api])
                self.assertEqual(job["epoch"], "frozen")
                self.assertFalse(params.keys() - set(module.INPUT_FIELDS[api]))
                self.assertFalse(
                    {"offset", "limit", "rank_time", "rank", "start_date", "end_date"}
                    & params.keys()
                )
                identity = tuple(
                    (key, params[key]) for key in C[api]["request_identity_fields"]
                )
                self.assertNotIn(identity, seen)
                seen.add(identity)
            self.assertEqual(len(seen), len(module.VARIANTS[api]))
        self.assertEqual(
            {j["params"]["idx_type"] for j in by_api["tdx_index"]},
            set(module.TDX_TYPES),
        )
        self.assertIn("地区板块", module.TDX_TYPES)
        self.assertNotIn("地域板块", module.TDX_TYPES)
        self.assertEqual(
            {j["params"]["tag"] for j in by_api["kpl_list"]}, set(module.KPL_TAGS)
        )
        self.assertEqual(
            {j["params"]["market"] for j in by_api["ths_hot"]}, set(module.THS_MARKETS)
        )
        self.assertEqual({j["params"]["is_new"] for j in by_api["ths_hot"]}, {"Y", "N"})
        self.assertEqual(
            C["dc_hot"]["request_identity_fields"], ["market", "hot_type", "is_new"]
        )

    def test_unknown_floor_explicit_scope_leap_days_and_lazy_history(self):
        today = date(2024, 3, 5)
        recent = list(module.iter_market_sentiment_jobs({}, today))
        self.assertEqual(len(recent), 46 * 7)
        self.assertTrue(all(j["epoch"] != "history" for j in recent))
        for api in C:
            gaps = module.market_sentiment_prerequisites(enabled_apis=[api])
            self.assertIn(
                "unknown_history_start_requires_scope", {g["reason"] for g in gaps}
            )
        cfg = {"history_start": "20240227"}
        jobs = list(module.iter_market_sentiment_jobs(cfg, today))
        self.assertEqual(len(jobs), 46 * 8)
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d") for i in range(8)
        }
        seen = set()
        for api in C:
            group = [j for j in jobs if j["api_name"] == api]
            self.assertEqual({j["params"]["trade_date"] for j in group}, expected)
            for job in group:
                key = (api, json.dumps(job["params"], sort_keys=True))
                self.assertNotIn(key, seen)
                seen.add(key)
        self.assertEqual(
            {j["params"]["trade_date"] for j in jobs if j["epoch"] == "history"},
            {"20240227"},
        )
        counts = []
        original = module._days

        def traced(begin, end):
            for params in original(begin, end):
                counts.append(params)
                yield params

        with patch.object(module, "_days", side_effect=traced):
            iterator = module.iter_market_sentiment_jobs(
                {"history_start": "19900101"}, today
            )
            sample = list(islice(iterator, 46 * 7 + 1))
        self.assertEqual(sample[-1]["params"]["trade_date"], "19900101")
        self.assertLessEqual(len(counts), 50)

    def test_legal_split_axes_preserve_board_member_or_tag(self):
        split = existing_pure_function(
            "backend/shared/tushare_pipeline.py",
            "date_children",
            {
                "datetime": datetime,
                "timedelta": timedelta,
                "contract_for": C.__getitem__,
            },
            owner="Pipeline",
        )
        for api, filters in [
            ("tdx_member", {"ts_code": "880728.TDX", "con_code": "T600001.SH"}),
            ("tdx_daily", {"ts_code": "880728.TDX"}),
            ("kpl_list", {"ts_code": "T600001.SH", "tag": "自然涨停"}),
        ]:
            params = {"start_date": "20240228", "end_date": "20240301", **filters}
            children = split(None, {"api_name": api, "params": params})
            self.assertEqual(len(children), 2)
            self.assertEqual(children[0]["end_date"], "20240229")
            self.assertEqual(children[1]["start_date"], "20240301")
            self.assertTrue(
                all(all(c[k] == v for k, v in filters.items()) for c in children)
            )
        for api in ("tdx_index", "kpl_concept_cons", "ths_hot", "dc_hot"):
            self.assertIsNone(C[api]["split"])
            self.assertIsNone(
                split(
                    None,
                    {
                        "api_name": api,
                        "params": {"trade_date": "20260904", **module.VARIANTS[api][0]},
                    },
                )
            )
        for api in C:
            self.assertNotIn("pagination", C[api])
        for api in ("ths_hot", "dc_hot"):
            self.assertNotIn("saturation_fallback", C[api])
            self.assertIn("stock-only", C[api]["saturation_gap"])

    def test_actual_assessor_missing_field_and_cap_stay_gaps(self):
        assess = existing_pure_function(
            "backend/shared/tushare_intake.py",
            "assess_response",
            {"re": re, "math": math},
        )
        for api, spec in C.items():
            fields = module.FIELDS[api]
            values = [
                "source" if m["type"] == "str" else -1.25
                for m in module.FIELD_METADATA[api].values()
            ]
            payload = {"code": 0, "data": {"fields": fields, "items": [values]}}
            args = (spec["row_cap"], spec["required_fields"], spec["nullable_fields"])
            self.assertEqual(assess(payload, *args)["status"], "sample_ok")
            omitted = {
                "code": 0,
                "data": {"fields": fields[:-1], "items": [values[:-1]]},
            }
            self.assertEqual(assess(omitted, *args)["status"], "schema_gap")
            saturated = {
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [values] * spec["row_cap"],
                    "has_more": False,
                },
            }
            self.assertEqual(assess(saturated, *args)["status"], "possibly_truncated")
        self.assertIn("ts_name", C["kpl_concept_cons"]["schema_gap"])
        self.assertIn("con_name", module.FIELDS["kpl_concept_cons"])
        self.assertNotIn("ts_name", module.FIELDS["kpl_concept_cons"])

    def test_digit_leading_source_columns_units_and_discovery_are_not_rewritten(self):
        quote = existing_pure_function(
            "backend/shared/tushare_store.py", "_identifier", {}
        )
        for field in ("3day", "5day", "10day", "20day", "60day", "1year"):
            self.assertIn(field, module.FIELDS["tdx_daily"])
            self.assertEqual(
                quote(field, module.FIELDS["tdx_daily"]), '"' + field + '"'
            )
        for field in ("rise", "pe", "pb"):
            self.assertEqual(module.FIELD_METADATA["tdx_daily"][field]["type"], "str")
        self.assertIn("open interest", C["tdx_daily"]["unit_note"])
        self.assertIn("3000", C["kpl_concept_cons"]["discovery_gap"])
        self.assertEqual(C["tdx_member"]["saturation_fallback"], "tdx_indices")
        self.assertEqual(C["kpl_concept_cons"]["saturation_fallback"], "kpl_concepts")
        for api in ("ths_hot", "dc_hot"):
            self.assertIn("22:30", C[api]["intraday_gap"])
            self.assertIn("rank_time", C[api]["keys"])
            self.assertNotIn("rank_time", C[api]["nullable_fields"])
            self.assertIn("RRG", C[api]["pit_gap"])
        self.assertEqual(
            C["kpl_list"]["documented_quota_tiers"][1]["requests_per_minute"], 500
        )
        self.assertEqual(C["kpl_list"]["requests_per_minute"], 30)

    def test_configuration_validation_and_per_api_scope(self):
        today = date(2026, 9, 9)
        for cfg in (
            {"market_sentiment_apis": "tdx_daily"},
            {"market_sentiment_apis": ["daily"]},
            {"market_sentiment_history_start": 42},
            {"market_sentiment_history_start": {"daily": "20260101"}},
            {"history_start": "20260230"},
            {"history_start": "20270909"},
        ):
            with self.assertRaises(ValueError):
                list(module.iter_market_sentiment_jobs(cfg, today))
        self.assertEqual(
            list(
                module.iter_market_sentiment_jobs({"market_sentiment_apis": []}, today)
            ),
            [],
        )
        cfg = {
            "market_sentiment_apis": ["tdx_daily", "tdx_daily", "kpl_list"],
            "market_sentiment_history_start": {
                "tdx_daily": "20260908",
                "kpl_list": "20260909",
            },
        }
        plan = list(module.iter_market_sentiment_jobs(cfg, today))
        self.assertEqual(len(plan), 7)
        self.assertEqual({j["api_name"] for j in plan}, {"tdx_daily", "kpl_list"})
        self.assertEqual(
            {g["api_name"] for g in module.market_sentiment_prerequisites(config=cfg)},
            {"tdx_daily", "kpl_list"},
        )


if __name__ == "__main__":
    unittest.main()
