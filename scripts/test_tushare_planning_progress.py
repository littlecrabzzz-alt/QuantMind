#!/usr/bin/env python3
"""Offline regression for family signatures and finite discovery snapshots."""

from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module  # noqa: E402

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


def universe_planner(config, anchor, identifiers):
    for code in sorted(identifiers.get("stocks", [])):
        yield {
            "api_name": "daily",
            "params": {
                "ts_code": code,
                "trade_date": (anchor - timedelta(days=1)).strftime("%Y%m%d"),
            },
            "priority": 20,
            "epoch": config["planning_epoch"],
        }
    for code in sorted(identifiers.get("stocks", [])):
        for day in ("20200101", "20200102", "20200103"):
            yield {
                "api_name": "daily",
                "params": {"ts_code": code, "trade_date": day},
                "priority": 40,
                "epoch": "history",
            }


class PlanningProgress(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(lambda: self.p.close())
        self.ids = {
            "stocks": ["600100.SH", "600900.SH"],
            "indexes": ["000001.SH"],
            "etfs": ["510300.SH"],
        }
        self.config = {
            "enable_structured": True,
            "structured_apis": ["namechange"],
            "history_start": "20200101",
            "plan_jobs_per_tick": 2,
        }
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("Offline boundary"))
            guard.start()
            self.addCleanup(guard.stop)

    def tick(self, today=date(2026, 9, 9), config=None):
        with (
            patch.object(self.p, "identifiers", return_value=deepcopy(self.ids)),
            patch.dict(module.PLANNERS, {"structured": universe_planner}, clear=True),
        ):
            return self.p.plan_extended(config or self.config, today)

    def state(self, name="history:structured"):
        return dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", (name,)
            ).fetchone()
        )

    def jobs(self):
        return [
            (json.loads(r[0])["params"], r[1], r[2])
            for r in self.p.db.execute("SELECT job,epoch,state FROM jobs")
        ]

    def test_unrelated_family_contract_config_and_discovery_do_not_reset(self):
        self.tick()
        old = self.state()
        changed = {
            **self.config,
            "etf_basket_apis": ["etf_sz_cons"],
            "etf_basket_history_start": "19900101",
            "text_history_window": "month",
        }
        self.ids["etfs"].append("159915.SZ")
        self.ids["options"] = ["10000001.SH"]
        with patch.dict(
            module.EXTENDED_CONTRACTS,
            {"new_pcf": {"group": "etf_basket", "dependencies": ["etfs"]}},
        ):
            self.tick(config=changed)
        current = self.state()
        self.assertEqual(current["signature"], old["signature"])
        self.assertGreater(current["offset"], old["offset"])
        stored = json.loads(current["signature"])
        self.assertEqual(set(stored["identifiers"]), {"stocks"})
        self.assertNotIn("contracts", stored)
        self.assertNotIn("config", stored)

    def test_only_selected_contract_changes_invalidate(self):
        self.tick()
        old = self.state()
        with patch.dict(
            module.EXTENDED_CONTRACTS,
            {"daily": {**module.EXTENDED_CONTRACTS["daily"], "row_cap": 1}},
        ):
            self.tick()
        self.assertEqual(self.state()["signature"], old["signature"])
        with patch.dict(
            module.EXTENDED_CONTRACTS,
            {"namechange": {**module.EXTENDED_CONTRACTS["namechange"], "row_cap": 1}},
        ):
            stats = self.tick()
        self.assertNotEqual(self.state()["signature"], old["signature"])
        self.assertEqual(
            stats["history:structured"]["reset_reason"], "policy_or_legacy_change"
        )

    def test_growing_universe_cannot_starve_original_tail_or_new_history(self):
        original = set(self.ids["stocks"])
        self.tick()
        signature = self.state()["signature"]
        for number in range(5):
            self.ids["stocks"].append(f"00000{number}.SZ")
            self.tick()
            if not self.state()["done"]:
                self.assertEqual(self.state()["signature"], signature)
            else:
                break
        old_history = {
            p["ts_code"]
            for p, epoch, _ in self.jobs()
            if epoch == "history" and p["trade_date"] == "20200103"
        }
        self.assertLessEqual(original, old_history)
        self.assertTrue(self.state()["done"])
        for _ in range(100):
            self.tick()
        for code in self.ids["stocks"]:
            history = {
                p["trade_date"]
                for p, epoch, _ in self.jobs()
                if epoch == "history" and p["ts_code"] == code
            }
            self.assertEqual(history, {"20200101", "20200102", "20200103"})
            self.assertTrue(
                any(
                    p["ts_code"] == code and epoch != "history"
                    for p, epoch, _ in self.jobs()
                )
            )
        self.assertTrue(self.state()["done"])
        count = len(self.jobs())
        self.assertEqual(self.tick(), {})
        self.assertEqual(len(self.jobs()), count)

    def test_recent_snapshot_progresses_during_growth_before_history_finishes(self):
        self.config["plan_jobs_per_tick"] = 1
        self.tick()
        signature = self.state("recent:structured")["signature"]
        self.ids["stocks"].append("000001.SZ")
        self.tick()
        self.assertEqual(self.state("recent:structured")["signature"], signature)
        self.tick()  # Mark the finite two-code recent scan complete.
        self.assertTrue(self.state("recent:structured")["done"])
        self.assertFalse(self.state()["done"])
        self.tick()  # Next recent scan captures the new code, independent of history.
        self.assertTrue(
            any(
                p["ts_code"] == "000001.SZ" and epoch != "history"
                for p, epoch, _ in self.jobs()
            )
        )
        self.assertFalse(self.state()["done"])

    def test_unfinished_recent_and_history_keep_date_anchor_across_year(self):
        self.config["plan_jobs_per_tick"] = 1
        self.tick(date(2026, 12, 31))
        before = {
            mode: self.state(mode + ":structured") for mode in ("recent", "history")
        }
        self.tick(date(2027, 1, 9))
        for mode in before:
            state = self.state(mode + ":structured")
            self.assertEqual(state["anchor"], "20261231")
            self.assertEqual(state["signature"], before[mode]["signature"])
            self.assertGreater(state["offset"], before[mode]["offset"])
        self.assertFalse(any(p["trade_date"] == "20270108" for p, _, _ in self.jobs()))

    def test_recent_catchup_windows_do_not_skip_dates_after_long_sweep(self):
        config = {
            "enable_structured": True,
            "structured_apis": ["daily"],
            "history_start": "20260801",
            "plan_jobs_per_tick": 2,
        }
        with patch.object(self.p, "identifiers", return_value={}):
            self.p.plan_extended(config, date(2026, 9, 1))
            for _ in range(30):
                self.p.plan_extended(config, date(2026, 9, 20))
        recent_days = {
            p["trade_date"] for p, epoch, _ in self.jobs() if epoch != "history"
        }
        required = {
            (date(2026, 8, 25) + timedelta(days=n)).strftime("%Y%m%d")
            for n in range(26)
        }
        self.assertLessEqual(required, recent_days)
        self.assertEqual(self.state("recent:structured")["anchor"], "20260920")
        self.assertTrue(self.state("recent:structured")["done"])

    def test_restart_preserves_snapshot_and_pending_discovery(self):
        self.tick()
        before = self.state()
        self.p.close()
        self.p = module.Pipeline(self.root, CATALOG)
        self.ids["stocks"].append("000001.SZ")
        stats = self.tick()
        self.assertEqual(self.state()["signature"], before["signature"])
        self.assertEqual(self.state()["offset"], before["offset"] + 2)
        self.assertTrue(stats["history:structured"]["discovery_refresh_pending"])

    def test_true_config_change_replans_without_requeueing_done_jobs(self):
        for _ in range(10):
            self.tick()
        self.p.db.execute("UPDATE jobs SET state='done'")
        self.p.db.commit()
        before = len(self.jobs())
        config = {**self.config, "history_start": "20190101"}
        stats = self.tick(config=config)
        self.assertEqual(stats["recent:structured"]["new_jobs"], 0)
        self.assertEqual(stats["recent:structured"]["existing_jobs"], 2)
        self.assertEqual(len(self.jobs()), before)
        self.assertTrue(all(state == "done" for _, _, state in self.jobs()))

    def test_legacy_scalar_signature_safely_replays_once(self):
        self.p.db.execute(
            "INSERT INTO planning_state VALUES(?,?,?,?,?)",
            ("history:structured", "20250101", "0" * 64, 9000, 1),
        )
        self.p.db.commit()
        self.tick()
        first = self.state()
        self.assertEqual(first["offset"], 2)
        self.assertEqual(json.loads(first["signature"])["version"], 1)
        self.tick()
        self.assertEqual(self.state()["signature"], first["signature"])
        self.assertEqual(self.state()["offset"], 4)

    def test_actual_declared_and_implicit_dependencies(self):
        expected = [
            ("structured", ["namechange"], {"stocks"}),
            ("structured", ["index_daily"], {"indexes"}),
            ("market", ["fund_nav", "index_member_all"], {"funds", "sw_l3"}),
            ("credit_extra", ["pledge_stat"], {"stocks"}),
            ("etf_basket", ["etf_sh_cons"], {"etfs"}),
            ("text", ["news"], set()),
            ("other", ["opt_daily"], set()),
        ]
        for family, apis, dependencies in expected:
            with self.subTest(family=family):
                _, ids = module._planning_inputs(
                    family,
                    {family + "_apis": apis, "history_start": "20200101"},
                    self.ids,
                )
                self.assertEqual(set(ids), dependencies)


if __name__ == "__main__":
    unittest.main()
