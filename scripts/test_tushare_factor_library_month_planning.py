"""Opt-in month history: exact scope, legacy policy and resumable daily cursors."""

from collections import Counter
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module  # noqa: E402
from backend.shared.tushare_factor_library_contracts import (  # noqa: E402
    FIELDS,
    iter_factor_library_jobs,
    factor_library_prerequisites,
)
from backend.shared.tushare_registry import contract_for  # noqa: E402
import test_tushare_technical_extra_pipeline as fixtures  # noqa: E402

IDS = {"factor_library_stocks": ["T600018.SH", "000001.SZ"]}
CONFIG = {
    "enable_factor_library": True,
    "factor_library_apis": ["factor_value"],
    "factor_library_value_mode": "code_only",
    "factor_library_history_start": "19900101",
    "plan_jobs_per_tick": 3,
}


def days(params):
    start = datetime.strptime(
        params.get("trade_date", params.get("start_date")), "%Y%m%d"
    ).date()
    end = datetime.strptime(
        params.get("trade_date", params.get("end_date")), "%Y%m%d"
    ).date()
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class FactorMonths(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture

    def plan(self, cfg, today=date(2026, 9, 9)):
        with patch.object(self.p, "identifiers", return_value=IDS):
            return self.p.plan_extended(cfg, today)

    def test_partition_coverage_no_gap_no_overlap_leap_year_and_recent_boundary(self):
        for start, today in (
            ("20240130", date(2024, 3, 3)),
            ("20231229", date(2024, 1, 3)),
            ("20260227", date(2026, 3, 9)),
            ("20260907", date(2026, 9, 9)),
            ("20260801", date(2026, 9, 9)),
        ):
            cfg = {
                **CONFIG,
                "factor_library_history_start": start,
                "factor_library_history_window": "month",
            }
            jobs = list(iter_factor_library_jobs(cfg, today, IDS))
            by_code = {code: Counter() for code in IDS["factor_library_stocks"]}
            first_history = False
            for job in jobs:
                p = job["params"]
                self.assertEqual(job["fields"].split(","), FIELDS["factor_value"])
                if job["epoch"] == "history":
                    first_history = True
                    self.assertEqual(set(p), {"ts_code", "start_date", "end_date"})
                    self.assertEqual(p["start_date"][:6], p["end_date"][:6])
                    self.assertLess(max(days(p)), today - timedelta(days=6))
                else:
                    self.assertFalse(first_history)
                    self.assertEqual(set(p), {"ts_code", "trade_date"})
                    self.assertGreaterEqual(min(days(p)), today - timedelta(days=6))
                by_code[p["ts_code"]].update(days(p))
            expected = Counter(
                days({"start_date": start, "end_date": today.strftime("%Y%m%d")})
            )
            self.assertTrue(all(counts == expected for counts in by_code.values()))

    def test_daily_default_byte_identity_and_policy_backward_compatibility(self):
        explicit = {**CONFIG, "factor_library_history_window": "daily"}
        self.assertEqual(
            list(iter_factor_library_jobs(CONFIG, date(1990, 1, 20), IDS)),
            list(iter_factor_library_jobs(explicit, date(1990, 1, 20), IDS)),
        )
        current = module._planning_inputs("factor_library", CONFIG, IDS)
        self.assertEqual(
            current, module._planning_inputs("factor_library", explicit, IDS)
        )
        self.assertEqual(
            current[0],
            "5230e8b9d534c35cd082a84b2aa41cee2638eebdf46120ef7d11893c86c56bb1",
        )
        changed = {**CONFIG, "factor_library_history_window": "month"}
        self.assertNotEqual(
            current, module._planning_inputs("factor_library", changed, IDS)
        )
        self.assertEqual(
            module._planning_inputs("factor_library", changed, IDS),
            module._planning_inputs(
                "factor_library", changed, {**IDS, "stocks": ["600001.SH"]}
            ),
        )

    def test_unfinished_daily_snapshot_default_still_resumes_same_absolute_stream(self):
        self.plan(CONFIG)
        before = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertFalse(before["done"])
        self.assertGreater(before["offset"], 0)
        oldjobs = {r["id"]: dict(r) for r in self.p.db.execute("SELECT * FROM jobs")}
        self.plan(
            {**CONFIG, "factor_library_history_window": "daily"}, date(2026, 9, 10)
        )
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertEqual(
            (after["signature"], after["anchor"]),
            (before["signature"], before["anchor"]),
        )
        self.assertEqual(
            after["offset"], before["offset"] + CONFIG["plan_jobs_per_tick"]
        )
        for key, value in oldjobs.items():
            self.assertEqual(
                dict(
                    self.p.db.execute(
                        "SELECT * FROM jobs WHERE id=?", (key,)
                    ).fetchone()
                ),
                value,
            )
        self.assertTrue(
            all(
                "trade_date" in json.loads(r["job"])["params"]
                for r in self.p.db.execute("SELECT * FROM jobs")
            )
        )

    def test_explicit_month_completed_scope_refresh_preserves_old_jobs(self):
        cfg = {
            **CONFIG,
            "factor_library_history_start": "20260801",
            "plan_jobs_per_tick": 100,
        }
        self.plan(cfg)
        before = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertTrue(before["done"])
        old = {r["id"]: dict(r) for r in self.p.db.execute("SELECT * FROM jobs")}
        self.plan({**cfg, "factor_library_history_window": "month"})
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:factor_library'"
            ).fetchone()
        )
        self.assertTrue(after["done"])
        self.assertNotEqual(after["signature"], before["signature"])
        for key, row in old.items():
            self.assertEqual(
                dict(
                    self.p.db.execute(
                        "SELECT * FROM jobs WHERE id=?", (key,)
                    ).fetchone()
                ),
                row,
            )
        new = [
            json.loads(r["job"])["params"]
            for r in self.p.db.execute("SELECT * FROM jobs")
            if r["id"] not in old
        ]
        self.assertEqual(len(new), 4)
        self.assertEqual(
            {(r["start_date"], r["end_date"]) for r in new},
            {("20260801", "20260831"), ("20260901", "20260902")},
        )

    def test_unknown_scope_discovery_and_mode_not_silently_replaced(self):
        for value in ("weekly", None, 30):
            cfg = {**CONFIG, "factor_library_history_window": value}
            with self.assertRaises(ValueError):
                list(iter_factor_library_jobs(cfg, date(2026, 9, 9), IDS))
            with self.assertRaises(ValueError):
                factor_library_prerequisites(IDS, config=cfg)
        with self.assertRaises(ValueError):
            list(
                iter_factor_library_jobs(
                    {
                        **CONFIG,
                        "factor_library_value_mode": "factor_name",
                        "factor_library_history_window": "month",
                    },
                    date(2026, 9, 9),
                    IDS,
                )
            )
        self.assertEqual(
            list(
                iter_factor_library_jobs(
                    {**CONFIG, "factor_library_history_window": "month"},
                    date(2026, 9, 9),
                    {},
                )
            ),
            [],
        )
        cfg = {**CONFIG, "factor_library_history_window": "month"}
        cfg.pop("factor_library_history_start")
        jobs = list(iter_factor_library_jobs(cfg, date(2026, 9, 9), IDS))
        self.assertEqual(len(jobs), 14)
        self.assertTrue(all(j["epoch"] != "history" for j in jobs))

    def test_cap_still_preserves_all_columns_and_legal_date_split_not_fake_completion(
        self,
    ):
        params = {
            "ts_code": "T600018.SH",
            "start_date": "20260801",
            "end_date": "20260831",
        }
        row = {
            "factor_name": "observed",
            "ts_code": "T600018.SH",
            "trade_date": "20260817",
            "factor_value": None,
            "unknown_source": "kept",
        }
        result = self.capture("factor_value", params, [row] * 6000)[2]
        self.assertEqual(result["status"], "possibly_truncated")
        self.assertEqual(len(self.p.records(result)), 6000)
        self.assertEqual(contract_for("factor_value")["row_cap"], 6000)
        children = self.p.date_children({"api_name": "factor_value", "params": params})
        self.assertEqual(
            Counter(d for p in children for d in days(p)), Counter(days(params))
        )
        self.assertTrue(all(p["ts_code"] == "T600018.SH" for p in children))
        self.assertIsNone(
            self.p.date_children(
                {
                    "api_name": "factor_value",
                    "params": {
                        "ts_code": "T600018.SH",
                        "start_date": "20260817",
                        "end_date": "20260817",
                    },
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
