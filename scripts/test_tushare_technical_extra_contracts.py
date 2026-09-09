"""Offline schema and acquisition geometry checks; no provider/client imports."""

from datetime import date, datetime, timedelta
import math
import re
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_technical_extra_contracts import (
    FIELD_METADATA,
    FIELDS,
    INPUT_FIELDS,
    TECHNICAL_EXTRA_CONTRACTS as CONTRACTS,
    iter_technical_extra_jobs as jobs,
    technical_extra_prerequisites as prerequisites,
)


class TechnicalExtraContracts(unittest.TestCase):
    def test_full_reviewed_schema_and_not_aliases(self):
        expected = {
            "stk_factor": 35,
            "stk_factor_pro": 261,
            "cyq_perf": 11,
            "cyq_chips": 4,
            "bak_daily": 31,
        }
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_text()
        )
        for api, count in expected.items():
            spec = CONTRACTS[api]
            entry = next(e for e in catalog["entries"] if e["api_names"] == [api])
            self.assertEqual(FIELDS[api], entry["output_fields"])
            self.assertEqual(len(set(FIELDS[api])), count)
            self.assertEqual(spec["required_fields"], FIELDS[api])
            self.assertEqual(spec["requested_fields"], FIELDS[api])
            self.assertEqual(set(spec["field_gaps"]), set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
            self.assertIsNone(spec["independent_permission"])
            self.assertEqual(spec["hidden_fields"], [])
            self.assertEqual(INPUT_FIELDS[api], entry["input_fields"])
            self.assertEqual(
                {m["default"] for m in FIELD_METADATA[api].values()}, {"Y"}
            )
        self.assertEqual(sum(expected.values()), 342)
        self.assertEqual(
            CONTRACTS["cyq_chips"]["keys"], ["ts_code", "trade_date", "price"]
        )
        self.assertEqual(
            [CONTRACTS[a]["row_cap"] for a in expected],
            [10000, 10000, 6000, 6000, 7000],
        )

    def test_literal_adjustment_formula_and_unit_ambiguities(self):
        meta = FIELD_METADATA["stk_factor_pro"]
        for suffix, value in (("bfq", 20), ("hfq", 21), ("qfq", 22)):
            self.assertIn(f"M4={value}", meta[f"bbi_{suffix}"]["description"])
            self.assertIn(f"ema_{suffix}_250", meta)
        self.assertIn("close_qfq", meta["pre_close"]["description"])
        self.assertIn("pct_chg", meta)
        self.assertIn("pct_change", FIELDS["stk_factor"])
        self.assertIn("pro_bar", CONTRACTS["stk_factor"]["adjustment_note"])
        self.assertIn("not inherit", CONTRACTS["stk_factor_pro"]["adjustment_note"])
        self.assertIn("hundred-million", CONTRACTS["bak_daily"]["unit_note"])
        self.assertIn("scale", CONTRACTS["cyq_perf"]["unit_note"])
        self.assertIn("decay", CONTRACTS["cyq_chips"]["formula_gap"])

    def test_every_request_legal_and_full_fields(self):
        cfg = {"history_start": "20260220", "planning_epoch": "frozen"}
        result = list(
            jobs(cfg, date(2026, 3, 12), {"stocks": ["600000.SH", "T600000.SH"]})
        )
        seen = set()
        for job in result:
            api, params = job["api_name"], job["params"]
            self.assertFalse(params.keys() - set(INPUT_FIELDS[api]))
            if api.startswith("cyq_"):
                self.assertIn(params["ts_code"], ("600000.SH", "T600000.SH"))
            if api == "stk_factor_pro":
                self.assertTrue("ts_code" in params or "trade_date" in params)
            self.assertEqual(job["fields"].split(","), FIELDS[api])
            self.assertNotIn("offset", params)
            self.assertNotIn("limit", params)
            identity = (api, json.dumps(params, sort_keys=True))
            self.assertNotIn(identity, seen)
            seen.add(identity)
            self.assertEqual(
                job["epoch"], "history" if job["priority"] == 55 else "frozen"
            )
        for api in CONTRACTS:
            self.assertTrue(
                any(j["api_name"] == api and j["epoch"] == "history" for j in result)
            )

    def test_leap_month_first_last_and_no_gaps_per_security(self):
        codes = ["600000.SH", "T600000.SH", "830001.BJ"]
        begin, end = date(2024, 1, 30), date(2024, 3, 10)
        result = list(jobs({"history_start": "20240130"}, end, {"stocks": codes}))
        expected = set()
        day = begin
        while day <= end:
            expected.add(day.isoformat())
            day += timedelta(days=1)
        for api in CONTRACTS:
            for code in codes if api.startswith("cyq_") else (None,):
                counts = {}
                for job in result:
                    if job["api_name"] != api or job["params"].get("ts_code") != code:
                        continue
                    params = job["params"]
                    first = datetime.strptime(
                        params.get("start_date", params.get("trade_date")), "%Y%m%d"
                    ).date()
                    last = datetime.strptime(
                        params.get("end_date", params.get("trade_date")), "%Y%m%d"
                    ).date()
                    if "start_date" in params:
                        self.assertEqual(
                            (first.year, first.month), (last.year, last.month)
                        )
                    while first <= last:
                        counts[first.isoformat()] = counts.get(first.isoformat(), 0) + 1
                        first += timedelta(days=1)
                self.assertEqual(set(counts), expected)
                self.assertEqual(set(counts.values()), {1})
        self.assertTrue(any(j["params"].get("end_date") == "20240229" for j in result))

    def test_unknown_start_and_required_stock_discovery_remain_gaps(self):
        result = list(jobs({}, date(2026, 9, 9)))
        self.assertEqual(len(result), 21)  # Three optional-symbol APIs, seven days.
        self.assertFalse(any(j["api_name"].startswith("cyq_") for j in result))
        gaps = prerequisites()
        self.assertEqual(
            {
                g["api_name"]
                for g in gaps
                if g["reason"] == "unknown_history_start_requires_scope"
            },
            {"stk_factor", "stk_factor_pro", "bak_daily"},
        )
        self.assertEqual(
            {g["api_name"] for g in gaps if g["reason"] == "awaiting_stored_stocks"},
            {"cyq_perf", "cyq_chips"},
        )
        discovered = prerequisites({"stocks": ["600000.SH"]})
        self.assertTrue(
            all(
                not g["universe_complete"]
                for g in discovered
                if "universe_complete" in g
            )
        )
        self.assertIsNone(CONTRACTS["bak_daily"]["history_start"])
        self.assertEqual(CONTRACTS["cyq_chips"]["history_start_precision"], "year")

    def test_lazy_fair_stream_and_historical_t_discovery(self):
        cfg = {"technical_extra_history_start": "19000101"}
        identifiers = {"stocks": ["T600000.SH", {"ts_code": "600000.SH"}, "600000.SH"]}
        first = list(islice(jobs(cfg, date(2026, 9, 9), identifiers), 5))
        self.assertEqual([j["api_name"] for j in first], list(CONTRACTS))
        self.assertEqual(
            [j["params"]["ts_code"] for j in first if j["api_name"].startswith("cyq_")],
            ["600000.SH"] * 2,
        )
        # Huge date scope remains lazy; chip year floor remains 2018.
        result = jobs(cfg, date(2026, 9, 9), identifiers)
        while (job := next(result))["priority"] != 55:
            pass
        first_history = [job] + list(islice(result, 4))
        self.assertEqual([j["api_name"] for j in first_history], list(CONTRACTS))
        self.assertEqual(first_history[2]["params"]["start_date"], "20180101")

    def test_existing_cap_assessment_and_bisection_keep_stock_and_price_levels(self):
        from test_tushare_limit_extra_contracts import existing_pure_function

        assess = existing_pure_function(
            "backend/shared/tushare_intake.py",
            "assess_response",
            {"math": math, "re": re},
        )
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
        for api, spec in CONTRACTS.items():
            row = [
                "T600000.SH"
                if f == "ts_code"
                else "20240229"
                if f == "trade_date"
                else 12.34
                if f == "price"
                else None
                for f in FIELDS[api]
            ]
            payload = {
                "code": 0,
                "data": {"fields": FIELDS[api], "items": [row] * spec["row_cap"]},
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
        for api in ("cyq_perf", "cyq_chips"):
            pending = [
                {
                    "start_date": "20240201",
                    "end_date": "20240229",
                    "ts_code": "T600000.SH",
                }
            ]
            leaves = []
            while pending:
                params = pending.pop()
                children = split(None, {"api_name": api, "params": params})
                if children is None:
                    self.assertEqual(params["start_date"], params["end_date"])
                    leaves.append(params)
                else:
                    self.assertTrue(
                        all(
                            p["ts_code"] == "T600000.SH"
                            and set(p) == {"ts_code", "start_date", "end_date"}
                            for p in children
                        )
                    )
                    pending.extend(children)
            self.assertEqual(
                sorted(p["start_date"] for p in leaves),
                [f"202402{d:02}" for d in range(1, 30)],
            )
        self.assertNotIn("pagination", CONTRACTS["bak_daily"])
        self.assertEqual(
            CONTRACTS["bak_daily"]["documented_pagination"]["input_type"], "str"
        )

    def test_configuration_validation_and_disabled_family_isolation(self):
        for cfg in (
            {"technical_extra_apis": ["pro_bar"]},
            {"technical_extra_apis": "stk_factor"},
            {"technical_extra_history_start": {"bad": "20200101"}},
            {"technical_extra_history_start": 2018},
            {"history_start": "20260230"},
            {"history_start": "20270101"},
        ):
            with self.assertRaises(ValueError):
                list(jobs(cfg, date(2026, 9, 9)))
        with self.assertRaises(ValueError):
            list(jobs({}, date(2026, 9, 9), {"stocks": ["SH600000"]}))
        self.assertEqual(
            list(
                jobs(
                    {"technical_extra_apis": []}, date(2026, 9, 9), {"stocks": ["bad"]}
                )
            ),
            [],
        )
        self.assertEqual(
            len(
                list(
                    jobs(
                        {"technical_extra_apis": ["bak_daily"]},
                        date(2026, 9, 9),
                        {"stocks": ["bad"]},
                    )
                )
            ),
            7,
        )
        self.assertEqual(
            len(
                list(
                    jobs(
                        {
                            "technical_extra_apis": ["bak_daily", "bak_daily"],
                            "technical_extra_history_start": {"bak_daily": "20260909"},
                        },
                        date(2026, 9, 9),
                    )
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
