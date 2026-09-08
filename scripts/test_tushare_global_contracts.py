#!/usr/bin/env python3
"""Offline global contracts/planning verification; no API calls or data writes."""

from datetime import date, timedelta
from itertools import islice
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_global_contracts import (  # noqa: E402
    GLOBAL_CONTRACTS,
    FIELDS,
    global_prerequisites,
    iter_global_jobs,
)


class GlobalContracts(unittest.TestCase):
    def test_catalog_and_all_hidden_fields(self):
        entries = json.loads((ROOT / "config/tushare-catalog.json").read_text())[
            "entries"
        ]
        self.assertEqual(len(GLOBAL_CONTRACTS), 17)
        for api, spec in GLOBAL_CONTRACTS.items():
            entry = next(e for e in entries if api in e["api_names"])
            self.assertEqual(set(FIELDS[api]), set(entry["output_fields"]))
            self.assertEqual(set(spec["extra_fields"]), set(FIELDS[api]))
            self.assertTrue(set(spec["keys"]) <= set(FIELDS[api]))
            self.assertEqual(spec["permission_status"], "unprobed")
        self.assertIn("enname", FIELDS["us_basic"])
        self.assertTrue(
            {"change", "turnover_ratio", "total_mv", "pe", "pb"}
            <= set(FIELDS["us_daily"])
        )

    def test_all_scopes_and_vendor_spelling(self):
        jobs = list(
            iter_global_jobs(
                {"global_apis": ["hk_basic", "us_basic"]}, date(2026, 9, 9)
            )
        )
        hk = [j["params"] for j in jobs if j["api_name"] == "hk_basic"]
        us = [j["params"] for j in jobs if j["api_name"] == "us_basic"]
        self.assertEqual({p["list_status"] for p in hk}, {"L", "D", "P"})
        self.assertEqual({p.get("list_stauts") for p in us}, {None, "L", "D", "P"})
        self.assertTrue(all("classify" not in p and "offset" not in p for p in us))
        self.assertTrue(all(p["limit"] == 6000 for p in us))

    def test_full_leap_range_recent_first_and_interleaved(self):
        config = {
            "global_apis": ["us_daily", "hk_tradecal"],
            "global_history_start": "20240227",
            "planning_epoch": "20240312T03",
        }
        today = date(2024, 3, 12)
        with patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            jobs = list(iter_global_jobs(config, today))
        first_history = next(i for i, j in enumerate(jobs) if j["epoch"] == "history")
        self.assertTrue(all(j["priority"] == 20 for j in jobs[:first_history]))
        self.assertTrue(all(j["epoch"] == "20240312T03" for j in jobs[:first_history]))
        self.assertTrue(all(j["priority"] == 40 for j in jobs[first_history:]))
        self.assertEqual(
            [j["api_name"] for j in jobs[first_history : first_history + 2]],
            config["global_apis"],
        )
        expected = {
            (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
            for i in range(15)
        }
        for api in config["global_apis"]:
            rows = [j["params"] for j in jobs if j["api_name"] == api]
            actual = [p.get("trade_date", p.get("start_date")) for p in rows]
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(expected))
        calendars = [j["params"] for j in jobs if j["api_name"] == "hk_tradecal"]
        self.assertTrue(
            all(
                p["start_date"] == p["end_date"] and "is_open" not in p
                for p in calendars
            )
        )
        self.assertEqual(jobs, list(iter_global_jobs(config, today)))

    def test_current_incomplete_week_month_and_weekend(self):
        config = {"global_apis": ["stk_weekly_monthly", "stk_week_month_adj"]}
        jobs = list(iter_global_jobs(config, date(2026, 9, 9)))
        for api in config["global_apis"]:
            params = [j["params"] for j in jobs if j["api_name"] == api]
            self.assertIn({"trade_date": "20260911", "freq": "week"}, params)
            self.assertIn({"trade_date": "20260930", "freq": "month"}, params)
            self.assertEqual(
                len(params), len({json.dumps(p, sort_keys=True) for p in params})
            )
            self.assertTrue({"freq", "end_date"} <= set(GLOBAL_CONTRACTS[api]["keys"]))
        weekend = list(iter_global_jobs(config, date(2026, 9, 12)))
        self.assertFalse(
            any(
                j["params"] == {"trade_date": "20260918", "freq": "week"}
                for j in weekend
            )
        )

    def test_known_history_default_is_complete_and_lazy(self):
        jobs = iter_global_jobs({"global_apis": ["index_dailybasic"]}, date(2026, 9, 9))
        first = list(islice(jobs, 8))
        self.assertEqual(first[-1]["params"], {"trade_date": "20040101"})
        self.assertEqual(first[-1]["epoch"], "history")
        remainder = list(jobs)
        self.assertEqual(remainder[-1]["params"], {"trade_date": "20260902"})
        self.assertEqual(
            len(first) + len(remainder), (date(2026, 9, 9) - date(2004, 1, 1)).days + 1
        )

    def test_unknown_lower_bound_gap_and_per_api_scope(self):
        config = {
            "global_apis": ["hk_daily", "us_daily"],
            "global_history_start": {"hk_daily": "20260830"},
        }
        gaps = global_prerequisites(config=config)
        self.assertIn(
            {
                "api_name": "us_daily",
                "dependencies": [],
                "reason": "unknown_history_start_requires_explicit_scope_or_evidence",
            },
            gaps,
        )
        jobs = list(iter_global_jobs(config, date(2026, 9, 9)))
        self.assertEqual(
            {j["api_name"] for j in jobs if j["epoch"] == "history"}, {"hk_daily"}
        )
        self.assertIsNone(GLOBAL_CONTRACTS["hk_daily"]["history_start"])
        self.assertFalse(GLOBAL_CONTRACTS["hk_daily"]["history_bound_verified"])
        self.assertEqual(
            len(
                list(iter_global_jobs({"global_apis": ["us_daily"]}, date(2026, 9, 9)))
            ),
            7,
        )

    def test_saturation_families_include_retired_and_punctuation(self):
        ids = {
            "us_stocks": [{"ts_code": "BRK.B", "list_stauts": "D"}, "AAPL", "BF-A"],
            "hk_stocks": [{"ts_code": "00001.HK", "list_status": "D"}],
            "indexes": ["000001.SH"],
            "stocks": ["920061.BJ"],
        }
        gaps = global_prerequisites(
            ids,
            ["us_adjfactor", "hk_daily", "index_weekly", "monthly"],
            {"global_history_start": "20260901"},
        )
        self.assertEqual(gaps, [])
        self.assertEqual(
            GLOBAL_CONTRACTS["us_adjfactor"]["saturation_fallback"], "us_stocks"
        )
        self.assertEqual(
            GLOBAL_CONTRACTS["index_weekly"]["saturation_fallback"], "indexes"
        )
        self.assertIn("exchange", GLOBAL_CONTRACTS["us_adjfactor"]["keys"])
        self.assertIn("exchange", GLOBAL_CONTRACTS["us_daily_adj"]["keys"])
        all_us = list(
            iter_global_jobs({"global_apis": ["us_daily_adj"]}, date(2026, 9, 9), ids)
        )
        self.assertTrue(
            all(
                "exchange" not in j["params"] and j["params"]["limit"] == 8000
                for j in all_us
            )
        )

    def test_permissions_caps_and_adjustment_revisions(self):
        self.assertEqual(GLOBAL_CONTRACTS["monthly"]["row_cap"], 5629)
        self.assertEqual(GLOBAL_CONTRACTS["monthly"]["documented_row_cap"], 4500)
        self.assertFalse(GLOBAL_CONTRACTS["monthly"]["row_cap_verified"])
        self.assertEqual(GLOBAL_CONTRACTS["us_adjfactor"]["row_cap"], 15000)
        self.assertFalse(GLOBAL_CONTRACTS["hk_basic"]["row_cap_verified"])
        for api in (
            "hk_daily",
            "hk_daily_adj",
            "hk_adjfactor",
            "us_daily",
            "us_daily_adj",
            "us_adjfactor",
        ):
            self.assertTrue(GLOBAL_CONTRACTS[api]["independent_permission"])
        for api in (
            "hk_daily_adj",
            "us_daily_adj",
            "hk_adjfactor",
            "us_adjfactor",
            "stk_week_month_adj",
        ):
            self.assertIn("revision_note", GLOBAL_CONTRACTS[api])
        self.assertIn(
            "close_price", GLOBAL_CONTRACTS["us_adjfactor"]["nullable_fields"]
        )

    def test_symbol_period_ranges_cover_every_day_and_retired_universe(self):
        config = {
            "global_apis": ["weekly", "monthly", "index_weekly", "index_monthly"],
            "global_history_start": "20240227",
        }
        ids = {
            "stocks": [{"ts_code": "600000.SH", "list_status": "D"}, "920061.BJ"],
            "indexes": ["000001.SH", "000300.CSI", "HSI.HI"],
        }
        today = date(2026, 1, 10)
        jobs = list(iter_global_jobs(config, today, ids))
        first_history = next(
            i for i, job in enumerate(jobs) if job["epoch"] == "history"
        )
        self.assertTrue(all(j["epoch"] == "history" for j in jobs[first_history:]))
        for api in config["global_apis"]:
            closed = date(2026, 1, 4) if api.endswith("weekly") else date(2025, 12, 31)
            expected = {
                (date(2024, 2, 27) + timedelta(days=i)).strftime("%Y%m%d")
                for i in range((closed - date(2024, 2, 27)).days + 1)
            }
            codes = (
                ["000001.SH", "000300.CSI", "HSI.HI"]
                if api.startswith("index_")
                else ["600000.SH", "920061.BJ"]
            )
            for code in codes:
                selected = [
                    j
                    for j in jobs
                    if j["api_name"] == api and j["params"]["ts_code"] == code
                ]
                covered = []
                for job in selected:
                    params = job["params"]
                    self.assertEqual(set(params), {"ts_code", "start_date", "end_date"})
                    start = date(
                        int(params["start_date"][:4]),
                        int(params["start_date"][4:6]),
                        int(params["start_date"][6:]),
                    )
                    end = date(
                        int(params["end_date"][:4]),
                        int(params["end_date"][4:6]),
                        int(params["end_date"][6:]),
                    )
                    covered.extend(
                        (start + timedelta(days=i)).strftime("%Y%m%d")
                        for i in range((end - start).days + 1)
                    )
                    if job["epoch"] == "history" and api.startswith("index_"):
                        self.assertEqual(start.year, end.year)
                self.assertEqual(set(covered), expected)
                # Recent two-period review can overlap a completed annual partition.
                self.assertEqual(len(selected), 3)
        self.assertEqual(jobs, list(iter_global_jobs(config, today, ids)))
        # 2024 spring holiday's pre-Friday closing day stays inside a full range.
        self.assertIn("20240403", expected)
        self.assertIn("20240229", expected)

    def test_periods_wait_for_discovery_without_cross_section_explosion(self):
        config = {
            "global_apis": ["weekly", "monthly", "index_weekly", "index_monthly"],
            "global_history_start": "19900101",
        }
        self.assertEqual(list(iter_global_jobs(config, date(2026, 9, 9))), [])
        gaps = global_prerequisites(config=config)
        self.assertEqual(len(gaps), 4)
        self.assertTrue(
            all(
                g["reason"] == "awaiting_stored_discovery_for_symbol_ranges"
                for g in gaps
            )
        )
        ids = {"indexes": [f"{n:06d}.CSI" for n in range(1000)]}
        index_config = {
            "global_apis": ["index_weekly", "index_monthly"],
            "global_history_start": "20250101",
        }
        jobs = list(iter_global_jobs(index_config, date(2026, 1, 10), ids))
        self.assertEqual(
            len(jobs), 4000
        )  # 2 APIs * 1000 codes * (recent + completed 2025 year)
        self.assertFalse(any("trade_date" in j["params"] for j in jobs))

    def test_period_epoch_is_stable_across_daily_planning_and_new_identifiers(self):
        config = {
            "global_apis": ["weekly", "monthly", "index_weekly", "index_monthly"],
            "global_history_start": "20200101",
            "planning_epoch": "20260909",
        }
        ids = {"stocks": ["600000.SH"], "indexes": ["000300.CSI"]}
        first = list(iter_global_jobs(config, date(2026, 9, 9), ids))
        second = list(
            iter_global_jobs(
                {**config, "planning_epoch": "20260910"}, date(2026, 9, 10), ids
            )
        )
        self.assertEqual(first, second)
        recent = [job for job in first if job["epoch"] != "history"]
        self.assertEqual(len(recent), 4)
        for job in recent:
            self.assertEqual(
                job["epoch"],
                "period-20260906"
                if job["api_name"].endswith("weekly")
                else "period-20260831",
            )
        extended = list(
            iter_global_jobs(
                config,
                date(2026, 9, 10),
                {"stocks": ["600000.SH", "920061.BJ"], "indexes": ["000300.CSI"]},
            )
        )
        old = [job for job in extended if job["params"]["ts_code"] != "920061.BJ"]
        self.assertEqual(
            {json.dumps(job, sort_keys=True) for job in first},
            {json.dumps(job, sort_keys=True) for job in old},
        )

    def test_current_year_history_has_fixed_period_endpoints(self):
        config = {
            "global_apis": ["weekly", "monthly"],
            "global_history_start": "20250101",
        }
        ids = {"stocks": ["600000.SH"]}
        first = list(iter_global_jobs(config, date(2026, 9, 9), ids))
        later = list(iter_global_jobs(config, date(2026, 10, 7), ids))
        old_history = {
            json.dumps(j, sort_keys=True) for j in first if j["epoch"] == "history"
        }
        new_history = {
            json.dumps(j, sort_keys=True) for j in later if j["epoch"] == "history"
        }
        self.assertTrue(old_history <= new_history)
        for job in later:
            if job["epoch"] != "history" or not job["params"]["start_date"].startswith(
                "2026"
            ):
                continue
            start = date.fromisoformat(job["params"]["start_date"])
            end = date.fromisoformat(job["params"]["end_date"])
            self.assertLessEqual(
                (end - start).days, 6 if job["api_name"] == "weekly" else 30
            )
        # Re-enumerating after a long outage still covers every fully ended period.
        for api, closed in (
            ("weekly", date(2026, 10, 4)),
            ("monthly", date(2026, 9, 30)),
        ):
            covered = set()
            for job in later:
                if job["api_name"] != api:
                    continue
                start = date.fromisoformat(job["params"]["start_date"])
                end = date.fromisoformat(job["params"]["end_date"])
                covered.update(
                    start + timedelta(days=n) for n in range((end - start).days + 1)
                )
            expected = {
                date(2025, 1, 1) + timedelta(days=n)
                for n in range((closed - date(2025, 1, 1)).days + 1)
            }
            self.assertEqual(covered, expected)

    def test_calendar_closure_cross_year_and_leap_month(self):
        config = {
            "global_apis": ["weekly", "monthly"],
            "global_history_start": "20230101",
        }
        ids = {"stocks": [{"ts_code": "600000.SH", "list_status": "D"}]}
        jobs = list(iter_global_jobs(config, date(2024, 3, 1), ids))
        month = next(
            j for j in jobs if j["api_name"] == "monthly" and j["epoch"] != "history"
        )
        self.assertEqual(
            month["params"],
            {"ts_code": "600000.SH", "start_date": "20240101", "end_date": "20240229"},
        )
        before = list(iter_global_jobs(config, date(2026, 1, 1), ids))
        week = next(
            j for j in before if j["api_name"] == "weekly" and j["epoch"] != "history"
        )
        self.assertEqual(week["params"]["end_date"], "20251228")
        after = list(iter_global_jobs(config, date(2026, 1, 5), ids))
        self.assertTrue(
            any(
                j["api_name"] == "weekly"
                and j["epoch"] == "history"
                and j["params"]
                == {
                    "ts_code": "600000.SH",
                    "start_date": "20250101",
                    "end_date": "20251231",
                }
                for j in after
            )
        )
        scope = {
            "global_apis": ["weekly", "monthly"],
            "global_history_start": "20260908",
        }
        self.assertEqual(list(iter_global_jobs(scope, date(2026, 9, 9), ids)), [])
        self.assertTrue(
            all(
                "period_wait_note" in GLOBAL_CONTRACTS[api]
                for api in scope["global_apis"]
            )
        )

    def test_retired_hk_bang_remains_distinct_and_does_not_abort_other_apis(self):
        from backend.shared.tushare_global_contracts import _identifiers

        ids = {
            "hk_stocks": [
                "00013!.HK",
                "00013.HK",
                {"ts_code": "00013!.HK", "list_status": "D"},
            ]
        }
        self.assertEqual(_identifiers(ids)["hk_stocks"], ["00013!.HK", "00013.HK"])
        config = {
            "global_apis": ["hk_daily", "us_daily"],
            "global_history_start": "20260901",
        }
        jobs = list(iter_global_jobs(config, date(2026, 9, 9), ids))
        self.assertEqual({j["api_name"] for j in jobs}, {"hk_daily", "us_daily"})
        self.assertEqual(len(jobs), 18)

    def test_hk_opaque_retirement_suffix(self):
        from backend.shared.tushare_global_contracts import _identifiers

        codes = [
            "02121!AE.HK",
            "02228!AE.HK",
            "03636!AE.HK",
            "03668!AE.HK",
            "03699!AE.HK",
            "02121.HK",
            "02121!.HK",
            "02121!ABCDEFGH.HK",
        ]
        self.assertEqual(_identifiers({"hk_stocks": codes})["hk_stocks"], sorted(codes))
        for code in (
            "02121!ABCDEFGHI.HK",
            "02121!ae.HK",
            "02121!!AE.HK",
            "2121!AE.HK",
            "02121AE.HK",
            "02121!AE.US",
        ):
            with self.subTest(code=code), self.assertRaises(ValueError):
                _identifiers({"hk_stocks": [code]})

    def test_validation_before_first_job(self):
        bad_configs = [
            {"global_apis": ["missing"]},
            {"global_apis": "us_daily"},
            {"global_history_start": "not-date"},
            {"global_history_start": {"missing": "20260101"}},
            {"global_history_start": "20270101"},
            {"global_history_start": 20260101},
        ]
        for config in bad_configs:
            with self.assertRaises(ValueError):
                next(iter_global_jobs(config, date(2026, 9, 9)))
        for ids in (
            {"hk_stocks": ["HK00001"]},
            {"us_stocks": ["AAPL,MSFT"]},
            {"stocks": ["SH600000"]},
        ):
            with self.assertRaises(ValueError):
                next(iter_global_jobs({}, date(2026, 9, 9), ids))
        self.assertEqual(
            list(iter_global_jobs({"global_apis": []}, date(2026, 9, 9))), []
        )


if __name__ == "__main__":
    unittest.main()
