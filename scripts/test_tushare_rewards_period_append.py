"""Bounded observed-period append while the original family snapshot progresses."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import APPEND_PLANNERS, PLANNERS
from test_tushare_stock_context_pipeline import source
import test_tushare_technical_extra_pipeline as fixtures

TODAY = date(2026, 9, 10)
SCOPE = "history:stock_rewards_periods"
CONFIG = {
    "enable_stock_context": True,
    "stock_context_apis": ["stk_managers", "stk_rewards"],
    "history_start": "19900101",
    "plan_jobs_per_tick": 2,
    "history_plan_seconds": 5,
}


def identifiers(periods):
    return {
        "stock_context_stocks": ["X20720.SZ"] + [f"{n:06d}.SZ" for n in range(100)],
        "stock_context_reward_periods": [
            {"ts_code": "000001.SZ", "end_date": period} for period in periods
        ],
    }


class RewardAppend(unittest.TestCase):
    setUp = fixtures.TechnicalExtraRuntime.setUp
    capture = fixtures.TechnicalExtraRuntime.capture

    def plan(self, ids, config=None):
        with patch.object(self.p, "identifiers", return_value=deepcopy(ids)):
            return self.p.plan_extended(config or CONFIG, TODAY)

    def state(self, name):
        row = self.p.db.execute(
            "SELECT * FROM planning_state WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def pairs(self):
        return {
            (j["params"]["ts_code"], j["params"]["end_date"])
            for (saved,) in self.p.db.execute(
                "SELECT job FROM jobs WHERE epoch='history'"
            )
            if (j := json.loads(saved))["api_name"] == "stk_rewards"
        }

    def test_new_pairs_bypass_large_parent_snapshot_without_reset(self):
        old_ids = identifiers(["20201231"])
        self.plan(old_ids)
        old_states = {
            n: self.state(n) for n in ("recent:stock_context", "history:stock_context")
        }
        next_ids = identifiers(["20101231", "20201231", "20251231"])
        before = deepcopy(next_ids)
        self.plan(next_ids)
        # Append finishes the frozen first generation before refreshing it.
        for _ in range(3):
            self.plan(next_ids)
        self.assertEqual(
            self.pairs(),
            {("000001.SZ", p) for p in ("20101231", "20201231", "20251231")},
        )
        for name, old in old_states.items():
            current = self.state(name)
            self.assertEqual(current["signature"], old["signature"])
            self.assertEqual(current["anchor"], old["anchor"])
            self.assertGreater(current["offset"], old["offset"])
            self.assertFalse(current["done"])
        self.assertEqual(next_ids, before)
        self.assertIsNone(self.state("recent:stock_rewards_periods"))
        self.assertNotIn("stock_rewards_periods", PLANNERS)
        self.assertIn("stock_rewards_periods", APPEND_PLANNERS)
        jobs = [json.loads(r[0]) for r in self.p.db.execute("SELECT job FROM jobs")]
        self.assertNotIn("X20720.SZ", json.dumps(jobs))

    def test_growth_cannot_restart_unfinished_append_and_restart_resumes(self):
        initial = [f"{year}1231" for year in range(2010, 2016)]
        self.plan(identifiers(initial))
        frozen = self.state(SCOPE)
        self.assertEqual(frozen["offset"], 2)
        # Every tick adds older observations that would reorder a live iterator.
        for year in (2009, 2008):
            initial.insert(0, f"{year}1231")
            self.plan(identifiers(initial))
            self.assertEqual(self.state(SCOPE)["signature"], frozen["signature"])
        self.assertEqual(self.state(SCOPE)["offset"], 6)
        self.assertTrue(
            {("000001.SZ", f"{year}1231") for year in range(2010, 2016)} <= self.pairs()
        )
        # Restart the actual temporary SQLite owner; no in-memory append cursor.
        self.p.close()
        self.p = module.Pipeline(self.root, self.p.catalog)
        self.addCleanup(self.p.close)
        for _ in range(8):
            self.plan(identifiers(initial))
        self.assertEqual(self.pairs(), {("000001.SZ", p) for p in initial})
        self.assertTrue(self.state(SCOPE)["done"])
        count = len(self.pairs())
        self.plan(identifiers(initial))
        self.assertEqual(len(self.pairs()), count)

    def test_append_uses_existing_history_identity_and_preserves_capped_parent(self):
        parent, _, _ = self.capture(
            "stk_rewards",
            {"ts_code": "000001.SZ"},
            [source("stk_rewards", ts_code="000001.SZ", end_date="20251231")],
            more=True,
        )
        parent_before = tuple(parent)
        existing_id = self.p.enqueue(
            "stk_rewards",
            {"ts_code": "000001.SZ", "end_date": "20251231"},
            55,
            "history",
        )
        before = tuple(
            self.p.db.execute(
                "SELECT * FROM jobs WHERE id=?", (existing_id,)
            ).fetchone()
        )
        self.plan(identifiers(["20251231"]))
        self.assertEqual(self.state(SCOPE)["offset"], 1)
        self.assertTrue(self.state(SCOPE)["done"])
        self.assertEqual(
            tuple(
                self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (existing_id,)
                ).fetchone()
            ),
            before,
        )
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
        self.assertEqual(len(self.pairs()), 1)

    def test_no_api_selection_no_append_and_invalid_container_stays_blocked(self):
        for config in (
            {},
            {**CONFIG, "enable_stock_context": False},
            {**CONFIG, "stock_context_apis": ["stk_managers"]},
        ):
            with patch.object(
                self.p, "identifiers", return_value=identifiers(["20251231"])
            ):
                self.p.plan_extended(config, TODAY)
            self.assertIsNone(self.state(SCOPE))
        bad = identifiers(["20251231"])
        bad["stock_context_reward_periods"] = {}
        self.plan(bad)
        self.assertIsNone(self.state(SCOPE))
        self.assertEqual(
            self.p.db.execute(
                "SELECT status FROM capability WHERE scope='planning:stock_context'"
            ).fetchone()[0],
            "validation_blocked",
        )

    def test_500_hard_cap_uses_only_pair_dependency_and_time_limit_is_durable(self):
        ids = identifiers([f"{year}1231" for year in range(1400, 2001)])
        config = {
            **CONFIG,
            "stock_context_apis": ["stk_rewards"],
            "plan_jobs_per_tick": 2000,
        }
        # Parent planner omitted only to isolate the append hard cap.
        with patch.dict(module.PLANNERS, {}, clear=True):
            stats = self.plan(ids, config)
        self.assertEqual(stats[SCOPE]["new_jobs"], 500)
        self.assertEqual(self.state(SCOPE)["offset"], 500)
        self.assertFalse(self.state(SCOPE)["done"])
        snapshot = json.loads(self.state(SCOPE)["signature"])
        self.assertEqual(set(snapshot["identifiers"]), {"stock_context_reward_periods"})
        original = module._planning_inputs("stock_rewards_periods", config, ids)
        changed = deepcopy(ids)
        changed["stock_context_stocks"] = ["900001.SH"]
        self.assertEqual(
            module._planning_inputs(
                "stock_rewards_periods",
                {**config, "history_start": "20200101"},
                changed,
            ),
            original,
        )
        # Zero work under a spent monotonic budget must not mark remaining done.
        with (
            patch.dict(module.PLANNERS, {}, clear=True),
            patch.object(module.time, "monotonic", side_effect=range(1000)),
        ):
            stats = self.plan(ids, {**config, "history_plan_seconds": 0.01})
        self.assertEqual(stats[SCOPE]["stop_reason"], "time_limit")
        self.assertEqual(self.state(SCOPE)["offset"], 500)
        self.assertFalse(self.state(SCOPE)["done"])
        with patch.dict(module.PLANNERS, {}, clear=True):
            self.plan(ids, config)
        self.assertEqual(len(self.pairs()), 601)
        self.assertTrue(self.state(SCOPE)["done"])


if __name__ == "__main__":
    unittest.main()
