"""Paired fund_nav empty reviews are exact, bounded and recoverable."""

from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import prepare_tushare_fund_nav_empty_review as preparation  # noqa: E402
from scripts import run_tushare_fund_nav_empty_review as runner  # noqa: E402
from scripts import test_tushare_fund_nav_empty_review as prepare_tests  # noqa: E402


class FundNavEmptyReviewRunnerTests(unittest.TestCase):
    def setUp(self):
        fixture = prepare_tests.FundNavEmptyReviewTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.base = fixture.base
        self.authority = fixture.authority
        self.release_root = fixture.release_root
        self.release_id = fixture.release_id
        self.now = fixture.first_fetched + timedelta(days=2)
        self.manifest_path = self.base / "review-plan.json"
        self.manifest = fixture._prepare(self.now, self.manifest_path)
        (self.authority / "ENABLED").write_text("enabled\n")
        self.config_path = self.authority / "pipeline-config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "rate_policy": "legacy",
                    "requests_per_minute": 500,
                    "api_requests_per_minute": {"fund_nav": 500},
                }
            )
        )
        (self.authority / "CURRENT.json").write_text('{"release_id":"unchanged"}\n')

    def plan(self, path=None, digest=None, **overrides):
        arguments = {
            "manifest": path or self.manifest_path,
            "manifest_sha256": digest or preparation.sha(self.manifest_path),
        }
        arguments.update(overrides)
        return runner.run_review(**arguments)

    def execute(self, handler, output=None, **overrides):
        output = output or self.base / "receipt.json"
        disk_free = overrides.pop("disk_free", runner.MIN_FREE_BYTES + 1)
        arguments = {
            "root": self.authority,
            "release_root": self.release_root,
            "release_id": self.release_id,
            "expected_authority_sha256": runner.sha(self.authority / "pipeline.sqlite"),
            "expected_config_sha256": runner.sha(self.config_path),
            "expected_code_sha256": runner.code_sha256(),
            "expected_release_manifest_sha256": self.release_id.removeprefix("data-"),
            "expected_task_ids_sha256": self.manifest["all_task_ids_sha256"],
            "output": output,
            "max_requests": 2,
            "max_seconds": 10,
            "now": self.now,
            "execute": True,
        }
        arguments.update(overrides)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        disk = type("usage", (), {"free": disk_free})()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.authority),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.shutil, "disk_usage", return_value=disk),
            patch.object(runner.httpx, "Client", return_value=client),
            patch.object(runner.time, "sleep", return_value=None),
        ):
            return self.plan(**arguments)

    def response(self, *, request_empty=True, control_ok=True):
        calls = []

        def handle(request):
            body = json.loads(request.content)
            calls.append(body["params"])
            fields = body["fields"].split(",")
            is_control = body["params"]["start_date"] == "20130503"
            if (is_control and not control_ok) or (not is_control and request_empty):
                items = []
            else:
                values = {
                    "ts_code": "000022.OF",
                    "nav_date": body["params"]["start_date"],
                    "ann_date": None,
                    "unit_nav": 1.0,
                }
                items = [[values.get(field) for field in fields]]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": fields, "items": items, "has_more": False},
                },
            )

        return calls, handle

    def attempts(self):
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT result FROM attempts WHERE job_id=? ORDER BY attempt",
                    (self.fixture.target_id,),
                )
            ]
        finally:
            db.close()

    def test_plan_only_rejects_tampering_without_authority_secret_or_network(self):
        before = (self.authority / "pipeline.sqlite").read_bytes()
        result = self.plan(root=self.base / "ignored")
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["paired_targets"], 1)
        self.assertEqual(result["required_upstream_calls"], 2)
        self.assertEqual(
            result["operator_precondition"],
            "host_must_stop_beat_and_tushare_worker",
        )
        self.assertEqual(result["writer_exclusion"], "nonblocking_shared_pipeline_lock")
        self.assertFalse(result["would_access_authority"])
        self.assertEqual((self.authority / "pipeline.sqlite").read_bytes(), before)
        tampered = self.base / "tampered.json"
        changed = json.loads(self.manifest_path.read_bytes())
        changed["records"][0]["target"]["job"]["params"]["start_date"] = "19900102"
        tampered.write_bytes(preparation.json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.plan(tampered, preparation.sha(tampered))

    def test_valid_pair_appends_review_attempt_and_preserves_empty_task(self):
        calls, handler = self.response()
        pointer = (self.authority / "CURRENT.json").read_bytes()
        receipt = self.execute(handler)
        self.assertEqual(
            calls,
            [
                {
                    "ts_code": "000022.OF",
                    "start_date": "19900101",
                    "end_date": "20080502",
                },
                {
                    "ts_code": "000022.OF",
                    "start_date": "20130503",
                    "end_date": "20130503",
                },
            ],
        )
        self.assertEqual(receipt["outcome_counts"], {"round1_valid_empty": 1})
        self.assertEqual(receipt["upstream_calls"], 2)
        self.assertFalse(receipt["operator_precondition_verified_by_runner"])
        self.assertEqual(
            receipt["writer_exclusion"], "nonblocking_shared_pipeline_lock"
        )
        self.assertEqual(json.loads((self.base / "receipt.json").read_bytes()), receipt)
        reviews = self.attempts()
        self.assertEqual(reviews[-1]["status"], "round1_valid_empty")
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            state, tries = db.execute(
                "SELECT state,tries FROM jobs WHERE id=?", (self.fixture.target_id,)
            ).fetchone()
        finally:
            db.close()
        self.assertEqual((state, tries), ("empty", 1))
        self.assertEqual((self.authority / "CURRENT.json").read_bytes(), pointer)
        self.assertFalse(receipt["release_published"])

    def test_recovered_data_uses_normalization_and_partition_reconciliation(self):
        _calls, handler = self.response(request_empty=False)
        receipt = self.execute(handler)
        self.assertEqual(receipt["outcome_counts"], {"review_recovered_data": 1})
        saved = self.attempts()[-1]
        self.assertIn("parquet", saved["request_result"])
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            state = db.execute(
                "SELECT state FROM jobs WHERE id=?", (self.fixture.target_id,)
            ).fetchone()[0]
            parent = db.execute(
                "SELECT status,gap FROM partition_splits WHERE parent_id=?",
                (self.manifest["records"][0]["parent_ids"][0],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(state, "done")
        self.assertEqual(parent, ("gap", "child_not_verified"))

    def test_receipt_can_be_rebuilt_after_post_commit_crash_without_more_http(self):
        calls, handler = self.response(request_empty=False)
        with patch.object(
            runner, "_write_receipt", side_effect=OSError("fixture crash")
        ):
            with self.assertRaisesRegex(OSError, "fixture crash"):
                self.execute(handler, self.base / "lost-receipt.json")
        self.assertEqual(len(calls), 2)
        rebuilt = self.execute(handler, self.base / "rebuilt-receipt.json")
        self.assertEqual(len(calls), 2)
        self.assertEqual(rebuilt["upstream_calls"], 0)
        self.assertEqual(rebuilt["outcome_counts"], {"review_recovered_data": 1})

    def test_inconclusive_retry_progresses_to_manual_hold_without_replaying_a_plan(
        self,
    ):
        _calls, handler = self.response(control_ok=False)
        first = self.execute(handler, self.base / "receipt-1.json")
        self.assertEqual(first["outcome_counts"], {"review_inconclusive": 1})
        with self.assertRaisesRegex(ValueError, "Receipt output must be new"):
            self.execute(handler, self.base / "receipt-1.json")

        previous = self.attempts()[-1]
        for index, wait in ((2, timedelta(hours=2)), (3, timedelta(days=2))):
            self.now += wait
            self.manifest_path = self.base / f"review-plan-{index}.json"
            self.manifest = self.fixture._prepare(self.now, self.manifest_path)
            receipt = self.execute(handler, self.base / f"receipt-{index}.json")
            expected = "manual_hold" if index == 3 else "review_inconclusive"
            self.assertEqual(receipt["outcome_counts"], {expected: 1})
            previous = self.attempts()[-1]
        self.assertIsNone(previous["empty_review"]["retry_not_before"])

    def test_conflicts_and_all_execute_gates_fail_before_http(self):
        calls = 0

        def wrong(request):
            nonlocal calls
            calls += 1
            body = json.loads(request.content)
            fields = body["fields"].split(",")
            values = {"ts_code": "WRONG.OF", "nav_date": "19900101"}
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": fields,
                        "items": [[values.get(f) for f in fields]],
                    },
                },
            )

        result = self.execute(wrong)
        self.assertEqual(result["outcome_counts"], {"review_conflict": 1})
        self.assertEqual(calls, 2)

        # Fresh fixture for pre-HTTP gates after the terminal conflict above.
        self.setUp()
        before = calls
        with self.assertRaisesRegex(ValueError, "code hash mismatch"):
            self.execute(wrong, expected_code_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "authority database hash mismatch"):
            self.execute(wrong, expected_authority_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "config hash mismatch"):
            self.execute(wrong, expected_config_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "release manifest hash mismatch"):
            self.execute(wrong, expected_release_manifest_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "task inventory hash mismatch"):
            self.execute(wrong, expected_task_ids_sha256="0" * 64)
        with (self.authority / "pipeline.lock").open("a+") as held:
            import fcntl

            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.execute(wrong)
        blocked = self.execute(wrong, disk_free=runner.MIN_FREE_BYTES - 1)
        self.assertEqual(blocked["status"], "blocked_disk_reserve")
        self.assertEqual(calls, before)


if __name__ == "__main__":
    unittest.main()
