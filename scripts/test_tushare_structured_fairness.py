"""Offline structured scheduling: reservations, migration and indexed queue seeks."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_pipeline as module

INDEX = "jobs_ready_api_history"
CONFIG = {"requests_per_minute": 240, "enable_structured": True}


class StructuredFairnessTest(unittest.TestCase):
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
        self.stack.enter_context(patch.object(module.time, "time", return_value=1000))
        self.stack.enter_context(patch.object(module.time, "monotonic", return_value=0))

    def seed(
        self,
        apis=("adj_factor", "daily", "daily_basic", "namechange"),
        each=12,
        group="structured",
    ):
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        rows = []
        for api in apis:
            for history in (False, True):
                for i in range(each):
                    identity = f"{count + len(rows)}"
                    rows.append(
                        (
                            identity,
                            identity,
                            "history" if history else "legacy-probe",
                            json.dumps({"api_name": api, "params": {"i": i}}),
                            45 if history else 25,
                            "pending",
                            i % 2,
                            0,
                            json.dumps({"old_result": i}),
                            group,
                        )
                    )
        self.p.db.executemany(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,retry_after,result,group_name) VALUES(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.p.db.commit()

    def snapshot(self):
        return hashlib.sha256(
            json.dumps(
                [
                    tuple(r)
                    for r in self.p.db.execute(
                        "SELECT rowid,* FROM jobs ORDER BY rowid"
                    )
                ]
            ).encode()
        ).hexdigest()

    def next(self, config=None, complete=True):
        self.p.db.execute("DELETE FROM request_gates")
        self.p.db.commit()
        row = self.p.next_job(config if config is not None else CONFIG, 1)
        if complete and row:
            self.p.db.execute("UPDATE jobs SET state='done' WHERE id=?", (row["id"],))
            self.p.db.commit()
        return row

    def test_per_api_three_recent_one_history_and_reopen(self):
        self.seed()
        seen = {}
        sequence = []
        for i in range(32):
            row = self.next()
            api = json.loads(row["job"])["api_name"]
            sequence.append(api)
            seen.setdefault(api, []).append(row["epoch"] == "history")
            if i == 10:
                self.p.close()
                self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(sequence, sorted(seen) * 8)
        self.assertEqual(list(seen.values()), [[False, False, False, True] * 2] * 4)

    def test_family_weights_and_cross_group_fallback(self):
        self.seed(each=20)
        self.seed(("ci_daily",), each=40, group="rrg")
        self.seed(("news",), each=40, group="text")
        config = dict(CONFIG, enable_text=True, group_weights={"rrg": 3})
        groups = [self.next(config)["group_name"] for _ in range(50)]
        self.assertEqual(groups, ["rrg", "rrg", "rrg", "text", "structured"] * 10)
        # Disabled/empty scheduled families still fallback to queued structured;
        # fallback must use API fairness, not the globally oldest high priority.
        self.p.db.execute("UPDATE jobs SET state='done' WHERE group_name!='structured'")
        self.p.db.commit()
        apis = [
            json.loads(self.next({"requests_per_minute": 240})["job"])["api_name"]
            for _ in range(8)
        ]
        self.assertEqual(len(set(apis[:4])), 4)
        self.assertEqual(apis[:4], apis[4:])

    def test_cooldown_retry_borrow_and_new_pending_api(self):
        self.seed()
        self.p.db.execute("INSERT INTO request_gates VALUES('api:adj_factor',2000)")
        self.p.db.execute(
            "UPDATE jobs SET retry_after=2000 WHERE json_extract(job,'$.api_name')='daily' AND epoch!='history'"
        )
        row = self.p.next_job(CONFIG, 1)  # rrg fallback lands on structured
        self.assertEqual(json.loads(row["job"])["api_name"], "daily")
        self.assertEqual(row["epoch"], "history")
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name='structured_phase:daily'"
            ).fetchone()[0],
            1,
        )
        # New supplier API names are discovered from jobs, not a frozen/config list.
        self.seed(("balancesheet",), each=1)
        seen = [json.loads(self.next()["job"])["api_name"] for _ in range(5)]
        self.assertIn("balancesheet", seen)

    def test_all_structured_cold_falls_back_without_consuming_api_phases(self):
        self.seed(("daily", "adj_factor"), each=1)
        self.seed(("news",), each=1, group="text")
        self.p.db.executemany(
            "INSERT INTO request_gates VALUES(?,2000)",
            [("api:daily",), ("api:adj_factor",)],
        )
        self.p.db.commit()
        self.p._fair_turn = 1  # selected outer slot is structured
        row = self.p.next_job(CONFIG, 1)
        self.assertEqual(row["group_name"], "text")
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM scheduler_state WHERE name GLOB 'structured_*'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.p._fair_turn, 2)
        self.p.db.execute("UPDATE jobs SET state='done' WHERE group_name='text'")
        self.p.db.commit()
        self.assertEqual(self.p._next_structured_job(1000), (None, []))

    def test_both_bucket_borrow_directions_and_priority_within_bucket(self):
        self.seed(("daily",), each=6)
        self.p.db.execute("UPDATE jobs SET state='done' WHERE epoch='history'")
        self.p.db.execute("UPDATE jobs SET priority=1 WHERE id='4'")
        self.p.db.commit()
        rows = [self.next() for _ in range(4)]
        self.assertEqual(rows[0]["id"], "4")
        self.assertTrue(all(r["epoch"] != "history" for r in rows))
        self.p.db.execute(
            "UPDATE jobs SET state=CASE WHEN epoch='history' THEN 'pending' ELSE 'done' END"
        )
        self.p.db.commit()
        self.assertEqual(self.next()["epoch"], "history")

    def test_failed_attempt_consumes_opportunity_job_unchanged_at_reservation(self):
        self.seed(("daily",), each=6)
        before = self.snapshot()
        row = self.next(complete=False)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name='structured_phase:daily'"
            ).fetchone()[0],
            1,
        )
        # Model a later failure/retry using the same state transition as caller:
        # reservation is already durable and cannot rewind the phase.
        self.p.db.execute(
            "UPDATE jobs SET tries=tries+1,retry_after=2000 WHERE id=?", (row["id"],)
        )
        self.p.db.commit()
        self.p.close()
        self.p = module.Pipeline(self.root, {"entries": []})
        epochs = [self.next()["epoch"] for _ in range(3)]
        self.assertEqual(epochs, ["legacy-probe", "legacy-probe", "history"])

    def test_checkpoint_failure_rolls_back_gates_and_family_turn(self):
        self.seed(("daily",), each=1)
        before = self.snapshot()
        turn = self.p._fair_turn
        self.p.db.set_authorizer(
            lambda action, table, *args: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == "scheduler_state"
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.p.next_job(CONFIG, 1)
        self.p.db.set_authorizer(None)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM request_gates").fetchone()[0], 0
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM scheduler_state").fetchone()[0], 0
        )
        self.assertEqual(self.p._fair_turn, turn)
        self.assertEqual(before, self.snapshot())

    def test_commit_failure_rolls_back_already_written_checkpoints(self):
        self.seed(("daily",), each=1)
        self.p.db.set_authorizer(
            lambda action, name, *args: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.p.next_job(CONFIG, 1)
        self.p.db.set_authorizer(None)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM request_gates").fetchone()[0], 0
        )
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM scheduler_state").fetchone()[0], 0
        )
        self.assertEqual(self.p._fair_turn, 0)
        row = self.next(complete=False)
        self.assertIsNotNone(row)
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name='structured_phase:daily'"
            ).fetchone()[0],
            1,
        )

    def test_api_interval_quota_and_account_gates_unchanged(self):
        self.seed(("daily",), each=1)
        self.p.db.execute(
            "INSERT INTO capability VALUES('quota:daily','rate_limit_observed','today',?)",
            (json.dumps({"interval_seconds": 9}),),
        )
        self.p.db.commit()
        self.p.next_job(dict(CONFIG, api_min_interval_seconds={"daily": 5}), 1)
        self.assertEqual(
            dict(self.p.db.execute("SELECT * FROM request_gates")),
            {"account": 1000.25, "api:daily": 1009},
        )
        state = list(self.p.db.execute("SELECT * FROM scheduler_state"))
        self.assertIsNone(self.p.next_job(CONFIG, 0.1))
        self.assertEqual(
            state, list(self.p.db.execute("SELECT * FROM scheduler_state"))
        )

    def test_legacy_no_rpm_and_unknown_or_malformed_api_remain_visible(self):
        self.seed(each=4)
        apis = [json.loads(self.next({})["job"])["api_name"] for _ in range(4)]
        self.assertEqual(len(set(apis)), 4)
        self.p.db.execute("UPDATE jobs SET state='done'")
        self.p.db.commit()
        self.seed(("unknown_supplier_api",), each=1)
        before = self.snapshot()
        row = self.next(complete=False)
        self.assertEqual(json.loads(row["job"])["api_name"], "unknown_supplier_api")
        self.assertEqual(before, self.snapshot())
        self.p.db.execute("UPDATE jobs SET job='{}' WHERE state='pending'")
        self.p.db.commit()
        with self.assertRaisesRegex(ValueError, "missing/invalid"):
            self.p._next_structured_job(1000)

    def test_v5_migration_atomic_and_preserves_all_rows(self):
        self.seed(each=50)
        self.p.db.execute(
            "INSERT INTO planning_state VALUES('history:structured','20260909','original-signature',33500,0)"
        )
        self.p.db.execute("INSERT INTO scheduler_state VALUES('family_turn',123)")
        self.p.db.execute("INSERT INTO request_gates VALUES('account',42)")
        self.p.db.execute("DROP INDEX " + INDEX)
        self.p.db.execute("PRAGMA user_version=5")
        self.p.db.commit()
        before = self.snapshot()
        preserved = {
            t: [tuple(r) for r in self.p.db.execute("SELECT * FROM " + t)]
            for t in ("planning_state", "scheduler_state", "request_gates")
        }
        self.p.close()
        original = sqlite3.connect

        def failing(*args, **kwargs):
            db = original(*args, **kwargs)
            db.set_authorizer(
                lambda action, name, *rest: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_CREATE_INDEX and name == INDEX
                    else sqlite3.SQLITE_OK
                )
            )
            return db

        with patch.object(module.sqlite3, "connect", side_effect=failing):
            with self.assertRaises(sqlite3.DatabaseError):
                module.Pipeline(self.root, {"entries": []})
        with original(self.root / "pipeline.sqlite") as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertIsNone(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name=?", (INDEX,)
                ).fetchone()
            )
        self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.p.db.execute("PRAGMA user_version").fetchone()[0], 6)
        self.assertEqual(
            preserved,
            {
                t: [tuple(r) for r in self.p.db.execute("SELECT * FROM " + t)]
                for t in preserved
            },
        )
        self.assertEqual(self.p._fair_turn, 123)

    def test_400k_pending_indexed_seeks(self):
        def rows():
            for i in range(400000):
                api = f"api{i % 26:02}"
                yield (
                    str(i),
                    str(i),
                    "history" if (i // 26) % 4 == 3 else "20260909",
                    json.dumps({"api_name": api}),
                    25,
                    "pending",
                    "structured",
                )

        self.p.db.executemany(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,group_name) VALUES(?,?,?,?,?,?,?)",
            rows(),
        )
        self.p.db.commit()
        # A real v5 -> v6 index build on the same large, already populated DB.
        self.p.db.execute("DROP INDEX " + INDEX)
        self.p.db.execute("PRAGMA user_version=5")
        self.p.db.commit()
        before = self.snapshot()
        free_before = self.p.db.execute("PRAGMA freelist_count").fetchone()[0]
        pages_before = self.p.db.execute("PRAGMA page_count").fetchone()[0]
        self.p.close()
        started = time.perf_counter()
        self.p = module.Pipeline(self.root, {"entries": []})
        migration_ms = (time.perf_counter() - started) * 1000
        free_after = self.p.db.execute("PRAGMA freelist_count").fetchone()[0]
        pages_after = self.p.db.execute("PRAGMA page_count").fetchone()[0]
        page_size = self.p.db.execute("PRAGMA page_size").fetchone()[0]
        self.assertEqual(before, self.snapshot())
        queries = [
            (
                "SELECT json_extract(job,'$.api_name') FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' AND group_name='structured' AND json_extract(job,'$.api_name')>? ORDER BY json_extract(job,'$.api_name') LIMIT 1",
                ("api12",),
            ),
            (
                "SELECT * FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' AND group_name='structured' AND json_extract(job,'$.api_name')=? AND (epoch='history')=? AND retry_after<=? ORDER BY priority,rowid LIMIT 1",
                ("api13", 1, 1000),
            ),
        ]
        report = {
            "pending": 400000,
            "migration_ms": migration_ms,
            "index_bytes": (pages_after - free_after - pages_before + free_before)
            * page_size,
            "all_job_rows_sha256": before,
            "queries": [],
        }
        for query, params in queries:
            plan = [
                r[3] for r in self.p.db.execute("EXPLAIN QUERY PLAN " + query, params)
            ]
            counter = [0]
            self.p.db.set_progress_handler(
                lambda counter=counter: counter.__setitem__(0, counter[0] + 1) or 0, 1
            )
            started = time.perf_counter()
            self.assertIsNotNone(self.p.db.execute(query, params).fetchone())
            elapsed = (time.perf_counter() - started) * 1000
            self.p.db.set_progress_handler(None, 0)
            self.assertTrue(any("SEARCH jobs USING INDEX " + INDEX in p for p in plan))
            self.assertFalse(any("TEMP B-TREE" in p for p in plan))
            self.assertLess(counter[0], 100)
            report["queries"].append(
                {"plan": plan, "vm_steps": counter[0], "ms": elapsed}
            )
        # Whole selector covers all 26 APIs with checkpoints; no DISTINCT scan.
        counter = [0]
        self.p.db.set_progress_handler(
            lambda counter=counter: counter.__setitem__(0, counter[0] + 1) or 0, 100
        )
        started = time.perf_counter()
        for _ in range(52):
            row, states = self.p._next_structured_job(1000)
            self.assertIsNotNone(row)
            self.p.db.executemany(
                "INSERT INTO scheduler_state VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                states,
            )
        self.p.db.set_progress_handler(None, 0)
        report["52_selections"] = {
            "ms": (time.perf_counter() - started) * 1000,
            "vm_steps_lower_bound": counter[0] * 100,
        }
        self.assertLess(counter[0] * 100, 100000)
        print("STRUCTURED_FAIRNESS_BENCHMARK " + json.dumps(report))


if __name__ == "__main__":
    unittest.main()
