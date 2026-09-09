"""Offline absolute planning offsets with bounded history-prefix skipping."""

from contextlib import ExitStack
from datetime import date
import hashlib
import itertools
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module

TODAY = date(2026, 9, 9)


class HistoryBudget(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(lambda: self.p.close())
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            self.stack.enter_context(
                patch(target, side_effect=AssertionError("offline only"))
            )
        self.ids = {"stocks": ["600000.SH"]}
        self.config = {
            "enable_structured": True,
            "structured_apis": ["namechange"],
            "history_start": "20200101",
            "plan_jobs_per_tick": 3,
            "history_plan_seconds": 5,
        }
        self.prefix, self.tail = 11, 14
        self.clock = None

    def planner(self, config, today, identifiers):
        for history, n in ((False, self.prefix), (True, self.tail)):
            for i in range(n):
                if self.clock is not None:
                    self.clock[0] += 0.02
                yield {
                    "api_name": "daily",
                    "params": {
                        "n": i,
                        "slice": "history" if history else "recent",
                        "codes": len(identifiers.get("stocks", [])),
                    },
                    "priority": 45 if history else 20,
                    "epoch": "history" if history else config["planning_epoch"],
                }

    def install_state(
        self, family="structured", offset=0, recent_offset=None, recent_done=True
    ):
        policy, ids = module._planning_inputs(family, self.config, self.ids)
        for mode in ("recent", "history"):
            signature = module.json_bytes(
                {
                    "version": 1,
                    "policy": policy,
                    "identifiers": ids,
                    "refresh": "history" if mode == "history" else "20260909",
                    "epoch": "20260909",
                }
            ).decode()
            self.p.db.execute(
                "INSERT OR REPLACE INTO planning_state VALUES(?,?,?,?,?)",
                (
                    mode + ":" + family,
                    "20260909",
                    signature,
                    offset
                    if mode == "history"
                    else (self.prefix if recent_offset is None else recent_offset),
                    int(recent_done) if mode == "recent" else 0,
                ),
            )
        self.p.db.commit()

    def state(self, name="history:structured"):
        return dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name=?", (name,)
            ).fetchone()
        )

    def tick(self):
        with (
            patch.object(self.p, "identifiers", return_value=self.ids),
            patch.dict(module.PLANNERS, {"structured": self.planner}, clear=True),
        ):
            return self.p.plan_extended(self.config, TODAY)

    def historical_params(self):
        return [
            json.loads(r[0])["params"]
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE epoch='history' ORDER BY rowid"
            )
        ]

    def test_nonzero_offsets_keep_full_stream_identity_and_signature(self):
        for offset in (0, 3, self.prefix - 1, self.prefix, self.prefix + 4):
            with self.subTest(offset=offset):
                self.p.db.execute("DELETE FROM jobs")
                self.install_state(offset=offset)
                before = self.state()
                recent = self.state("recent:structured")
                report = self.tick()["history:structured"]
                wanted = list(
                    itertools.islice(
                        (
                            j["params"]
                            for j in itertools.islice(
                                self.planner(
                                    {"planning_epoch": "20260909"}, TODAY, self.ids
                                ),
                                offset,
                                None,
                            )
                            if j["epoch"] == "history"
                        ),
                        3,
                    )
                )
                self.assertEqual(self.historical_params(), wanted)
                self.assertEqual(self.state()["offset"], max(self.prefix, offset) + 3)
                self.assertEqual(self.state()["signature"], before["signature"])
                self.assertEqual(self.state("recent:structured"), recent)
                self.assertEqual(report["skipped_recent"], max(0, self.prefix - offset))
                self.assertEqual(report["stop_reason"], "job_budget")

    def test_scan_limit_and_budget_saturation_resume_without_drops(self):
        self.config["history_plan_scan_limit"] = 4
        self.install_state(offset=3)
        first = self.tick()["history:structured"]
        self.assertEqual(first["planned"], 4)
        self.assertEqual(first["stop_reason"], "scan_limit")
        self.assertEqual(self.state()["offset"], 7)
        for _ in range(20):
            self.tick()
            if self.state()["done"]:
                break
        self.assertTrue(self.state()["done"])
        self.assertEqual(
            [p["n"] for p in self.historical_params()], list(range(self.tail))
        )
        self.assertEqual(self.state()["offset"], self.prefix + self.tail)
        self.assertEqual(self.tick(), {})

    def test_time_bound_checkpoints_consumed_prefix_and_resume(self):
        self.config["history_plan_seconds"] = 0.05
        self.install_state()
        self.clock = [0.0]
        with patch.object(module.time, "monotonic", side_effect=lambda: self.clock[0]):
            report = self.tick()["history:structured"]
        self.assertEqual(report["stop_reason"], "time_limit")
        self.assertEqual(report["planned"], 3)
        self.assertEqual(self.state()["offset"], 3)
        self.assertEqual(report["new_jobs"], 0)
        self.clock = None
        self.config["history_plan_seconds"] = 5
        self.tick()
        self.assertEqual([p["n"] for p in self.historical_params()], [0, 1, 2])

    def test_existing_jobs_and_failed_commit_resume_preserve_rows(self):
        self.install_state()
        original = next(
            j
            for j in self.planner({"planning_epoch": "20260909"}, TODAY, self.ids)
            if j["epoch"] == "history"
        )
        self.p.enqueue(
            original["api_name"],
            original["params"],
            original["priority"],
            original["epoch"],
        )
        self.p.db.execute("UPDATE jobs SET state='empty',tries=3,result='saved-result'")
        self.p.db.commit()
        before = tuple(self.p.db.execute("SELECT * FROM jobs").fetchone())
        state = self.state()
        # Enqueues and absolute checkpoint must roll back together on close.
        self.p.db.set_authorizer(
            lambda action, name, *args: (
                module.sqlite3.SQLITE_DENY
                if action == module.sqlite3.SQLITE_TRANSACTION and name == "COMMIT"
                else module.sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(module.sqlite3.DatabaseError):
            self.tick()
        self.p.db.set_authorizer(None)
        self.p.close()
        self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(self.state(), state)
        self.assertEqual(
            tuple(self.p.db.execute("SELECT * FROM jobs").fetchone()), before
        )
        stats = self.tick()["history:structured"]
        self.assertEqual(stats["existing_jobs"], 1)
        self.assertEqual(stats["new_jobs"], 2)
        self.assertEqual(
            tuple(
                self.p.db.execute(
                    "SELECT * FROM jobs WHERE id=?", (before[0],)
                ).fetchone()
            ),
            before,
        )

    def test_discovery_growth_does_not_redefine_old_cursor(self):
        self.install_state(offset=4)
        before = self.state()
        self.ids["stocks"].append("T600018.SH")
        result = self.tick()["history:structured"]
        self.assertTrue(result["discovery_refresh_pending"])
        self.assertEqual(self.state()["signature"], before["signature"])
        self.assertTrue(
            all(params["codes"] == 1 for params in self.historical_params())
        )

    def test_empty_history_and_recent_budget_remain_bounded(self):
        self.tail = 0
        self.install_state(recent_offset=0, recent_done=False)
        stats = self.tick()
        self.assertEqual(stats["recent:structured"]["planned"], 3)
        self.assertEqual(stats["recent:structured"]["new_jobs"], 3)
        self.assertEqual(stats["history:structured"]["planned"], self.prefix)
        self.assertTrue(stats["history:structured"]["done"])
        self.assertEqual(self.historical_params(), [])

    def test_default_configuration_and_limit_validation(self):
        self.config.pop("history_plan_seconds")
        self.install_state()
        self.assertEqual(self.tick()["history:structured"]["new_jobs"], 3)
        before = self.state()
        for key, value in [
            ("history_plan_scan_limit", 0),
            ("history_plan_scan_limit", True),
            ("history_plan_scan_limit", 100001),
            ("history_plan_seconds", 0),
            ("history_plan_seconds", float("nan")),
            ("history_plan_seconds", True),
            ("history_plan_seconds", 6),
        ]:
            with self.subTest(key=key, value=value):
                cfg = self.config.copy()
                self.config[key] = value
                with self.assertRaises(ValueError):
                    self.tick()
                self.assertEqual(self.state(), before)
                self.config = cfg

    def test_real_6194_code_prefix_skipped_in_one_bounded_batch(self):
        self.ids = {
            "technical_stocks": [f"{i:06d}.SH" for i in range(6193)] + ["T600018.SH"]
        }
        self.config = {
            "enable_technical_extra": True,
            "technical_extra_apis": [
                "stk_factor",
                "stk_factor_pro",
                "cyq_perf",
                "cyq_chips",
                "bak_daily",
            ],
            "history_start": "19900101",
            "plan_jobs_per_tick": 500,
            "history_plan_seconds": 5,
        }
        prefix = 7 * 6194 * 2 + 21
        self.install_state("technical_extra", offset=4000, recent_offset=prefix)
        before = self.state("history:technical_extra")
        started = time.perf_counter()
        with patch.object(self.p, "identifiers", return_value=self.ids):
            stats = self.p.plan_extended(self.config, TODAY)["history:technical_extra"]
        elapsed = time.perf_counter() - started
        self.assertEqual(stats["new_jobs"], 500)
        self.assertEqual(stats["skipped_recent"], prefix - 4000)
        self.assertEqual(self.state("history:technical_extra")["offset"], prefix + 500)
        self.assertEqual(
            self.state("history:technical_extra")["signature"], before["signature"]
        )
        real = module.PLANNERS["technical_extra"](self.config, TODAY, self.ids)
        expected = list(
            itertools.islice((j for j in real if j["epoch"] == "history"), 500)
        )
        actual = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT job FROM jobs WHERE epoch='history' ORDER BY rowid"
            )
        ]
        self.assertEqual(
            [(j["api_name"], j["params"]) for j in actual],
            [(j["api_name"], j["params"]) for j in expected],
        )
        sha = hashlib.sha256(
            module.json_bytes([(j["api_name"], j["params"]) for j in actual])
        ).hexdigest()
        print(
            json.dumps(
                {
                    "technical_prefix": prefix,
                    "old_offset": 4000,
                    "new_offset": prefix + 500,
                    "new_history": 500,
                    "seconds": elapsed,
                    "api_params_sha256": sha,
                }
            )
        )

    def test_missing_technical_discovery_does_not_invent_chip_jobs(self):
        self.ids = {}
        self.config = {
            "enable_technical_extra": True,
            "technical_extra_apis": ["cyq_perf", "cyq_chips"],
            "history_start": "19900101",
            "plan_jobs_per_tick": 500,
        }
        with patch.object(self.p, "identifiers", return_value=self.ids):
            stats = self.p.plan_extended(self.config, TODAY)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
        )
        self.assertTrue(stats["history:technical_extra"]["done"])
        reasons = [
            json.loads(r[0])
            for r in self.p.db.execute(
                "SELECT reason FROM capability WHERE scope LIKE 'planning:technical_extra:%'"
            )
        ]
        self.assertTrue(
            any("awaiting_stored_stocks" in json.dumps(reason) for reason in reasons)
        )


if __name__ == "__main__":
    unittest.main()
