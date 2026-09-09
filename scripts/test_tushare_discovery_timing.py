"""Local immutable-body deduplication and failure-persistent planning diagnostics."""

from contextlib import ExitStack
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module
import test_tushare_tick_timing as tick_fixtures


class DiscoveryTiming(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)
        self.stack.enter_context(
            patch("socket.socket.connect", side_effect=AssertionError("offline"))
        )
        self.stack.enter_context(
            patch.object(
                module, "get_secret", side_effect=AssertionError("no credentials")
            )
        )
        self.n = 0
        self.p.planning_timing = {}

    def body(self, codes):
        data = module.json_bytes(
            {"data": {"fields": ["ts_code", "value"], "items": [[c, 1] for c in codes]}}
        )
        sha = hashlib.sha256(data).hexdigest()
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (sha + ".json")).write_bytes(data)
        return sha

    def result(self, api, sha, status="sample_ok", **extra):
        self.n += 1
        item = {
            "api_name": api,
            "object_sha256": sha,
            "status": status,
            "observation": f"{self.n:032x}.json",
            **extra,
        }
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (str(self.n), 1, json.dumps(item))
        )
        self.p.db.commit()

    def without_dedup(self):
        # Equivalent original traversal: every result reaches records(), keeping
        # the current family mapping (including parallel contract additions).
        with patch.object(
            module,
            "contract_for",
            return_value={"request_identity_fields": ["bypass_test"]},
        ):
            return self.p.identifiers()

    def test_duplicate_api_status_format_and_new_body_identity(self):
        sha = self.body(["600000.SH", "T600018.SH"])
        self.result("stock_basic", sha)
        self.result("stock_basic", sha)
        self.result("daily", sha)
        self.result("stock_basic", sha, "possibly_truncated")
        self.result("stock_basic", sha, "api_error")
        self.result("stock_basic", sha, response_format="non_json")
        self.result("stock_basic", self.body(["000001.SZ"]))
        expected = self.without_dedup()
        with patch.object(self.p, "records", wraps=self.p.records) as reads:
            actual = self.p.identifiers()
        self.assertEqual(module.json_bytes(actual), module.json_bytes(expected))
        self.assertEqual(reads.call_count, 6)
        self.assertEqual(
            self.p.identifier_timing,
            {"results": 7, "duplicate_bodies": 1, "bypassed": 0, "body_reads": 4},
        )
        self.assertIn("T600018.SH", actual["stocks"])

    def test_request_identity_bypassed_even_same_body_different_market(self):
        sha = self.body(["000001.SH"])
        self.result("stock_basic", sha, request_market="SH")
        self.result("stock_basic", sha, request_market="SZ")

        def records(saved, *, fields=None):
            return [{"ts_code": "000001." + saved["request_market"]}]

        with (
            patch.object(
                module,
                "contract_for",
                return_value={"request_identity_fields": ["market"]},
            ),
            patch.object(self.p, "records", side_effect=records) as reads,
        ):
            actual = self.p.identifiers()
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(actual["stocks"], ["000001.SH", "000001.SZ"])
        self.assertEqual(self.p.identifier_timing["bypassed"], 2)

    def test_no_cross_call_cache_and_old_history_retained(self):
        old = self.body(["T600018.SH"])
        self.result("stock_basic", old)
        self.p.identifiers()
        self.result("stock_basic", self.body(["600018.SH"]))
        with patch.object(self.p, "records", wraps=self.p.records) as reads:
            result = self.p.identifiers()
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(result["stocks"], ["600018.SH", "T600018.SH"])
        (self.root / "objects" / (old + ".json")).unlink()
        with self.assertRaises(FileNotFoundError):
            self.p.identifiers()

    def test_missing_duplicate_file_not_hidden_and_errors_do_not_require_body(self):
        sha = self.body(["600000.SH"])
        self.result("stock_basic", sha)
        self.result("stock_basic", sha)
        original = self.p.records

        def disappearing(saved, *, fields=None):
            rows = original(saved, fields=fields)
            (self.root / "objects" / (sha + ".json")).unlink()
            return rows

        with patch.object(self.p, "records", side_effect=disappearing):
            with self.assertRaises(FileNotFoundError):
                self.p.identifiers()
        self.p.db.execute("DELETE FROM attempts")
        self.result("stock_basic", "0" * 64, "permission_denied")
        self.assertEqual(self.p.identifiers()["stocks"], [])

    def test_duplicate_wide_body_readcount_benchmark(self):
        data = module.json_bytes(
            {
                "data": {
                    "fields": ["ts_code"] + [f"value{i}" for i in range(30)],
                    "items": [[f"{i:06d}.SZ"] + list(range(30)) for i in range(3000)],
                }
            }
        )
        sha = hashlib.sha256(data).hexdigest()
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (sha + ".json")).write_bytes(data)
        for _ in range(40):
            self.result("daily", sha)
        started = time.perf_counter()
        with patch.object(self.p, "records", wraps=self.p.records) as reads:
            expected = self.without_dedup()
        old_seconds, old_reads = time.perf_counter() - started, reads.call_count
        started = time.perf_counter()
        with patch.object(self.p, "records", wraps=self.p.records) as reads:
            actual = self.p.identifiers()
        new_seconds = time.perf_counter() - started
        self.assertEqual(module.json_bytes(expected), module.json_bytes(actual))
        self.assertEqual((old_reads, reads.call_count), (40, 1))
        print(
            json.dumps(
                {
                    "duplicate_results": 40,
                    "body_bytes": len(data),
                    "old_body_reads": old_reads,
                    "new_body_reads": reads.call_count,
                    "old_seconds": old_seconds,
                    "new_seconds": new_seconds,
                    "identifier_sha256": hashlib.sha256(
                        module.json_bytes(actual)
                    ).hexdigest(),
                }
            )
        )

    def test_failed_discovery_and_enqueue_keep_diagnostics(self):
        with patch.object(
            self.p, "identifiers", side_effect=RuntimeError("do not record error text")
        ):
            with self.assertRaises(RuntimeError):
                self.p.plan_extended({}, date(2026, 9, 9))
        self.assertEqual(self.p.planning_timing["failed_stage"], "identifiers")
        self.assertIn("identifiers", self.p.planning_timing["stage_seconds"])

        def planner(*args):
            yield {
                "api_name": "daily",
                "params": {"trade_date": "20260908"},
                "priority": 20,
                "epoch": "20260909",
            }

        with (
            patch.object(self.p, "identifiers", return_value={}),
            patch.dict(module.PLANNERS, {"structured": planner}, clear=True),
            patch.object(
                self.p, "enqueue", side_effect=RuntimeError("do not record error text")
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.p.plan_extended({"enable_structured": True}, date(2026, 9, 9))
        timing = self.p.planning_timing
        self.assertEqual(timing["failed_stage"], "recent:structured:enqueue")
        self.assertIn("enqueue_seconds", timing["families"]["recent:structured"])
        self.assertNotIn("do not record", json.dumps(timing))
        self.assertEqual(
            self.p.db.execute(
                "SELECT offset FROM planning_state WHERE name='recent:structured'"
            ).fetchone()[0],
            0,
        )

    def test_source_replay_counts_remain_absolute(self):
        def planner(*args):
            for i in range(6):
                yield {
                    "api_name": "daily",
                    "params": {"trade_date": f"2026090{i + 1}"},
                    "priority": 40,
                    "epoch": "history",
                }

        config = {"enable_structured": True, "plan_jobs_per_tick": 2}
        with (
            patch.object(self.p, "identifiers", return_value={}),
            patch.dict(module.PLANNERS, {"structured": planner}, clear=True),
        ):
            self.p.plan_extended(config, date(2026, 9, 9))
            before = dict(
                self.p.db.execute(
                    "SELECT * FROM planning_state WHERE name='history:structured'"
                ).fetchone()
            )
            stats = self.p.plan_extended(config, date(2026, 9, 9))
        after = dict(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:structured'"
            ).fetchone()
        )
        self.assertEqual(before["signature"], after["signature"])
        self.assertEqual(after["offset"], 4)
        timing = self.p.planning_timing["families"]["history:structured"]
        self.assertEqual((timing["initial_offset"], timing["source_items"]), (2, 2))
        self.assertEqual(stats["history:structured"]["new_jobs"], 2)
        self.assertLessEqual(
            timing["initial_next_seconds"], timing["source_next_seconds"]
        )
        self.assertIsNone(self.p.planning_timing["failed_stage"])

    def test_failed_initial_replay_preserves_checkpoint(self):
        def good(*args):
            for i in range(6):
                yield {
                    "api_name": "daily",
                    "params": {"trade_date": f"2026090{i + 1}"},
                    "priority": 40,
                    "epoch": "history",
                }

        def broken(*args):
            yield {
                "api_name": "daily",
                "params": {"trade_date": "20260901"},
                "priority": 40,
                "epoch": "history",
            }
            raise RuntimeError("replay failed")

        config = {"enable_structured": True, "plan_jobs_per_tick": 2}
        with (
            patch.object(self.p, "identifiers", return_value={}),
            patch.dict(module.PLANNERS, {"structured": good}, clear=True),
        ):
            self.p.plan_extended(config, date(2026, 9, 9))
        before = tuple(
            self.p.db.execute(
                "SELECT * FROM planning_state WHERE name='history:structured'"
            ).fetchone()
        )
        with (
            patch.object(self.p, "identifiers", return_value={}),
            patch.dict(module.PLANNERS, {"structured": broken}, clear=True),
        ):
            with self.assertRaises(RuntimeError):
                self.p.plan_extended(config, date(2026, 9, 9))
        self.assertEqual(
            before,
            tuple(
                self.p.db.execute(
                    "SELECT * FROM planning_state WHERE name='history:structured'"
                ).fetchone()
            ),
        )
        timing = self.p.planning_timing
        self.assertEqual(timing["failed_stage"], "history:structured:source_next")
        self.assertGreaterEqual(
            timing["families"]["history:structured"]["initial_next_seconds"], 0
        )
        self.assertEqual(timing["families"]["history:structured"]["source_items"], 0)

    def test_later_discovery_does_not_overwrite_planning_diagnostics(self):
        sha = self.body(["600000.SH"])
        self.result("stock_basic", sha)
        self.p.plan_extended({}, date(2026, 9, 9))
        captured = module.json_bytes(self.p.planning_timing)
        self.result("stock_basic", sha)
        self.p.identifiers()  # A later saturation split also calls this method.
        self.assertEqual(self.p.identifier_timing["results"], 2)
        self.assertEqual(module.json_bytes(self.p.planning_timing), captured)


class PersistedTiming(unittest.TestCase):
    setUp = tick_fixtures.TickTimingTest.setUp
    effect = tick_fixtures.TickTimingTest.effect
    saved = tick_fixtures.TickTimingTest.saved

    def test_tick_failure_persists_planning_attribute(self):
        self.failure = "planning"
        self.pipeline.planning_timing = {
            "failed_stage": "identifiers",
            "stage_seconds": {"identifiers": 2.5},
        }
        with self.assertRaises(RuntimeError):
            module.tick()
        self.assertEqual(
            self.saved()["timing"]["planning"], self.pipeline.planning_timing
        )
        self.assertEqual(self.saved()["timing"]["failed_stage"], "planning")


if __name__ == "__main__":
    unittest.main()
