"""Offline cadence tests: real durable DB/checkpoints, simulated bounded stages."""

import json
import sqlite3
import unittest
from unittest.mock import patch

import test_tushare_publish_interval as fixture

module = fixture.module
REAL_PLAN = module.Pipeline.plan_extended


class PlanningInterval(unittest.TestCase):
    # Reuse the existing isolated publication fixture, without inheriting its tests.
    acquire = fixture.PublicationInterval.acquire
    register = fixture.PublicationInterval.register
    tick = fixture.PublicationInterval.tick
    saved = fixture.PublicationInterval.saved
    checkpoint = fixture.PublicationInterval.checkpoint

    def setUp(self):
        fixture.PublicationInterval.setUp(self)
        self.config["planning_interval_seconds"] = 900

    def planning_checkpoint(self):
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            return db.execute(
                "SELECT name,value FROM scheduler_state "
                "WHERE name GLOB 'planning_success:*' ORDER BY name"
            ).fetchall()

    def published(self):
        self.assertEqual(self.tick()["status"], "publish_only")
        self.assertEqual(self.planning_checkpoint(), [])

    def test_first_enable_is_plan_only_then_restart_acquires_without_initialize(self):
        self.published()
        with patch.object(
            module, "get_secret", side_effect=AssertionError("no source")
        ):
            planned = self.tick(1)
        self.assertEqual(planned["status"], "planning_only")
        self.assertEqual(planned["requests"], 0)
        self.assertEqual(planned["planning_cadence"]["reason"], "first_enabled")
        self.assertEqual(self.acquisitions, 0)
        self.assertEqual(self.registrations, 0)
        self.assertFalse(planned["publication"]["performed"])
        checkpoint = self.planning_checkpoint()
        with (
            patch.object(module.Pipeline, "initialize", side_effect=AssertionError),
            patch.object(module.Pipeline, "plan_extended", side_effect=AssertionError),
        ):
            deferred = self.tick(120)
        self.assertEqual(deferred["planning_cadence"]["status"], "deferred")
        self.assertNotIn("initialize", deferred["timing"]["stage_seconds"])
        self.assertNotIn("planning", deferred["timing"]["stage_seconds"])
        self.assertEqual(self.planning_checkpoint(), checkpoint)
        self.assertEqual(self.acquisitions, 1)
        self.assertEqual(self.registrations, 1)

    def test_publish_priority_does_not_advance_due_planning(self):
        self.published()
        self.tick(1)
        checkpoint = self.planning_checkpoint()
        result = self.tick(900)
        self.assertEqual(result["status"], "publish_only")
        self.assertEqual(result["planning_cadence"]["status"], "not_checked")
        self.assertEqual(self.planning_checkpoint(), checkpoint)
        result = self.tick(1)
        self.assertEqual(result["status"], "planning_only")
        self.assertEqual(result["planning_cadence"]["reason"], "interval_due")
        self.assertGreater(self.planning_checkpoint()[0][1], checkpoint[0][1])

    def test_configuration_change_and_return_to_previous_config_force_plan(self):
        self.published()
        self.tick(1)
        first = self.planning_checkpoint()[0][0]
        self.config["enable_structured"] = True
        result = self.tick(1)
        self.assertEqual(result["planning_cadence"]["reason"], "configuration_changed")
        self.assertNotEqual(self.planning_checkpoint()[0][0], first)
        del self.config["enable_structured"]
        result = self.tick(1)
        self.assertEqual(result["planning_cadence"]["reason"], "configuration_changed")
        self.assertEqual(self.planning_checkpoint()[0][0], first)
        self.assertEqual(len(self.planning_checkpoint()), 1)

    def test_clock_rollback_and_failed_planning_keep_old_checkpoint(self):
        self.published()
        self.tick(10)
        checkpoint = self.planning_checkpoint()
        # Keep time above publish_success_at so rollback targets planning itself.
        with patch.object(
            module.Pipeline, "plan_extended", side_effect=RuntimeError("fixture")
        ):
            with self.assertRaises(RuntimeError):
                self.tick(-5)
        self.assertEqual(self.planning_checkpoint(), checkpoint)
        self.assertEqual(self.saved()["planning_cadence"]["status"], "failed")
        self.assertEqual(self.saved()["timing"]["failed_stage"], "planning")
        self.assertEqual(self.acquisitions, 0)
        result = self.tick()
        self.assertEqual(result["planning_cadence"]["reason"], "clock_rollback")
        self.assertEqual(result["status"], "planning_only")

    def test_initialize_failure_and_checkpoint_transaction_failure_are_retryable(self):
        self.published()
        with patch.object(
            module.Pipeline, "initialize", side_effect=RuntimeError("fixture")
        ):
            with self.assertRaises(RuntimeError):
                self.tick(1)
        self.assertEqual(self.planning_checkpoint(), [])
        self.assertEqual(self.saved()["timing"]["failed_stage"], "initialize")
        self.tick()
        checkpoint = self.planning_checkpoint()
        self.config["recent_days"] = 8
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            db.execute(
                "CREATE TRIGGER reject_planning BEFORE INSERT ON scheduler_state "
                "WHEN NEW.name GLOB 'planning_success:*' BEGIN SELECT RAISE(ABORT,'fixture'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.tick(1)
        self.assertEqual(self.planning_checkpoint(), checkpoint)
        self.assertEqual(self.saved()["timing"]["failed_stage"], "planning_checkpoint")
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            db.execute("DROP TRIGGER reject_planning")
        self.assertEqual(self.tick()["status"], "planning_only")

    def test_legacy_zero_still_plans_each_acquire_and_tail_publish_is_unchanged(self):
        self.config["planning_interval_seconds"] = 0
        self.published()
        self.tick(1)
        self.tick(1)
        self.assertEqual(module.Pipeline.initialize.call_count, 2)
        self.assertEqual(module.Pipeline.plan_extended.call_count, 2)
        self.assertEqual(self.planning_checkpoint(), [])
        self.config["publish_interval_seconds"] = 0
        self.assertTrue(self.tick(1)["publication"]["performed"])
        self.assertEqual(module.Pipeline.initialize.call_count, 3)
        self.assertEqual(self.acquisitions, 3)

    def test_invalid_config_and_checkpoint_fail_closed(self):
        for value in (-1, True, 1.5, "900"):
            with self.subTest(value=value):
                self.config["planning_interval_seconds"] = value
                with self.assertRaises(ValueError):
                    self.tick()
        self.config["planning_interval_seconds"] = 900
        self.config["publish_interval_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "positive publication"):
            self.tick()
        self.config["publish_interval_seconds"] = 900
        self.published()
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            db.execute(
                "INSERT INTO scheduler_state VALUES('planning_success:broken',1)"
            )
        with self.assertRaisesRegex(ValueError, "Invalid planning checkpoint"):
            self.tick(1)
        self.assertEqual(self.acquisitions, 0)

    def test_discovery_arriving_between_rounds_is_planned_on_next_due_tick(self):
        from test_tushare_planning_progress import universe_planner

        self.config.update(
            enable_structured=True,
            structured_apis=["namechange"],
            history_start="20200101",
            plan_jobs_per_tick=500,
            publish_interval_seconds=10000,
        )
        ids = {"stocks": ["600100.SH"], "indexes": [], "etfs": []}
        self.published()
        with (
            patch.object(module.Pipeline, "plan_extended", REAL_PLAN),
            patch.object(module.Pipeline, "identifiers", side_effect=lambda: ids),
            patch.dict(module.PLANNERS, {"structured": universe_planner}, clear=True),
        ):
            self.tick(1)
            with sqlite3.connect(self.root / "pipeline.sqlite") as db:
                first = db.execute("SELECT id,job FROM jobs ORDER BY id").fetchall()
            ids["stocks"].append("600900.SH")
            self.tick(120)
            with sqlite3.connect(self.root / "pipeline.sqlite") as db:
                self.assertEqual(
                    db.execute("SELECT id,job FROM jobs ORDER BY id").fetchall(), first
                )
            self.assertEqual(self.tick(780)["status"], "planning_only")
            with sqlite3.connect(self.root / "pipeline.sqlite") as db:
                later = db.execute("SELECT id,job FROM jobs ORDER BY id").fetchall()
            self.assertTrue(set(first).issubset(later))
            self.assertTrue(
                any(
                    json.loads(job)["params"].get("ts_code") == "600900.SH"
                    for _, job in later
                )
            )

    def test_no_family_cursor_or_jobs_reset_on_defer_or_config_change(self):
        self.published()
        pipeline = module.Pipeline(self.root, {"entries": []})
        pipeline.enqueue("trade_cal", {"start_date": "19900101"}, 45, "old-history")
        pipeline.db.execute("INSERT INTO scheduler_state VALUES('fair_turn',17)")
        pipeline.db.execute(
            "INSERT INTO planning_state VALUES('history:old','2026-09-09','old-policy',9123,0)"
        )
        pipeline.db.commit()
        before = [tuple(row) for row in pipeline.db.execute("SELECT * FROM jobs")]
        pipeline.close()
        self.tick(1)
        self.tick(1)
        self.config["recent_days"] = 9
        self.tick(1)
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            self.assertEqual(db.execute("SELECT * FROM jobs").fetchall(), before)
            self.assertEqual(
                db.execute("SELECT * FROM planning_state").fetchall(),
                [("history:old", "2026-09-09", "old-policy", 9123, 0)],
            )
            self.assertEqual(
                db.execute(
                    "SELECT value FROM scheduler_state WHERE name='fair_turn'"
                ).fetchone()[0],
                17,
            )
        # Whole effective config is hashed, not persisted in the new status field.
        self.assertNotIn("config", self.saved()["planning_cadence"])
        json.dumps(self.saved())


if __name__ == "__main__":
    unittest.main()
