#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPT = Path("/tmp/run_tushare_opt_daily_one_call.py")
spec = importlib.util.spec_from_file_location("opt_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
CANDIDATE = Path(
    "/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/coordination/tushare-data/"
    "20260912T075159Z-opt-daily-fixed-row-sample-candidate.json"
)


class DuplicateGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = sqlite3.connect(Path(self.temp.name) / "pipeline.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE jobs (
              id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, epoch TEXT NOT NULL,
              job TEXT NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL,
              tries INTEGER NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
              result TEXT, expanded INTEGER NOT NULL DEFAULT 0,
              group_name TEXT NOT NULL DEFAULT 'rrg');
            CREATE TABLE attempts (
              job_id TEXT NOT NULL, attempt INTEGER NOT NULL, result TEXT NOT NULL,
              PRIMARY KEY(job_id,attempt));
            CREATE INDEX jobs_ready_api_history
              ON jobs(group_name,json_extract(job,'$.api_name'),
                      (epoch='history'),priority) WHERE state='pending';
            PRAGMA user_version=6;
            """
        )
        self.db.execute(
            "INSERT INTO attempts(rowid,job_id,attempt,result) VALUES(?,?,?,?)",
            (runner.ATTEMPT_WATERMARK, runner.WATERMARK_JOB_ID, 4, "{}"),
        )
        self.verified = runner.verify_candidate(
            CANDIDATE, runner.EXPECTED_CANDIDATE_SHA256
        )
        self.job = self.verified["job"]
        self.candidate = self.verified["candidate"]
        self.config = {"planning_epoch": "20260912"}

    def add_job(self, job, epoch, state="pending", tries=0, result=None):
        logical = runner.digest(runner.json_bytes(job))
        task = runner._task_id(logical, epoch)
        self.db.execute(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,result,group_name) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                task,
                logical,
                epoch,
                runner.json_bytes(job).decode(),
                10,
                state,
                tries,
                None if result is None else json.dumps(result),
                runner.GROUP,
            ),
        )
        return task

    def inspect(self):
        self.db.commit()
        return runner.inspect_duplicates(self.db, self.job, self.candidate, self.config)

    def test_new_candidate_and_indexed_query(self):
        result = self.inspect()
        self.assertEqual(result["action"], "enqueue_candidate_epoch")
        self.assertIn("jobs_ready_api_history", result["query_plan"]["pending"])
        self.assertIn("INTEGER PRIMARY KEY", result["query_plan"]["attempt_tail"])

    def test_reuse_pristine_history_task(self):
        task = self.add_job(self.job, "history")
        result = self.inspect()
        self.assertEqual(result["action"], "use_existing_pristine")
        self.assertEqual(result["task"]["id"], task)

    def test_reuse_post_watermark_attempt_without_http(self):
        task = self.add_job(
            self.job,
            "unexpected-epoch",
            state="done",
            tries=1,
            result={"status": "sample_ok"},
        )
        self.db.execute(
            "INSERT INTO attempts(rowid,job_id,attempt,result) VALUES(?,?,?,?)",
            (
                runner.ATTEMPT_WATERMARK + 1,
                task,
                1,
                json.dumps({"status": "sample_ok"}),
            ),
        )
        result = self.inspect()
        self.assertEqual(result["action"], "reuse_without_http")
        self.assertEqual(result["attempt_rowid"], runner.ATTEMPT_WATERMARK + 1)

    def test_history_contract_drift_blocks(self):
        changed = {**self.job, "fields": "trade_date,ts_code"}
        self.add_job(changed, "history")
        self.assertEqual(self.inspect()["action"], "blocked_pending_contract_drift")


if __name__ == "__main__":
    unittest.main()
