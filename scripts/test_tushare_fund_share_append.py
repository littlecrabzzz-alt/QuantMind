"""Historical fund-share dates bypass the larger market planner cursor."""

from copy import deepcopy
from datetime import date
import json
import unittest
from unittest.mock import patch

from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import APPEND_PLANNERS, PLANNERS
from scripts import test_tushare_equity_event_pipeline as fixtures


TODAY = date(2026, 9, 10)
CONFIG = {
    "enable_market": True,
    "market_apis": ["fund_share"],
    "history_start": "20260901",
    "plan_jobs_per_tick": 500,
    "history_plan_seconds": 5,
}


class FundShareAppend(unittest.TestCase):
    setUp = fixtures.EquityEventPipeline.setUp

    def plan_append(self, config=CONFIG):
        with (
            patch.object(self.p, "identifiers", return_value={}),
            patch.dict(module.PLANNERS, {}, clear=True),
        ):
            return self.p.plan_extended(config, TODAY)

    def state(self, name):
        row = self.p.db.execute(
            "SELECT * FROM planning_state WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def jobs(self):
        return [
            json.loads(row[0])
            for row in self.p.db.execute("SELECT job FROM jobs ORDER BY id")
        ]

    def test_history_only_scope_is_idempotent(self):
        self.assertNotIn("fund_share_history", PLANNERS)
        self.assertIn("fund_share_history", APPEND_PLANNERS)
        first = self.plan_append()["history:fund_share_history"]
        self.assertTrue(first["done"])
        self.assertEqual(first["new_jobs"], 4)
        jobs = self.jobs()
        self.assertEqual({job["api_name"] for job in jobs}, {"fund_share"})
        self.assertEqual(
            {job["params"]["market"] for job in jobs}, {"SH", "SZ"}
        )
        self.assertEqual(
            {row[0] for row in self.p.db.execute("SELECT DISTINCT epoch FROM jobs")},
            {"history"},
        )
        before = deepcopy(
            [tuple(row) for row in self.p.db.execute("SELECT * FROM jobs ORDER BY id")]
        )
        self.p.db.execute(
            "DELETE FROM planning_state WHERE name='history:fund_share_history'"
        )
        self.p.db.commit()
        second = self.plan_append()["history:fund_share_history"]
        self.assertEqual((second["new_jobs"], second["existing_jobs"]), (0, 4))
        self.assertEqual(
            before,
            [tuple(row) for row in self.p.db.execute("SELECT * FROM jobs ORDER BY id")],
        )

    def test_parent_cursor_is_untouched(self):
        self.p.db.execute(
            "INSERT INTO planning_state VALUES(?,?,?,?,?)",
            ("history:market", "20260909", "frozen-parent", 169787, 0),
        )
        self.p.db.commit()
        frozen = self.state("history:market")
        self.plan_append()
        self.assertEqual(self.state("history:market"), frozen)
        self.assertIsNone(self.state("recent:fund_share_history"))

    def test_disabled_or_unselected_parent_does_not_create_scope(self):
        self.plan_append({**CONFIG, "enable_market": False})
        self.assertIsNone(self.state("history:fund_share_history"))
        self.plan_append({**CONFIG, "market_apis": ["fund_nav"]})
        self.assertIsNone(self.state("history:fund_share_history"))


if __name__ == "__main__":
    unittest.main()
