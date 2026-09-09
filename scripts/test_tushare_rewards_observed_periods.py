"""Observed report-period supplements; temporary storage and mock HTTP only."""

from datetime import date
from itertools import islice
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import PLANNERS, contract_for
from backend.shared.tushare_stock_context_contracts import (
    FIELDS,
    observed_reward_periods,
    iter_stock_context_jobs,
    stock_context_prerequisites,
)
from backend.shared.tushare_store import read_dataset
from test_tushare_stock_context_pipeline import source
import test_tushare_technical_extra_pipeline as fixtures

TODAY = date(2026, 9, 10)
CONFIG = {
    "enable_stock_context": True,
    "stock_context_apis": ["stk_rewards"],
    "plan_jobs_per_tick": 10,
}


class PureObservedPeriods(unittest.TestCase):
    def test_exact_actual_pairs_only_preserve_t_and_discovery(self):
        identifiers = {
            "stocks": ["600001.SH", "T600001.SH"],
            "reward_periods": [
                {"ts_code": "T600001.SH", "end_date": "20240229"},
                {"ts_code": "T600001.SH", "end_date": "20251231"},
                {"ts_code": "T600001.SH", "end_date": "20251231"},
                {"ts_code": "600001.SH", "end_date": "20240917"},
            ],
        }
        jobs = list(iter_stock_context_jobs(CONFIG, TODAY, identifiers))
        recent = [j for j in jobs if j["epoch"] != "history"]
        history = [j for j in jobs if j["epoch"] == "history"]
        self.assertEqual(
            [j["params"] for j in recent],
            [
                {"ts_code": "600001.SH"},
                {"ts_code": "600001.SH", "end_date": "20240917"},
                {"ts_code": "T600001.SH"},
                {"ts_code": "T600001.SH", "end_date": "20251231"},
            ],
        )
        self.assertEqual(
            {(j["params"]["ts_code"], j["params"]["end_date"]) for j in history},
            {
                ("T600001.SH", "20240229"),
                ("T600001.SH", "20251231"),
                ("600001.SH", "20240917"),
            },
        )
        self.assertTrue(all(set(j["params"]) <= {"ts_code", "end_date"} for j in jobs))
        self.assertTrue(
            all(j["fields"].split(",") == FIELDS["stk_rewards"] for j in jobs)
        )
        # No regular-quarter enumeration, no cross-product to the other stock.
        self.assertEqual(len(history), 3)
        self.assertEqual(
            list(islice(iter_stock_context_jobs(CONFIG, TODAY, identifiers), 2)),
            recent[:2],
        )

    def test_malformed_period_is_gap_not_ann_date_or_normalized_guess(self):
        ids = {
            "stocks": ["T600001.SH"],
            "reward_periods": [
                {"ts_code": "T600001.SH", "end_date": "20250229"},
                {"ts_code": "T600001.SH", "end_date": None},
                {"ts_code": "T600001.SH", "end_date": "2025-12-31"},
                {
                    "ts_code": "T600001.SH",
                    "end_date": "20251231",
                    "ann_date": "20260904",
                },
                {"ts_code": "HK00001", "end_date": "20251231"},
                {"ts_code": "T600001.SH", "end_date": "20240229"},
            ],
        }
        pairs, invalid = observed_reward_periods(ids)
        self.assertEqual(pairs, [("T600001.SH", "20240229")])
        self.assertEqual(invalid, 5)
        gap = next(
            g
            for g in stock_context_prerequisites(ids, config=CONFIG)
            if g["reason"] == "observed_period_inventory_unverified"
        )
        self.assertEqual(gap["invalid_period_identities"], 5)
        self.assertFalse(gap["period_inventory_complete"])
        self.assertFalse(gap["parent_saturation_resolved"])
        self.assertEqual(len(list(iter_stock_context_jobs(CONFIG, TODAY, ids))), 3)

    def test_missing_periods_keeps_code_only_and_default_family_stays_off(self):
        jobs = list(iter_stock_context_jobs(CONFIG, TODAY, {"stocks": ["T600001.SH"]}))
        self.assertEqual([j["params"] for j in jobs], [{"ts_code": "T600001.SH"}])
        self.assertEqual(contract_for("stk_rewards")["row_cap"], 1000)
        self.assertFalse(contract_for("stk_rewards")["row_cap_verified"])
        self.assertIsNone(contract_for("stk_rewards").get("pagination"))

    def test_periods_do_not_change_unrelated_family_policy_or_stock_context_siblings(
        self,
    ):
        cfg = {
            "stock_context_apis": ["stk_managers", "stk_nineturn", "stk_ah_comparison"]
        }
        before = module._planning_inputs("stock_context", cfg, {})
        ids = {
            "stock_context_reward_periods": [
                {"ts_code": "T600001.SH", "end_date": "20251231"}
            ]
        }
        self.assertEqual(module._planning_inputs("stock_context", cfg, ids), before)
        self.assertEqual(
            module._planning_inputs(
                "technical_extra", {"technical_extra_apis": ["stk_factor"]}, ids
            ),
            module._planning_inputs(
                "technical_extra", {"technical_extra_apis": ["stk_factor"]}, {}
            ),
        )
        _, frozen = module._planning_inputs("stock_context", CONFIG, ids)
        self.assertIn("stock_context_reward_periods", frozen)
        self.assertEqual(
            frozen["stock_context_reward_periods"], ids["stock_context_reward_periods"]
        )


