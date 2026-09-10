"""Historical announcement windows bypass the equity-event stock fanout."""

from copy import deepcopy
from datetime import date
import json
import unittest
from unittest.mock import patch

from backend.shared import tushare_pipeline as module
from backend.shared.tushare_registry import APPEND_PLANNERS, PLANNERS
from scripts import test_tushare_equity_event_pipeline as fixtures


TODAY = date(2026, 9, 10)
APIS = ("stk_holdernumber", "stk_holdertrade", "repurchase")
CONFIG = {
    "enable_equity_event": True,
    "equity_event_apis": [
        "dividend",
        *APIS,
        "share_float",
        "top10_holders",
        "top10_floatholders",
    ],
    "history_start": "20250101",
    "plan_jobs_per_tick": 500,
    "history_plan_seconds": 5,
}


class EquityAnnouncementAppend(unittest.TestCase):
    setUp = fixtures.EquityEventPipeline.setUp

    def plan_append(self, config=CONFIG):
        with (
            patch.object(self.p, "identifiers", return_value={"stocks": ["600036.SH"]}),
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

    def test_history_only_scope_interleaves_three_apis_and_is_idempotent(self):
        self.assertNotIn("equity_announcements", PLANNERS)
        self.assertIn("equity_announcements", APPEND_PLANNERS)
        first = self.plan_append()["history:equity_announcements"]
        self.assertTrue(first["done"])
        self.assertEqual(first["new_jobs"], 63)
        jobs = self.jobs()
        self.assertEqual({job["api_name"] for job in jobs}, set(APIS))
        self.assertEqual(
            {row[0] for row in self.p.db.execute("SELECT DISTINCT epoch FROM jobs")},
            {"history"},
        )
        self.assertEqual(len(jobs), 63)
        before = deepcopy(
            [tuple(row) for row in self.p.db.execute("SELECT * FROM jobs ORDER BY id")]
        )
        self.p.db.execute(
            "DELETE FROM planning_state WHERE name='history:equity_announcements'"
        )
        self.p.db.commit()
        second = self.plan_append()["history:equity_announcements"]
        self.assertEqual((second["new_jobs"], second["existing_jobs"]), (0, 63))
        self.assertEqual(
            before,
            [tuple(row) for row in self.p.db.execute("SELECT * FROM jobs ORDER BY id")],
        )

    def test_parent_cursor_and_signature_are_untouched(self):
        self.p.db.execute(
            "INSERT INTO planning_state VALUES(?,?,?,?,?)",
            ("history:equity_event", "20260909", "frozen-parent", 175000, 0),
        )
        self.p.db.commit()
        frozen = self.state("history:equity_event")
        self.plan_append()
        self.assertEqual(self.state("history:equity_event"), frozen)
        self.assertIsNone(self.state("recent:equity_announcements"))

    def test_disabled_or_unselected_parent_does_not_create_scope(self):
        self.plan_append({**CONFIG, "enable_equity_event": False})
        self.assertIsNone(self.state("history:equity_announcements"))
        self.plan_append({**CONFIG, "equity_event_apis": ["dividend"]})
        self.assertIsNone(self.state("history:equity_announcements"))


if __name__ == "__main__":
    unittest.main()
