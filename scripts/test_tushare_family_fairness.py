"""Offline enabled-family fairness; preserve legacy structured and RRG behavior."""

import json
import sqlite3
import time
import unittest

import test_tushare_structured_fairness as fixtures

module = fixtures.module
FAMILY = "technical_extra"
CONFIG = {"requests_per_minute": 240, "enable_technical_extra": True}
PREFIX = "family:" + FAMILY.encode().hex() + ":"


class FamilyFairness(unittest.TestCase):
    setUp = fixtures.StructuredFairnessTest.setUp
    seed = fixtures.StructuredFairnessTest.seed
    snapshot = fixtures.StructuredFairnessTest.snapshot
    next = fixtures.StructuredFairnessTest.next

    def test_large_recent_prefix_history_within_four_api_turns_and_reopen(self):
        apis = ("stk_factor", "stk_factor_pro", "cyq_perf", "cyq_chips", "bak_daily")
        self.seed(apis, each=2000, group=FAMILY)
        self.p.db.execute(
            "INSERT INTO planning_state VALUES('history:technical_extra','20260909','frozen',87737,0)"
        )
        self.p.db.commit()
        plan_before = [
            tuple(r) for r in self.p.db.execute("SELECT * FROM planning_state")
        ]
        seen, sequence = {}, []
        started = time.perf_counter()
        for i in range(40):
            row = self.next(CONFIG)
            api = json.loads(row["job"])["api_name"]
            sequence.append(api)
            seen.setdefault(api, []).append(row["epoch"] == "history")
            if i == 16:
                self.p.close()
                self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(sequence, sorted(apis) * 8)
        self.assertEqual(list(seen.values()), [[False, False, False, True] * 2] * 5)
        self.assertEqual(
            plan_before,
            [tuple(r) for r in self.p.db.execute("SELECT * FROM planning_state")],
        )
        queries = (
            (
                "SELECT json_extract(job,'$.api_name') FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' AND group_name=? AND json_extract(job,'$.api_name')>? ORDER BY json_extract(job,'$.api_name') LIMIT 1",
                (FAMILY, "cyq_perf"),
            ),
            (
                "SELECT * FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' AND group_name=? AND json_extract(job,'$.api_name')=? AND (epoch='history')=? AND retry_after<=? ORDER BY priority,rowid LIMIT 1",
                (FAMILY, "stk_factor", 1, 1000),
            ),
        )
        plans = [
            [r[3] for r in self.p.db.execute("EXPLAIN QUERY PLAN " + sql, params)]
            for sql, params in queries
        ]
        for plan in plans:
            self.assertTrue(
                any(
                    "SEARCH jobs USING INDEX jobs_ready_api_history" in line
                    for line in plan
                )
            )
            self.assertFalse(any("TEMP B-TREE" in line for line in plan))
        print(
            json.dumps(
                {
                    "family_pending_seed": 20000,
                    "reservations": 40,
                    "seconds": time.perf_counter() - started,
                    "plans": plans,
                }
            )
        )

    def test_outer_weights_and_rrg_priority_unchanged(self):
        self.seed(("stk_factor",), each=40, group=FAMILY)
        self.seed(("ci_daily",), each=40, group="rrg")
        self.seed(("daily",), each=40)
        self.p.db.execute(
            "UPDATE jobs SET priority=1 WHERE group_name='rrg' AND epoch='history'"
        )
        self.p.db.commit()
        config = dict(CONFIG, enable_structured=True, group_weights={"rrg": 2})
        rows = [self.next(config) for _ in range(16)]
        self.assertEqual(
            [r["group_name"] for r in rows], ["rrg", "rrg", FAMILY, "structured"] * 4
        )
        self.assertTrue(
            all(r["epoch"] == "history" for r in rows if r["group_name"] == "rrg")
        )
        self.assertFalse(
            any(
                r[0].startswith("family:" + b"rrg".hex())
                for r in self.p.db.execute("SELECT name FROM scheduler_state")
            )
        )

    def test_fallback_gate_skip_retry_borrow_and_failure_consumes_opportunity(self):
        self.seed(("cyq_perf", "stk_factor"), each=8, group=FAMILY)
        self.p.db.execute("INSERT INTO request_gates VALUES('api:cyq_perf',2000)")
        self.p.db.execute(
            "UPDATE jobs SET retry_after=2000 WHERE json_extract(job,'$.api_name')='stk_factor' AND epoch!='history'"
        )
        self.p.db.commit()
        before = self.snapshot()
        row = self.p.next_job(CONFIG, 1)  # Empty RRG slot falls back into this family.
        self.assertEqual(json.loads(row["job"])["api_name"], "stk_factor")
        self.assertEqual(row["epoch"], "history")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?",
                (PREFIX + "phase:stk_factor",),
            ).fetchone()[0],
            1,
        )
        self.p.db.execute(
            "UPDATE jobs SET tries=tries+1,retry_after=2000 WHERE id=?", (row["id"],)
        )
        self.p.db.commit()
        self.p.close()
        self.p = module.Pipeline(self.root, {"entries": []})
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?",
                (PREFIX + "phase:stk_factor",),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM scheduler_state WHERE name=?",
                (PREFIX + "phase:cyq_perf",),
            ).fetchone()[0],
            0,
        )

    def test_cold_selected_family_fallback_keeps_other_family_fairness(self):
        self.seed(("stk_factor",), each=5, group=FAMILY)
        self.seed(("daily", "adj_factor"), each=5)
        self.p.db.execute("INSERT INTO request_gates VALUES('api:stk_factor',2000)")
        self.p.db.commit()
        self.p._fair_turn = 1
        row = self.p.next_job(CONFIG, 1)
        self.assertEqual(row["group_name"], "structured")
        self.assertEqual(
            self.p.db.execute(
                "SELECT count(*) FROM scheduler_state WHERE name GLOB ?",
                (PREFIX + "*",),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.p._fair_turn, 2)

    def test_disabled_unknown_and_legacy_modes(self):
        for config, group, fair in (
            ({}, FAMILY, False),
            ({"enable_technical_extra": True}, FAMILY, True),
            ({"enable_unknown": True}, "unknown", False),
            ({"requests_per_minute": 240}, FAMILY, False),
        ):
            with self.subTest(config=config, group=group):
                self.p.db.execute("DELETE FROM jobs")
                self.p.db.execute("DELETE FROM scheduler_state")
                self.seed(("cyq_perf", "stk_factor"), each=8, group=group)
                apis = [
                    json.loads(self.next(config)["job"])["api_name"] for _ in range(8)
                ]
                self.assertEqual(len(set(apis)), 2 if fair else 1)
                if not fair:
                    self.assertEqual(
                        self.p.db.execute(
                            "SELECT count(*) FROM scheduler_state WHERE name GLOB 'family:*'"
                        ).fetchone()[0],
                        0,
                    )

    def test_namespace_isolation_and_original_structured_checkpoint(self):
        families = ("text", "text:*", "文本", FAMILY)
        self.seed(("daily",), each=6)
        self.p.db.execute(
            "INSERT INTO scheduler_state VALUES('structured_phase:daily',3)"
        )
        self.p.db.execute(
            "INSERT INTO scheduler_state VALUES('structured_api_turn:daily',7)"
        )
        for family in families:
            self.seed(("same:api",), each=2, group=family)
            _, checkpoints = self.p._next_family_job(family, 1000)
            self.p.db.executemany(
                "INSERT INTO scheduler_state VALUES(?,?)", checkpoints
            )
        self.p.db.commit()
        row, checkpoints = self.p._next_structured_job(1000)
        self.assertEqual(row["epoch"], "history")
        self.assertEqual(
            checkpoints,
            [("structured_api_turn:daily", 8), ("structured_phase:daily", 0)],
        )
        for family in families:
            row, checkpoints = self.p._next_family_job(family, 1000)
            self.assertEqual(row["group_name"], family)
            self.assertEqual([value for _, value in checkpoints], [2, 2])

    def test_checkpoint_commit_failure_rolls_back_gates_jobs_and_cursor(self):
        self.seed(("stk_factor",), each=2, group=FAMILY)
        before = self.snapshot()
        self.p.db.set_authorizer(
            lambda action, name, *args: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.p.next_job(CONFIG, 1)
        self.p.db.set_authorizer(lambda *args: sqlite3.SQLITE_OK)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.p._fair_turn, 0)
        for table in ("scheduler_state", "request_gates"):
            self.assertEqual(
                self.p.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0
            )
        self.next(CONFIG, complete=False)
        self.assertEqual(
            self.p.db.execute(
                "SELECT value FROM scheduler_state WHERE name=?",
                (PREFIX + "phase:stk_factor",),
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
