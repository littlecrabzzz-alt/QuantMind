#!/usr/bin/env python3
"""Offline retirement tests for legacy invalid Tushare request shapes."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_futures_extra_contracts import (  # noqa: E402
    FUT_INDEX_DAILY_DOCUMENTED_CODES,
)
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_invalid_request_retirement as retirement  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
FACTOR_APIS = ("idx_factor_pro", "fund_factor_pro", "cb_factor_pro")


class InvalidRequestRetirement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)

    def enqueue(self, api, params, *, state="pending", epoch="history"):
        key = self.pipeline.enqueue(api, params, 55, epoch)
        if state != "pending":
            self.pipeline.db.execute("UPDATE jobs SET state=? WHERE id=?", (state, key))
        return key

    def invalid(self, api, params, *, attempted=True, epoch="history"):
        key = self.enqueue(api, params, epoch=epoch)
        result = None
        if attempted:
            result = json.dumps(
                {"api_name": api, "status": "api_error", "code": 50101},
                sort_keys=True,
            )
            self.pipeline.db.execute(
                "INSERT INTO attempts VALUES(?,?,?)", (key, 1, result)
            )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',tries=?,result=? WHERE id=?",
            (int(attempted), result, key),
        )
        self.pipeline.db.execute(
            "INSERT INTO capability VALUES(?,?,?,?)",
            (
                "dispatch:" + key,
                "request_contract_blocked",
                "fixture",
                json.dumps({"api_name": api, "coverage_proven": False}),
            ),
        )
        return key

    def factor_days(self, api, *days):
        return [self.enqueue(api, {"trade_date": day}) for day in days]

    def futures_ranges(self, *, omit=None):
        return [
            self.enqueue(
                "fut_index_daily",
                {
                    "ts_code": code,
                    "start_date": "20240101",
                    "end_date": "20241231",
                },
            )
            for code in FUT_INDEX_DAILY_DOCUMENTED_CODES
            if code != omit
        ]

    def snapshot(self):
        return {
            table: [
                tuple(row)
                for row in self.pipeline.db.execute(f"SELECT * FROM {table} ORDER BY 1")
            ]
            for table in (
                "jobs",
                "attempts",
                "capability",
                "partition_splits",
                "partition_children",
            )
        }

    def fixture(self):
        invalid = {
            api: self.invalid(
                api,
                {"start_date": "20240229", "end_date": "20240229"},
                attempted=api != "fund_factor_pro",
            )
            for api in FACTOR_APIS
        }
        invalid["fut_index_daily"] = self.invalid(
            "fut_index_daily",
            {"trade_date": "20240229"},
            attempted=False,
            epoch="20240301",
        )
        replacements = {
            api: self.factor_days(api, "20240229")[0] for api in FACTOR_APIS
        }
        replacements["fut_index_daily"] = self.futures_ranges()
        unrelated = self.enqueue(
            "fut_index_daily",
            {
                "ts_code": "NHCI.NH",
                "start_date": "20230101",
                "end_date": "20231231",
            },
            state="blocked",
        )
        self.pipeline.db.commit()
        return invalid, replacements, unrelated

    def test_dry_run_rolls_back_every_table(self):
        self.fixture()
        before = self.snapshot()
        report = retirement.migrate(self.pipeline)
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["candidate_jobs"], 4)
        self.assertEqual(report["required_factor_day_coverage"], 3)
        self.assertEqual(report["required_futures_code_day_coverage"], 56)
        self.assertEqual(report["candidate_epochs"], ["20240301", "history"])
        self.assertEqual(report["replacement_epochs"], ["20240301", "history"])
        self.assertEqual(report["missing_coverage_units"], 0)
        self.assertEqual(self.snapshot(), before)

    def test_apply_preserves_evidence_and_retires_only_covered_invalid_jobs(self):
        invalid, replacements, unrelated = self.fixture()
        attempts = [
            tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")
        ]
        results = dict(
            self.pipeline.db.execute(
                "SELECT id,result FROM jobs WHERE id IN (?,?,?,?)",
                tuple(invalid.values()),
            )
        )
        report = retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(report["superseded_jobs"], 4)
        self.assertEqual(report["candidate_attempts_preserved"], 2)
        self.assertEqual(report["factor_replacement_jobs_used"], 3)
        self.assertEqual(report["futures_replacement_jobs_available"], 56)
        states = dict(self.pipeline.db.execute("SELECT id,state FROM jobs"))
        for key in invalid.values():
            self.assertEqual(states[key], "superseded")
        for api in FACTOR_APIS:
            self.assertEqual(states[replacements[api]], "pending")
        for key in replacements["fut_index_daily"]:
            self.assertEqual(states[key], "pending")
        self.assertEqual(states[unrelated], "blocked")
        self.assertEqual(
            dict(
                self.pipeline.db.execute(
                    "SELECT id,result FROM jobs WHERE id IN (?,?,?,?)",
                    tuple(invalid.values()),
                )
            ),
            results,
        )
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts")],
            attempts,
        )
        for key in invalid.values():
            status, reason = self.pipeline.db.execute(
                "SELECT status,reason FROM capability WHERE scope=?",
                ("dispatch:" + key,),
            ).fetchone()
            self.assertEqual(status, "request_contract_superseded")
            self.assertTrue(json.loads(reason)["coverage_proven"])
            self.assertEqual(json.loads(reason)["upstream_calls"], 0)
        second = retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(second["candidate_jobs"], 0)
        self.assertEqual(second["superseded_jobs"], 0)

    def test_missing_factor_day_refuses_without_changes(self):
        self.invalid(
            "idx_factor_pro",
            {"start_date": "20240228", "end_date": "20240229"},
        )
        self.factor_days("idx_factor_pro", "20240228")
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack usable replacements"):
            retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(self.snapshot(), before)

    def test_missing_documented_futures_code_refuses_without_changes(self):
        self.invalid("fut_index_daily", {"trade_date": "20240229"})
        self.futures_ranges(omit=FUT_INDEX_DAILY_DOCUMENTED_CODES[-1])
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "lack usable replacements"):
            retirement.migrate(self.pipeline, apply=True)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
