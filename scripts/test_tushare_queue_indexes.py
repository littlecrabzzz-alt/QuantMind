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
        self.assertEqual(self.p.db.execute("PRAGMA schema_version").fetchone()[0], schema)
        self.assertEqual(before, [tuple(r) for r in self.p.db.execute("SELECT rowid,* FROM jobs ORDER BY rowid")])

    def test_discovery_seeks_preserve_historical_results_without_pending_scan(self):
        self.seed(50000, 60)
        self.p.db.execute("UPDATE jobs SET result=NULL WHERE state='pending'")
        self.p.db.executemany("INSERT INTO attempts VALUES(?,?,?)", [
            ('old', 1, json.dumps({'api_name': 'daily', 'old_version': 1})),
            ('old', 2, json.dumps({'api_name': 'daily', 'old_version': 2})),
        ])
        self.p.db.commit()
        sql = """SELECT result FROM jobs {hint} WHERE result IS NOT NULL
            AND json_extract(job,'$.api_name') IN (?) UNION SELECT result
            FROM attempts {hint} WHERE json_extract(result,'$.api_name') IN (?)"""
        results, steps = [], []
        for hint in ('NOT INDEXED', ''):
            counter = [0]
            def progress():
                counter[0] += 1
                return 0
            self.p.db.set_progress_handler(progress, 100)
            results.append([r[0] for r in self.p.db.execute(sql.format(hint=hint), ('daily', 'daily'))])
            self.p.db.set_progress_handler(None, 0)
            steps.append(counter[0])
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[1]), 3)  # Current result and both old attempts.
        self.assertLess(steps[1], steps[0] / 10)
        plan = ' '.join(r[3] for r in self.p.db.execute(
            'EXPLAIN QUERY PLAN ' + sql.format(hint=''), ('daily', 'daily')))
        self.assertIn('USING INDEX jobs_discovery_api', plan)
        self.assertIn('USING INDEX attempts_discovery_api', plan)

    def test_failed_discovery_index_migration_rolls_back_then_preserves_rows(self):
        self.seed()
        before = [tuple(r) for r in self.p.db.execute('SELECT rowid,* FROM jobs ORDER BY rowid')]
        self.p.db.executescript('DROP INDEX jobs_discovery_api; DROP INDEX attempts_discovery_api; PRAGMA user_version=6;')
        self.p.close()
        connect = sqlite3.connect
        def deny_second(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_authorizer(lambda action, name, *rest: sqlite3.SQLITE_DENY
                              if action == sqlite3.SQLITE_CREATE_INDEX and name == 'attempts_discovery_api'
                              else sqlite3.SQLITE_OK)
            return db
        with patch.object(module.sqlite3, 'connect', side_effect=deny_second):
            with self.assertRaises(sqlite3.DatabaseError):
                module.Pipeline(self.root, {'entries': []})
        with connect(self.root / 'pipeline.sqlite') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name IN ('jobs_discovery_api','attempts_discovery_api')").fetchall(), [])
        self.p = module.Pipeline(self.root, {'entries': []})
        self.assertEqual(self.p.db.execute('PRAGMA user_version').fetchone()[0], 6)
        self.assertEqual(before, [tuple(r) for r in self.p.db.execute('SELECT rowid,* FROM jobs ORDER BY rowid')])
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

    def test_recent_planning_reuses_open_request_but_history_is_independent(self):
        params = {"trade_date": "20260910"}
        first = self.p.enqueue(
            "daily", params, 1, "20260911", reuse_recent_open=True
        )
        repeated = self.p.enqueue(
            "daily", params, 1, "20260912", reuse_recent_open=True
        )
        history = self.p.enqueue(
            "daily", params, 1, "history", reuse_recent_open=True
        )
        split_child = self.p.enqueue("daily", params, 1, "20260912")
        self.assertEqual(repeated, first)
        self.assertNotEqual(history, first)
        self.assertNotEqual(split_child, first)
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM jobs WHERE logical_key=("
                "SELECT logical_key FROM jobs WHERE id=?)",
                (first,),
            ).fetchone()[0],
            3,
        )

    def test_compaction_supersedes_only_stale_recent_root_tree(self):
        params = {"trade_date": "20260910"}
        old = self.p.enqueue("daily", params, 1, "20260911")
        children = [
            self.p.enqueue(
                "daily", {**params, "ts_code": code}, 2, "20260911"
            )
            for code in ("000001.SZ", "600000.SH")
        ]
        self.p.record_partition(
            old,
            children,
            "identifier_fanout",
            False,
            {"origin": "test", "universe_complete": False},
        )
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (old,)
        )
        retained_parent = self.p.enqueue(
            "daily", {"trade_date": "20260909"}, 1, "20260911"
        )
        self.p.record_partition(
            retained_parent,
            [children[0]],
            "identifier_fanout",
            False,
            {"origin": "shared-test", "universe_complete": False},
        )
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (retained_parent,)
        )
        newest = self.p.enqueue("daily", params, 1, "20260912")
        history = self.p.enqueue("daily", params, 1, "history")
        self.p.db.commit()

        report = self.p.compact_stale_recent_roots("20260912")
        self.assertEqual(
            report,
            {
                "status": "compacted",
                "epoch": "20260912",
                "stale_roots": 1,
                "stale_duplicate_jobs": 1,
                "superseded_open_jobs": 2,
                "protected_shared_jobs": 1,
            },
        )
        states = dict(
            self.p.db.execute(
                "SELECT id,state FROM jobs WHERE id IN (?,?,?,?,?)",
                (old, *children, newest, history),
            )
        )
        self.assertEqual(states[old], "superseded")
        self.assertEqual(states[children[0]], "pending")
        self.assertEqual(states[children[1]], "superseded")
        self.assertEqual(states[newest], "pending")
        self.assertEqual(states[history], "pending")
        closure = self.p.partition_inventory()["splits"]
        self.assertEqual(len(closure), 1)
        self.assertEqual(closure[0]["parent_id"], retained_parent)
        self.assertEqual(closure[0]["children"], [children[0]])
        self.assertEqual(
            self.p.compact_stale_recent_roots("20260912"),
            {"status": "already_compacted", "epoch": "20260912"},
        )

    def test_compaction_removes_duplicate_child_of_terminal_parent(self):
        params = {"trade_date": "20260910"}
        old_parent = self.p.enqueue("daily", params, 1, "20260911")
        old_child = self.p.enqueue(
            "daily", {**params, "ts_code": "000001.SZ"}, 2, "20260911"
        )
        self.p.record_partition(
            old_parent,
            [old_child],
            "identifier_fanout",
            False,
            {"origin": "old"},
        )
        self.p.db.execute(
            "UPDATE jobs SET state='blocked' WHERE id=?", (old_parent,)
        )
        new_parent = self.p.enqueue("daily", params, 1, "20260912")
        new_child = self.p.enqueue(
            "daily", {**params, "ts_code": "000001.SZ"}, 2, "20260912"
        )
        self.p.record_partition(
            new_parent,
            [new_child],
            "identifier_fanout",
            False,
            {"origin": "new"},
        )
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (new_parent,)
        )
        self.p.db.commit()

        report = self.p.compact_stale_recent_roots("20260912")
        self.assertEqual(report["stale_roots"], 0)
        self.assertEqual(report["stale_duplicate_jobs"], 1)
        self.assertEqual(report["superseded_open_jobs"], 1)
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (old_child,)
            ).fetchone()[0],
            "superseded",
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT state FROM jobs WHERE id=?", (new_child,)
            ).fetchone()[0],
            "pending",
        )

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

    def test_reviewed_fast_lane_is_bounded_round_robin_and_persisted(self):
        for api in ("top10_holders", "top10_floatholders"):
            for code in ("000001.SZ", "000002.SZ", "000003.SZ"):
                self.p.enqueue(
                    api,
                    {
                        "ts_code": code,
                        "start_date": "20250101",
                        "end_date": "20251231",
                    },
                    20,
                    "20260917",
                )
        for day in ("20260915", "20260916", "20260917"):
            self.p.enqueue("daily", {"trade_date": day}, 1, "20260917")
        self.p.db.commit()
        config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
            "enable_equity_event": True,
            "group_weights": {"rrg": 2, "equity_event": 1},
            "throughput_fast_lane_apis": [
                "top10_holders",
                "top10_floatholders",
            ],
            "throughput_fast_lane_every": 2,
        }
        selected = []
        with (
            patch.object(module.time, "time", return_value=1000),
            patch.object(module.time, "monotonic", return_value=0),
        ):
            for _ in range(4):
                self.p.db.execute("DELETE FROM request_gates")
                row = self.p.next_job(config, 1)
                selected.append(json.loads(row["job"])["api_name"])
                self.p.db.execute(
                    "UPDATE jobs SET state='done' WHERE id=?", (row["id"],)
                )
                self.p.db.commit()
                self.p.close()
                self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(
            selected,
            ["top10_holders", "daily", "top10_floatholders", "daily"],
        )
        turns = self.p.db.execute(
            "SELECT name,value FROM scheduler_state "
            "WHERE name GLOB 'throughput_api_turn:*'"
        ).fetchall()
        self.assertEqual(
            dict(turns),
            {
                "throughput_api_turn:top10_holders": 1,
                "throughput_api_turn:top10_floatholders": 2,
            },
        )
        self.assertEqual(self.p._fair_turn, 4)

    def test_fast_lane_rejects_unreviewed_or_disabled_apis(self):
        base = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
            "group_weights": {"rrg": 1},
            "throughput_fast_lane_every": 2,
        }
        with self.assertRaisesRegex(ValueError, "reviewed account-rate"):
            self.p.next_job(
                {
                    **base,
                    "enable_factor_library": True,
                    "throughput_fast_lane_apis": ["factor_value"],
                },
                time.monotonic() + 1,
            )
        with self.assertRaisesRegex(ValueError, "reviewed account-rate"):
            self.p.next_job(
                {
                    **base,
                    "throughput_fast_lane_apis": ["top10_holders"],
                },
                time.monotonic() + 1,
            )

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
