"""Isolated v5 queue indexes: migration, semantics and 400k-pending evidence."""

from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module

INDEXES = ("jobs_ready_group", "jobs_ready_order", "jobs_unexpanded")
SELECT = """SELECT j.* FROM jobs j INDEXED BY {index} LEFT JOIN request_gates g
ON g.scope='api:' || json_extract(j.job,'$.api_name')
WHERE j.state='pending' AND j.retry_after<=? AND COALESCE(g.next_at,0)<=?
{group} ORDER BY j.priority,j.rowid LIMIT 1"""
EXPAND = "SELECT * FROM jobs INDEXED BY {index} WHERE expanded=0 AND state IN ('done','quality','empty')"


class QueueIndexTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(lambda: self.p.close())
        self.stack.enter_context(
            patch("socket.socket.connect", side_effect=AssertionError("no network"))
        )
        self.stack.enter_context(
            patch.object(module, "get_secret", side_effect=AssertionError("no secrets"))
        )

    def seed(self, n=30, done=10):
        apis = ("ci_daily", "news", "daily")
        groups = ("rrg", "text", "structured")

        def rows():
            for i in range(n + done):
                yield (
                    str(i),
                    str(i),
                    "history",
                    json.dumps({"api_name": apis[i % 3], "params": {}}),
                    (i // 3) % 4 * 10,
                    "pending" if i < n else "done",
                    i % 7,
                    0 if i < n or i >= n + done - 3 else 1,
                    groups[i % 3],
                    json.dumps({"api_name": apis[i % 3]}),
                )

        self.p.db.executemany(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,retry_after,expanded,group_name,result) VALUES(?,?,?,?,?,?,?,?,?,?)",
            rows(),
        )
        self.p.db.commit()

    def to_v4(self):
        self.p.db.executescript(
            ";".join("DROP INDEX " + name for name in INDEXES)
            + "; PRAGMA user_version=4;"
        )
        self.p.close()

    def test_v4_migration_preserves_rows_and_restart_is_idempotent(self):
        self.seed()
        before = list(
            map(tuple, self.p.db.execute("SELECT rowid,* FROM jobs ORDER BY rowid"))
        )
        self.to_v4()
        self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(self.p.db.execute("PRAGMA user_version").fetchone()[0], 6)
        self.assertEqual(
            before,
            list(
                map(tuple, self.p.db.execute("SELECT rowid,* FROM jobs ORDER BY rowid"))
            ),
        )
        schema = self.p.db.execute("PRAGMA schema_version").fetchone()[0]
        self.p.close()
        self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(
            self.p.db.execute("PRAGMA schema_version").fetchone()[0], schema
        )
        self.assertEqual(
            before,
            list(
                map(tuple, self.p.db.execute("SELECT rowid,* FROM jobs ORDER BY rowid"))
            ),
        )

    def test_failed_index_creation_rolls_back_and_can_retry(self):
        self.seed()
        self.to_v4()
        connect = sqlite3.connect

        def deny_second(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_authorizer(
                lambda action, arg1, *rest: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_CREATE_INDEX
                    and arg1 == "jobs_ready_order"
                    else sqlite3.SQLITE_OK
                )
            )
            return db

        with patch.object(module.sqlite3, "connect", side_effect=deny_second):
            with self.assertRaises(sqlite3.DatabaseError):
                module.Pipeline(self.root, {"entries": []})
        with connect(self.root / "pipeline.sqlite") as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name IN (?,?,?)", INDEXES
                ).fetchall(),
                [],
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 40)
        self.p = module.Pipeline(self.root, {"entries": []})

    def test_weighted_selection_matches_old_query_and_survives_reopen(self):
        self.seed(60, 0)
        config = {
            "requests_per_minute": 240,
            "enable_text": True,
            "enable_structured": True,
            "group_weights": {"rrg": 2},
            "api_min_interval_seconds": {"ci_daily": 5},
        }
        groups = ["rrg", "rrg", "text", "structured"]
        with (
            patch.object(module.time, "time", return_value=1000),
            patch.object(module.time, "monotonic", return_value=0),
        ):
            for turn in range(12):
                self.p.db.execute("DELETE FROM request_gates")
                # Keep a blocked API and a future retry in front of eligible rows.
                self.p.db.execute("INSERT INTO request_gates VALUES('api:news',2000)")
                self.p.db.execute("UPDATE jobs SET retry_after=2000 WHERE id='0'")
                expected = self.p.db.execute(
                    SELECT.format(
                        index="jobs_group_pending", group="AND j.group_name=?"
                    ),
                    (1000, 1000, groups[turn % 4]),
                ).fetchone()
                if expected is None:
                    expected = self.p.db.execute(
                        SELECT.format(index="jobs_pending", group=""), (1000, 1000)
                    ).fetchone()
                row = self.p.next_job(config, 1)
                self.assertEqual(row["id"], expected["id"])
                api = json.loads(row["job"])["api_name"]
                gates = dict(self.p.db.execute("SELECT * FROM request_gates"))
                self.assertEqual(gates["account"], 1000.25)
                self.assertGreaterEqual(
                    gates["api:" + api], 1000 + (5 if api == "ci_daily" else 0.3)
                )
                self.p.db.execute(
                    "UPDATE jobs SET state='done' WHERE id=?", (row["id"],)
                )
                self.p.db.commit()
                self.p.close()
                self.p = module.Pipeline(self.root, {"entries": []})
                self.assertEqual(self.p._fair_turn, turn + 1)
            self.assertIsNone(self.p.next_job(config, 0.1))

    def test_expand_visits_same_rows_order_and_marks_only_eligible(self):
        self.seed(30, 10)
        expected = [
            r["id"]
            for r in self.p.db.execute(EXPAND.format(index="jobs_group_pending"))
        ]
        actual = [
            r["id"] for r in self.p.db.execute(EXPAND.format(index="jobs_unexpanded"))
        ]
        self.assertEqual(actual, expected)
        self.p.expand({})
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE state='pending' AND expanded=0"
            ).fetchone()[0],
            30,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE state='done' AND expanded=0"
            ).fetchone()[0],
            0,
        )
        self.p.expand({})

    def test_400k_pending_query_plans_and_bounded_vm_work(self):
        self.seed(400000, 100000)
        report = {"rows": 500000, "pending": 400000, "queries": {}}
        for name, before, after, params in (
            (
                "group",
                SELECT.format(index="jobs_group_pending", group="AND j.group_name=?"),
                SELECT.format(index="jobs_ready_group", group="AND j.group_name=?"),
                (1000, 1000, "rrg"),
            ),
            (
                "fallback",
                SELECT.format(index="jobs_pending", group=""),
                SELECT.format(index="jobs_ready_order", group=""),
                (1000, 1000),
            ),
            (
                "expand",
                EXPAND.format(index="jobs_group_pending"),
                EXPAND.format(index="jobs_unexpanded"),
                (),
            ),
        ):
            samples = {}
            for kind, sql in [("before", before), ("after", after)]:
                vm = [0]

                def progress(counter=vm):
                    counter[0] += 1
                    return 0

                self.p.db.set_progress_handler(progress, 100)
                times = []
                for _ in range(3):
                    started = time.perf_counter()
                    rows = [tuple(r) for r in self.p.db.execute(sql, params)]
                    times.append(time.perf_counter() - started)
                self.p.db.set_progress_handler(None, 0)
                plan = [
                    r[3] for r in self.p.db.execute("EXPLAIN QUERY PLAN " + sql, params)
                ]
                samples[kind] = {
                    "p50_ms": statistics.median(times) * 1000,
                    "vm_steps_lower_bound": vm[0] * 100,
                    "plan": plan,
                }
                if kind == "before":
                    baseline = rows
                else:
                    self.assertEqual(rows, baseline)
                    self.assertFalse(any("TEMP B-TREE" in p for p in plan))
            self.assertGreater(samples["before"]["vm_steps_lower_bound"], 10000)
            self.assertLess(samples["after"]["vm_steps_lower_bound"], 1000)
            report["queries"][name] = samples
        print("\nqueue_index_benchmark=" + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
