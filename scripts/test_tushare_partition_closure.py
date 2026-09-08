#!/usr/bin/env python3
"""Offline v4 partition closure and conservative v1/v2/v3 migration checks."""

from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_pipeline as module  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_text())
API = "index_dailybasic"


class Closure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            guard = patch(target, side_effect=AssertionError("offline boundary"))
            guard.start()
            self.addCleanup(guard.stop)
        self.p = module.Pipeline(self.root, CATALOG)
        self.addCleanup(lambda: self.p.close())

    def reopen(self):
        self.p.close()
        self.p = module.Pipeline(self.root, CATALOG)

    def state(self, job):
        return self.p.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job,)
        ).fetchone()[0]

    def split(self, start="20260901", end="20260904", epoch="history"):
        parent = self.p.enqueue(
            API, {"start_date": start, "end_date": end}, epoch=epoch
        )
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (parent,)).fetchone()
        result = self.p.split_request(row, json.loads(row["job"]))
        self.p.db.execute(
            "UPDATE jobs SET state='split_pending',result=? WHERE id=?",
            (
                json.dumps(
                    {"api_name": API, "status": "possibly_truncated", "split": result}
                ),
                parent,
            ),
        )
        self.p.db.commit()
        return parent, [
            r[0]
            for r in self.p.db.execute(
                "SELECT child_id FROM partition_children WHERE parent_id=? ORDER BY child_id",
                (parent,),
            )
        ]

    def finish(self, key, state="done", status="sample_ok", artifact=True):
        path = self.root / "parquet" / (key + ".parquet")
        path.parent.mkdir(exist_ok=True)
        pq.write_table(
            pa.Table.from_pylist([{"ts_code": "SH000001", "trade_date": "20260901"}]),
            path,
        )
        result = {
            "api_name": API,
            "status": status,
            "row_count": 1,
            "parquet": {
                "path": str(path.relative_to(self.root)),
                "sha256": module.digest(path.read_bytes()),
                "bytes": path.stat().st_size,
            },
        }
        if not artifact:
            path.unlink()
        self.p.db.execute(
            "UPDATE jobs SET state=?,result=? WHERE id=?",
            (state, json.dumps(result), key),
        )
        self.p.db.commit()
        return result

    def test_persistent_idempotent_nested_closure(self):
        parent, children = self.split()
        nested_row = self.p.db.execute(
            "SELECT * FROM jobs WHERE id=?", (children[0],)
        ).fetchone()
        nested_job = json.loads(nested_row["job"])
        nested, leaves = self.split(
            nested_job["params"]["start_date"], nested_job["params"]["end_date"]
        )
        self.assertEqual(nested, children[0])
        self.finish(children[1])
        self.finish(leaves[0])
        self.p.reconcile_partitions()
        self.assertEqual(self.state(parent), "split_pending")
        self.reopen()
        self.finish(leaves[1])
        self.p.reconcile_partitions(child_id=leaves[1])
        self.assertEqual(self.state(nested), "resolved")
        self.assertEqual(self.state(parent), "resolved")
        inventory = self.p.partition_inventory()
        count = self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
        self.split()
        self.p.reconcile_partitions(child_id=parent)
        self.assertEqual(self.state(parent), "resolved")
        self.assertEqual(self.p.partition_inventory(), inventory)
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM jobs").fetchone()[0], count
        )

    def test_empty_permission_quality_and_missing_artifact_never_close(self):
        for state, status, artifact in [
            ("empty", "empty_unverified", True),
            ("done", "empty_unverified", True),
            ("blocked", "permission_denied", True),
            ("quality", "invalid_values", True),
            ("done", "schema_gap", True),
            ("pending", "transport_error", True),
            ("done", "possibly_truncated", True),
            ("done", "sample_ok", False),
        ]:
            parent, children = self.split(epoch=state + status + str(artifact))
            self.finish(children[0])
            self.finish(children[1], state, status, artifact)
            self.p.reconcile_partitions(child_id=children[1])
            self.assertEqual(self.state(parent), "split_pending", (state, status))
            self.finish(children[1])
            self.p.reconcile_partitions(child_id=children[1])
            self.assertEqual(self.state(parent), "resolved")

    def test_missing_universe_and_missing_edge_stay_explicit_gaps(self):
        parent = self.p.enqueue("us_adjfactor", {"trade_date": "20260901"})
        row = self.p.db.execute("SELECT * FROM jobs WHERE id=?", (parent,)).fetchone()
        with patch.object(
            self.p, "identifiers", return_value={"us_stocks": ["AAPL", "OLD"]}
        ):
            self.p.split_request(row, json.loads(row["job"]))
        self.p.db.execute("UPDATE jobs SET state='split_pending' WHERE id=?", (parent,))
        for child in self.p.db.execute(
            "SELECT child_id FROM partition_children WHERE parent_id=?", (parent,)
        ):
            self.finish(child[0])
        self.p.reconcile_partitions(child_id=parent)
        self.assertEqual(self.state(parent), "split_pending")
        self.assertEqual(
            self.p.partition_inventory()["splits"][0]["gap"], "universe_unverified"
        )
        date_parent, children = self.split()
        self.finish(children[0])
        self.p.db.execute(
            "DELETE FROM partition_children WHERE child_id=?", (children[1],)
        )
        self.p.reconcile_partitions(child_id=date_parent)
        gap = self.p.db.execute(
            "SELECT gap FROM partition_splits WHERE parent_id=?", (date_parent,)
        ).fetchone()[0]
        self.assertEqual(gap, "child_relationship_incomplete")

    def test_cycle_is_rejected_without_mutating_edges(self):
        parent, children = self.split()
        with self.assertRaises(ValueError):
            self.p.record_partition(children[0], [parent], "date_bisection", True, {})
        self.assertEqual(
            self.p.db.execute("SELECT count(*) FROM partition_children").fetchone()[0],
            2,
        )

    def test_lost_descendant_artifact_invalidates_ancestors(self):
        parent, children = self.split()
        row = self.p.db.execute(
            "SELECT job FROM jobs WHERE id=?", (children[0],)
        ).fetchone()
        params = json.loads(row[0])["params"]
        nested, leaves = self.split(params["start_date"], params["end_date"])
        self.finish(children[1])
        self.finish(leaves[0])
        lost = self.finish(leaves[1])
        self.p.reconcile_partitions(child_id=leaves[1])
        self.assertEqual(self.state(parent), "resolved")
        (self.root / lost["parquet"]["path"]).unlink()
        self.p.reconcile_partitions(child_id=leaves[1])
        self.assertEqual(self.state(nested), "split_pending")
        self.assertEqual(self.state(parent), "split_pending")

    def test_real_run_retry_closes_and_publishes_original_partial(self):
        calls = []

        def handler(request):
            body = json.loads(request.content)
            params = body["params"]
            calls.append(params)
            if params["start_date"] == params["end_date"] and len(calls) == 4:
                return httpx.Response(500, text="temporary")
            dates = (
                [params["start_date"]]
                if params["start_date"] == params["end_date"]
                else [params["start_date"], params["end_date"]]
            )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date"],
                        "items": [["000001.SH", day] for day in dates],
                    },
                },
            )

        with patch.dict(module.EXTENDED_CONTRACTS[API], {"row_cap": 2}):
            parent = self.p.enqueue(
                API, {"start_date": "20260901", "end_date": "20260904"}
            )
            with httpx.Client(
                transport=httpx.MockTransport(handler), trust_env=False
            ) as client:
                self.p.run(client, "synthetic", {}, max_requests=10, pause=0)
                self.assertEqual(self.state(parent), "split_pending")
                self.p.db.execute("UPDATE jobs SET retry_after=0 WHERE state='pending'")
                self.p.db.commit()
                self.reopen()
                self.p.run(client, "synthetic", {}, max_requests=10, pause=0)
        self.assertEqual(self.state(parent), "resolved")
        original = json.loads(
            self.p.db.execute(
                "SELECT result FROM attempts WHERE job_id=?", (parent,)
            ).fetchone()[0]
        )
        self.assertEqual(original["status"], "possibly_truncated")
        release = self.p.publish()
        manifest = module.verify_data(self.root, release)
        self.assertIn(
            "objects/" + original["object_sha256"] + ".json", manifest["files"]
        )
        self.assertFalse(any(g["id"] == parent for g in manifest["gaps"]))
        self.assertTrue(
            all(
                s["status"] == "resolved"
                for s in manifest["partition_closure"]["splits"]
            )
        )
        self.assertFalse(manifest["history_complete"])
        self.assertEqual(release, self.p.publish())

    def test_v3_recovers_only_unique_exact_contract_and_epoch(self):
        valid, children = self.split(epoch="valid")
        self.finish(children[0])
        self.finish(children[1])
        missing, bad_children = self.split(epoch="missing")
        self.p.db.execute("DELETE FROM jobs WHERE id=?", (bad_children[0],))
        mismatch, other_children = self.split(epoch="contract")
        job = json.loads(
            self.p.db.execute(
                "SELECT job FROM jobs WHERE id=?", (other_children[0],)
            ).fetchone()[0]
        )
        job["fields"] += ",different"
        self.p.db.execute(
            "UPDATE jobs SET job=? WHERE id=?", (json.dumps(job), other_children[0])
        )
        self.p.db.executescript(
            "DROP TABLE partition_children; DROP TABLE partition_splits; PRAGMA user_version=3;"
        )
        self.p.db.commit()
        self.reopen()
        self.assertEqual(self.p.db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.p.reconcile_partitions()
        self.assertEqual(self.state(valid), "resolved")
        for parent in (missing, mismatch):
            self.assertEqual(self.state(parent), "split_pending")
            item = self.p.db.execute(
                "SELECT * FROM partition_splits WHERE parent_id=?", (parent,)
            ).fetchone()
            self.assertEqual(item["gap"], "legacy_relationship_unverified")
        inventory = self.p.partition_inventory()
        self.reopen()
        self.assertEqual(self.p.partition_inventory(), inventory)

    def test_v3_unknown_fanout_stays_gap_even_when_matching_children_exist(self):
        parent, children = self.split()
        result = {
            "split": {
                "method": "identifier_fanout",
                "children": 2,
                "universe_complete": False,
            }
        }
        self.p.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), parent)
        )
        self.p.db.executescript(
            "DROP TABLE partition_children; DROP TABLE partition_splits; PRAGMA user_version=3;"
        )
        self.p.db.commit()
        self.reopen()
        self.p.reconcile_partitions()
        item = self.p.partition_inventory()["splits"][0]
        self.assertEqual(item["gap"], "legacy_relationship_unverified")
        self.assertEqual(item["children"], [])

    def test_bounded_cursor_resumes_across_restart(self):
        parents = []
        for n in range(3):
            parent, children = self.split(epoch=str(n))
            parents.append(parent)
            for child in children:
                self.finish(child)
        for _ in range(3):
            report = self.p.reconcile_partitions(max_parents=1)
            self.assertEqual(report["checked"], 1)
            self.reopen()
        self.assertTrue(all(self.state(parent) == "resolved" for parent in parents))

    def test_v1_v2_migration_preserves_jobs_and_original_attempt(self):
        for version in (1, 2):
            with tempfile.TemporaryDirectory() as tmp:
                db = sqlite3.connect(Path(tmp) / "pipeline.sqlite")
                db.executescript(
                    "CREATE TABLE jobs(id TEXT PRIMARY KEY,logical_key TEXT NOT NULL,epoch TEXT NOT NULL,job TEXT NOT NULL,priority INTEGER NOT NULL,state TEXT NOT NULL,tries INTEGER NOT NULL DEFAULT 0,retry_after REAL NOT NULL DEFAULT 0,result TEXT,expanded INTEGER NOT NULL DEFAULT 0);"
                )
                values = (
                    "old",
                    "logical",
                    "history",
                    json.dumps({"api_name": API, "params": {}}),
                    40,
                    "done",
                    2,
                    3.0,
                    json.dumps({"status": "sample_ok"}),
                    1,
                )
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)", values)
                if version == 2:
                    db.executescript(
                        "CREATE TABLE request_gates(scope TEXT PRIMARY KEY,next_at REAL NOT NULL); INSERT INTO request_gates VALUES('account',123);"
                    )
                db.execute(f"PRAGMA user_version={version}")
                db.commit()
                db.close()
                p = module.Pipeline(tmp, CATALOG)
                self.assertEqual(p.db.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(
                    tuple(p.db.execute("SELECT * FROM jobs").fetchone())[:10], values
                )
                self.assertEqual(
                    p.db.execute("SELECT result FROM attempts").fetchone()[0], values[8]
                )
                if version == 2:
                    self.assertEqual(
                        p.db.execute(
                            "SELECT next_at FROM request_gates WHERE scope='account'"
                        ).fetchone()[0],
                        123,
                    )
                p.close()


if __name__ == "__main__":
    unittest.main()