class ObservedRuntime(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture
    discovery = fixtures.TechnicalExtraRuntime.discovery

    def test_attempts_union_keeps_retired_periods_but_not_other_api_end_dates(self):
        oldrow = source("stk_rewards", ts_code="T600001.SH", end_date="20180630")
        old, _, _ = self.capture(
            "stk_rewards", {"ts_code": "T600001.SH"}, [oldrow], more=True, epoch="same"
        )
        self.capture(
            "stk_rewards",
            {"ts_code": "T600001.SH"},
            [source("stk_rewards", end_date="20251231")],
            epoch="same",
        )
        # The older full body remains only in attempts, not the latest jobs.result.
        self.discovery("income", [{"ts_code": "T600001.SH", "end_date": "20011231"}])
        self.discovery(
            "stk_rewards",
            [
                {"ts_code": "600001.SH", "end_date": None},
                {"ts_code": "600001.SH", "end_date": "20250229"},
            ],
        )
        ids = self.p.identifiers()
        self.assertIn(
            {"ts_code": "T600001.SH", "end_date": "20180630"},
            ids["stock_context_reward_periods"],
        )
        self.assertNotIn(
            {"ts_code": "T600001.SH", "end_date": "20011231"},
            ids["stock_context_reward_periods"],
        )
        self.assertEqual(set(ids["stock_context_stocks"]), {"T600001.SH", "600001.SH"})
        jobs = list(PLANNERS["stock_context"](CONFIG, TODAY, ids))
        self.assertIn(
            {"ts_code": "T600001.SH", "end_date": "20180630"},
            [j["params"] for j in jobs],
        )
        self.assertNotIn(
            {"ts_code": "600001.SH", "end_date": "20250229"},
            [j["params"] for j in jobs],
        )
        self.p.record_extra_planning_gaps("stock_context", CONFIG, ids)
        row = self.p.db.execute(
            "SELECT reason FROM capability WHERE scope='planning:stock_context:stk_rewards:observed_period_inventory_unverified'"
        ).fetchone()
        self.assertEqual(json.loads(row[0])["invalid_period_identities"], 2)

    def test_supplement_fixed_all_columns_do_not_complete_saturated_parent(self):
        old_release = self.p.publish()
        raw = [
            source("stk_rewards", end_date=p, supplier_extra=None)
            for p in ("20240630", "20251231")
        ]
        parent, job, result = self.capture(
            "stk_rewards", {"ts_code": "T600001.SH"}, raw, more=True
        )
        parent_before = tuple(
            self.p.db.execute(
                "SELECT * FROM jobs WHERE id=?", (parent["id"],)
            ).fetchone()
        )
        self.assertEqual(result["status"], "possibly_truncated")
        self.assertIsNone(self.p.split_request(parent, job, result))
        self.p.plan_extended({}, TODAY)
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM jobs WHERE state='pending'"
            ).fetchone()[0],
            0,
        )
        for _ in range(3):
            self.p.plan_extended(CONFIG, TODAY)
        self.assertEqual(
            tuple(
                self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (parent["id"],)
                ).fetchone()
            ),
            parent_before,
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            0,
        )
        # Successful legal period response does not become evidence of parent completeness.
        self.capture(
            "stk_rewards",
            {"ts_code": "T600001.SH", "end_date": "20251231"},
            [raw[1]],
            epoch="history",
        )
        new_release = self.p.publish()
        table = read_dataset(self.root, new_release, "stk_rewards")
        self.assertEqual(table.num_rows, 2)
        self.assertEqual(
            set(table.to_pylist()[0]) & set(FIELDS["stk_rewards"]),
            set(FIELDS["stk_rewards"]),
        )
        self.assertTrue(
            all(
                r["source_ts_code"] == "T600001.SH" and r["ts_code"] == "SHT600001"
                for r in table.to_pylist()
            )
        )
        self.assertTrue(all(r["supplier_extra"] is None for r in table.to_pylist()))
        self.assertEqual(
            read_dataset(
                self.root,
                new_release,
                "stk_rewards",
                date_field="end_date",
                start_date="20251231",
                end_date="20251231",
            ).num_rows,
            1,
        )
        self.assertEqual(
            read_dataset(
                self.root,
                new_release,
                "stk_rewards",
                start_date="20251231",
                end_date="20251231",
            ).num_rows,
            0,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (parent["id"],)
            ).fetchone()[0],
            "quality",
        )
        with self.assertRaisesRegex(ValueError, "Dataset unavailable"):
            read_dataset(self.root, old_release, "stk_rewards")

    def test_new_older_period_added_during_frozen_history_is_eventually_enqueued(self):
        self.capture(
            "stk_rewards",
            {"ts_code": "T600001.SH"},
            [
                source("stk_rewards", end_date=p)
                for p in ("20231231", "20240630", "20241231")
            ],
        )
        cfg = {**CONFIG, "plan_jobs_per_tick": 1}
        self.p.plan_extended(cfg, TODAY)
        self.capture(
            "stk_rewards",
            {"ts_code": "T600001.SH"},
            [source("stk_rewards", end_date="20180630")],
            epoch="new-observed",
        )
        for _ in range(16):
            self.p.plan_extended(cfg, TODAY)
        rows = self.p.db.execute(
            "SELECT job FROM jobs WHERE epoch='history' AND group_name='stock_context'"
        ).fetchall()
        self.assertEqual(
            {json.loads(r[0])["params"]["end_date"] for r in rows},
            {"20180630", "20231231", "20240630", "20241231"},
        )
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.p.plan_extended(cfg, TODAY)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )


if __name__ == "__main__":
    unittest.main()
