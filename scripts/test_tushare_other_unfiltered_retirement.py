#!/usr/bin/env python3
"""Offline tests for scoped WZ/GZ unfiltered-request retirement."""

from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from scripts import tushare_other_unfiltered_retirement as retirement  # noqa: E402

CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class OtherUnfilteredRetirement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("pipeline.lock", ".archive-worker.lock"):
            (self.root / name).touch()
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)
        self.config = {
            "enable_other": True,
            "other_apis": ["wz_index", "gz_index"],
            "history_start": "20240101",
        }

    def saved(self, api, params, state, status, *, has_more=False, rows=0):
        key = self.pipeline.enqueue(api, params, 20, "history")
        payload = json.dumps({"code": 0, "data": {"fields": [], "items": []}}).encode()
        object_sha = hashlib.sha256(payload).hexdigest()
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / (object_sha + ".json")).write_bytes(payload)
        observation = json.dumps({"request": {"params": params}}).encode()
        observation_sha = hashlib.sha256(observation).hexdigest()
        (self.root / "observations").mkdir(exist_ok=True)
        observation_name = observation_sha + ".json"
        (self.root / "observations" / observation_name).write_bytes(observation)
        result = {
            "api_name": api,
            "status": status,
            "row_count": rows,
            "supplier_has_more": has_more,
            "object_sha256": object_sha,
            "observation": observation_name,
            "observation_sha256": observation_sha,
        }
        encoded = json.dumps(result, sort_keys=True)
        self.pipeline.db.execute(
            "UPDATE jobs SET state=?,tries=1,result=? WHERE id=?", (state, encoded, key)
        )
        self.pipeline.db.execute("INSERT INTO attempts VALUES(?,?,?)", (key, 1, encoded))
        return key

    def fixture(self):
        for api in ("wz_index", "gz_index"):
            self.saved(
                api,
                {"start_date": "20240101", "end_date": "20241231"},
                "empty",
                "empty_unverified",
            )
            self.saved(
                api,
                {"start_date": "20250101", "end_date": "20260919"},
                "done",
                "sample_ok",
                rows=3,
            )
        parent = self.saved(
            "wz_index", {}, "blocked", "possibly_truncated", has_more=True, rows=3000
        )
        self.pipeline.db.commit()
        return parent

    def snapshot(self):
        return {
            table: [tuple(row) for row in self.pipeline.db.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("jobs", "attempts", "capability")
        }

    def test_dry_run_rolls_back_and_proves_both_scopes(self):
        self.fixture()
        before = self.snapshot()
        report = retirement.migrate(
            self.pipeline, self.config, date(2026, 9, 19)
        )
        self.assertEqual(report["status"], "planned_rollback")
        self.assertEqual(report["candidate_jobs"], 1)
        self.assertEqual(report["superseded_jobs"], 1)
        self.assertEqual(report["coverage"]["wz_index"]["range_jobs"], 2)
        self.assertEqual(report["coverage"]["gz_index"]["range_jobs"], 2)
        self.assertEqual(report["upstream_calls"], 0)
        self.assertEqual(self.snapshot(), before)

    def test_apply_preserves_result_and_attempt_then_is_idempotent(self):
        parent = self.fixture()
        result = self.pipeline.db.execute(
            "SELECT result FROM jobs WHERE id=?", (parent,)
        ).fetchone()[0]
        attempts = [
            tuple(row)
            for row in self.pipeline.db.execute(
                "SELECT * FROM attempts WHERE job_id=?", (parent,)
            )
        ]
        report = retirement.migrate(
            self.pipeline, self.config, date(2026, 9, 19), apply=True
        )
        self.assertEqual(report["superseded_jobs"], 1)
        state, after = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (parent,)
        ).fetchone()
        self.assertEqual(state, "superseded")
        self.assertEqual(after, result)
        self.assertEqual(
            [tuple(row) for row in self.pipeline.db.execute("SELECT * FROM attempts WHERE job_id=?", (parent,))],
            attempts,
        )
        status, reason = self.pipeline.db.execute(
            "SELECT status,reason FROM capability WHERE scope=?", ("retirement:" + parent,)
        ).fetchone()
        self.assertEqual(status, "request_contract_superseded")
        self.assertTrue(json.loads(reason)["coverage_proven"])
        second = retirement.migrate(
            self.pipeline, self.config, date(2026, 9, 19), apply=True
        )
        self.assertEqual(second["candidate_jobs"], 0)
        self.assertEqual(second["superseded_jobs"], 0)

    def test_gap_refuses_without_changes(self):
        self.saved(
            "wz_index",
            {"start_date": "20240101", "end_date": "20240131"},
            "empty",
            "empty_unverified",
        )
        self.saved(
            "wz_index", {}, "blocked", "possibly_truncated", has_more=True, rows=3000
        )
        self.config["other_apis"] = ["wz_index"]
        self.pipeline.db.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "coverage has a gap"):
            retirement.migrate(
                self.pipeline, self.config, date(2026, 9, 19), apply=True
            )
        self.assertEqual(self.snapshot(), before)

    def test_artifact_digest_mismatch_refuses_without_changes(self):
        parent = self.fixture()
        result = json.loads(
            self.pipeline.db.execute(
                "SELECT result FROM jobs WHERE id=?", (parent,)
            ).fetchone()[0]
        )
        (self.root / "objects" / (result["object_sha256"] + ".json")).write_text(
            "tampered"
        )
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            retirement.migrate(
                self.pipeline, self.config, date(2026, 9, 19), apply=True
            )
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
