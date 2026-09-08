#!/usr/bin/env python3
"""Offline acceptance of an explicitly selected candidate v3 pipeline.

Run with --pipeline-root PATH or QM_TUSHARE_PIPELINE_TEST_ROOT=PATH. The default
is the sibling candidate worktree used during integration. No authority mount,
credentials, sockets or production paths are read; every SQLite DB is temporary.
"""

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument(
    "--pipeline-root",
    type=Path,
    default=Path(
        os.environ.get(
            "QM_TUSHARE_PIPELINE_TEST_ROOT",
            "/Users/lizeyu/.codex/worktrees/quantmind-tushare-data-intake",
        )
    ),
)
args, remaining = parser.parse_known_args()
CANDIDATE = args.pipeline_root.resolve()
if not (CANDIDATE / "backend/shared/tushare_pipeline.py").is_file():
    raise RuntimeError("Pass --pipeline-root pointing to the candidate repository")
sys.path.insert(0, str(CANDIDATE))
import httpx  # noqa: E402
import backend.shared.tushare_pipeline as module  # noqa: E402

if Path(module.__file__).resolve() != CANDIDATE / "backend/shared/tushare_pipeline.py":
    raise RuntimeError(
        "A different pipeline was already imported; run this check in a fresh process"
    )

CATALOG = json.loads((CANDIDATE / "config/tushare-catalog.json").read_text())
CONFIG = {"priority_start": "20200101"}


class ExtendedPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("Offline test boundary"))
            guard.start()
            self.addCleanup(guard.stop)

    def pipeline(self):
        p = module.Pipeline(self.root, CATALOG)
        return p

    def test_bounded_planning_resumes_across_connection_and_deduplicates(self):
        def planner(config, anchor, identifiers):
            for n in range(12):
                yield {
                    "api_name": "daily",
                    "params": {"trade_date": f"202601{n + 1:02d}"},
                    "priority": 25 if n < 5 else 45,
                    "epoch": anchor.strftime("%Y%m%d") if n < 5 else "history",
                }

        config = {
            "history_start": "19900101",
            "enable_structured": True,
            "plan_jobs_per_tick": 2,
        }
        with patch.dict(module.PLANNERS, {"structured": planner}, clear=True):
            for _ in range(10):
                p = self.pipeline()
                before = p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                stats = p.plan_extended(config, date(2026, 1, 20))
                self.assertTrue(all(s["planned"] <= 2 for s in stats.values()))
                after = p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                self.assertLessEqual(after - before, 2)
                p.close()
            p = self.pipeline()
            rows = p.db.execute("SELECT logical_key,epoch FROM jobs").fetchall()
            self.assertEqual(len(rows), 12)
            self.assertEqual(len({tuple(row) for row in rows}), 12)
            self.assertEqual(
                p.db.execute("SELECT SUM(done) FROM planning_state").fetchone()[0], 2
            )
            self.assertEqual(p.plan_extended(config, date(2026, 1, 20)), {})
            for _ in range(4):
                p.plan_extended(config, date(2026, 1, 21))
            self.assertEqual(
                p.db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE epoch='history'"
                ).fetchone()[0],
                7,
            )
            self.assertEqual(
                p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 17
            )
            p.close()

    def test_denied_source_does_not_block_other_source_or_api(self):
        p = self.pipeline()
        jobs = [
            p.enqueue(
                "news",
                {
                    "src": source,
                    "start_date": f"2026-01-0{n} 00:00:00",
                    "end_date": f"2026-01-0{n} 23:59:59",
                },
            )
            for n, source in ((1, "sina"), (2, "sina"), (1, "cls"))
        ]
        other = p.enqueue("daily", {"trade_date": "20260101"})
        p.db.commit()
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append((payload["api_name"], payload["params"].get("src")))
            if payload["params"].get("src") == "sina":
                return httpx.Response(200, json={"code": 2002, "msg": "无权限"})
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": payload["fields"].split(","), "items": []},
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            result = p.run(
                client,
                "synthetic-test-token",
                CONFIG,
                max_requests=10,
                max_seconds=2,
                pause=0,
            )
        self.assertEqual(result["requests"], 3)
        self.assertEqual(requests.count(("news", "sina")), 1)
        self.assertIn(("news", "cls"), requests)
        self.assertIn(("daily", None), requests)
        states = dict(p.db.execute("SELECT id,state FROM jobs"))
        self.assertEqual(states[jobs[0]], "blocked")
        self.assertEqual(states[jobs[1]], "permission_blocked")
        self.assertNotIn(states[jobs[2]], ("blocked", "permission_blocked"))
        new = p.enqueue(
            "news",
            {
                "src": "sina",
                "start_date": "2026-01-03 00:00:00",
                "end_date": "2026-01-03 23:59:59",
            },
        )
        self.assertEqual(
            p.db.execute("SELECT state FROM jobs WHERE id=?", (new,)).fetchone()[0],
            "permission_blocked",
        )
        self.assertIsNotNone(other)
        p.close()

    def test_saturated_day_range_splits_without_skipping_or_self_recursion(self):
        p = self.pipeline()
        spec = {
            "row_cap": 2,
            "required_fields": ["date"],
            "nullable_fields": [],
            "positive_fields": [],
            "split": {
                "start_param": "start_date",
                "end_param": "end_date",
                "precision": "day",
            },
        }

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": ["date"], "items": [["20240228"], ["20240229"]]},
                },
            )

        with patch.object(module, "contract_for", return_value=spec):
            parent = p.enqueue(
                "shibor", {"start_date": "20240228", "end_date": "20240301"}
            )
            p.db.commit()
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False
            ) as client:
                p.run(
                    client,
                    "synthetic-test-token",
                    CONFIG,
                    max_requests=1,
                    max_seconds=2,
                    pause=0,
                )
            self.assertEqual(
                p.db.execute("SELECT state FROM jobs WHERE id=?", (parent,)).fetchone()[
                    0
                ],
                "split_pending",
            )
            children = [
                json.loads(r[0])["params"]
                for r in p.db.execute("SELECT job FROM jobs WHERE id<>?", (parent,))
            ]
            self.assertCountEqual(
                children,
                [
                    {"start_date": "20240228", "end_date": "20240229"},
                    {"start_date": "20240301", "end_date": "20240301"},
                ],
            )
            row = p.db.execute(
                "SELECT * FROM jobs WHERE id<>? AND json_extract(job,'$.params.start_date')='20240301'",
                (parent,),
            ).fetchone()
            self.assertIsNone(p.split_request(row, json.loads(row["job"])))
            self.assertEqual(
                p.db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (parent,)
                ).fetchone()[0],
                1,
            )
        p.close()

    def test_groups_are_fair_despite_rrg_priority(self):
        p = self.pipeline()
        for n in range(3):
            p.enqueue("etf_basic", {"list_status": "L", "marker": n}, priority=0)
            p.enqueue("news", {"src": "sina", "marker": n}, priority=99)
            p.enqueue("daily", {"trade_date": f"2026010{n + 1}"}, priority=99)
        p.db.commit()
        config = {
            "requests_per_minute": 500,
            "enable_text": True,
            "enable_structured": True,
        }
        seen = []
        for n in range(6):
            with (
                patch.object(module.time, "time", return_value=1000 + n * 10),
                patch.object(module.time, "monotonic", return_value=1000),
            ):
                row = p.next_job(config, 1001)
            self.assertIsNotNone(row)
            seen.append(row["group_name"])
            p.db.execute("UPDATE jobs SET state='done' WHERE id=?", (row["id"],))
            p.db.commit()
        self.assertEqual(seen, ["rrg", "text", "structured"] * 2)
        p.close()

    def test_fairness_survives_one_request_ticks_and_reopening(self):
        p = self.pipeline()
        for n in range(3):
            p.enqueue("etf_basic", {"list_status": "L", "marker": n}, priority=0)
            p.enqueue("news", {"src": "sina", "marker": n}, priority=99)
            p.enqueue("daily", {"trade_date": f"2026010{n + 1}"}, priority=99)
        p.db.commit()
        p.close()
        groups = []
        config = {
            "requests_per_minute": 500,
            "enable_text": True,
            "enable_structured": True,
        }
        for n in range(6):
            p = self.pipeline()
            # Virtual elapsed wall time clears rate reservations naturally; no real
            # sleep, and scheduler state remains untouched across every reopen.
            with (
                patch.object(module.time, "time", return_value=1000 + n * 10),
                patch.object(module.time, "monotonic", return_value=1000),
            ):
                row = p.next_job(config, 1000.1)
            self.assertIsNotNone(row)
            groups.append(row["group_name"])
            p.db.execute("UPDATE jobs SET state='done' WHERE id=?", (row["id"],))
            p.db.commit()
            p.close()
        self.assertEqual(groups, ["rrg", "text", "structured"] * 2)

    def test_fund_manager_documented_pagination_resume_end_and_repeated_page(self):
        for terminal in ("empty", "short", "repeated"):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as tmp:
                offsets = []

                def handler(request, terminal=terminal, offsets=offsets):
                    payload = json.loads(request.content)
                    params = payload["params"]
                    offsets.append(params["offset"])
                    self.assertEqual(params["limit"], 2)
                    first = [
                        ["000001.OF", "Manager A", "20260101", "20260102"],
                        ["000002.OF", "Manager B", "20260101", "20260102"],
                    ]
                    values = (
                        first
                        if params["offset"] == 0 or terminal == "repeated"
                        else (
                            [["000003.OF", "Manager C", "20260101", "20260102"]]
                            if terminal == "short"
                            else []
                        )
                    )
                    return httpx.Response(
                        200,
                        json={
                            "code": 0,
                            "data": {
                                "fields": ["ts_code", "name", "begin_date", "ann_date"],
                                "items": values,
                            },
                        },
                    )

                p = module.Pipeline(tmp, CATALOG)
                p.enqueue("fund_manager", {"offset": 0, "limit": 2}, epoch="20260120")
                p.db.commit()
                with httpx.Client(
                    transport=httpx.MockTransport(handler), trust_env=False
                ) as client:
                    p.run(
                        client,
                        "synthetic-test-token",
                        CONFIG,
                        max_requests=1,
                        max_seconds=2,
                        pause=0,
                    )
                    self.assertEqual(p.status(), {"done": 1, "pending": 1})
                    p.close()
                    p = module.Pipeline(tmp, CATALOG)
                    p.run(
                        client,
                        "synthetic-test-token",
                        CONFIG,
                        max_requests=5,
                        max_seconds=2,
                        pause=0,
                    )
                    self.assertEqual(offsets, [0, 2])
                    if terminal == "repeated":
                        self.assertEqual(p.status(), {"done": 1, "blocked": 1})
                        result = json.loads(
                            p.db.execute(
                                "SELECT result FROM jobs WHERE state='blocked'"
                            ).fetchone()[0]
                        )
                        self.assertEqual(result["pagination_error"], "repeated_page")
                    else:
                        self.assertEqual(p.status(), {"done": 2})
                        if terminal == "empty":
                            self.assertTrue(
                                any(
                                    json.loads(r[0]).get("pagination_end")
                                    for r in p.db.execute("SELECT result FROM jobs")
                                )
                            )
                    self.assertEqual(
                        p.run(
                            client,
                            "synthetic-test-token",
                            CONFIG,
                            max_requests=5,
                            max_seconds=2,
                            pause=0,
                        )["requests"],
                        0,
                    )
                self.assertEqual(
                    p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2
                )
                p.close()

    def test_v1_and_v2_migrations_preserve_jobs_attempts_and_gates(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                db = sqlite3.connect(Path(tmp) / "pipeline.sqlite")
                db.executescript(
                    """CREATE TABLE jobs(id TEXT PRIMARY KEY,logical_key TEXT NOT NULL,epoch TEXT NOT NULL,job TEXT NOT NULL,priority INTEGER NOT NULL,state TEXT NOT NULL,tries INTEGER NOT NULL DEFAULT 0,retry_after REAL NOT NULL DEFAULT 0,result TEXT,expanded INTEGER NOT NULL DEFAULT 0);"""
                )
                original = (
                    "saved-id",
                    "logical",
                    "history",
                    json.dumps(
                        {"api_name": "daily", "params": {"trade_date": "20260101"}}
                    ),
                    45,
                    "done",
                    2,
                    123.5,
                    json.dumps(
                        {
                            "status": "sample_ok",
                            "api_name": "daily",
                            "proof": "retained",
                        }
                    ),
                    1,
                )
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)", original)
                if version == 2:
                    db.executescript(
                        "CREATE TABLE request_gates(scope TEXT PRIMARY KEY,next_at REAL NOT NULL);INSERT INTO request_gates VALUES('account',123.0);"
                    )
                db.execute(f"PRAGMA user_version={version}")
                db.commit()
                db.close()
                p = module.Pipeline(tmp, CATALOG)
                self.assertEqual(
                    tuple(p.db.execute("SELECT * FROM jobs").fetchone())[:10], original
                )
                self.assertEqual(p.db.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(
                    p.db.execute(
                        "SELECT result FROM attempts WHERE job_id='saved-id' AND attempt=2"
                    ).fetchone()[0],
                    original[8],
                )
                if version == 2:
                    self.assertEqual(
                        p.db.execute(
                            "SELECT next_at FROM request_gates WHERE scope='account'"
                        ).fetchone()[0],
                        123,
                    )
                p.close()
                p = module.Pipeline(tmp, CATALOG)
                self.assertEqual(
                    p.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1
                )
                self.assertEqual(
                    p.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1
                )
                p.close()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *remaining])
