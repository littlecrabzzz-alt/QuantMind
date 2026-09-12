"""Private two-stage portfolio exact batch helper tests."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import stat
import socket
import tempfile
import unittest
from unittest.mock import patch

import httpx

from backend.shared.tushare_intake import json_bytes
from backend.shared.tushare_pipeline import Pipeline
from scripts import tushare_portfolio_read_batch as helper


class PortfolioReadBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "authority"
        self.root.mkdir()
        self.catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = Pipeline(self.root, self.catalog)
        pipeline.close()
        (self.root / "pipeline.lock").touch(mode=0o600)
        (self.root / "ENABLED").write_text("enabled\n")
        self.snapshot = "20260912T080000Z"
        self.config = {
            "enable_portfolio_read": True,
            "portfolio_read_apis": ["p_list", "p_get"],
            "portfolio_read_snapshot_epoch": self.snapshot,
            "rate_policy": "tiered_v1",
            "requests_per_minute": 240,
            "rollout_account_rpm": 240,
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_bytes(json_bytes(self.config))
        self.config_sha = helper.sha(self.config_path)
        release_raw = json_bytes({"datasets": [], "files": {}})
        self.release_sha = helper.digest(release_raw)
        self.release_id = "data-" + self.release_sha
        release = self.root / "releases" / self.release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(release_raw)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes(
                {
                    "manifest_sha256": self.release_sha,
                    "release_id": self.release_id,
                }
            )
        )
        self.private = self.root / helper.PRIVATE_DIR
        self.code_sha = helper.code_sha256()
        self.list_manifest = self.private / "list-manifest.json"
        self.list = helper.prepare_manifest(
            self.root,
            self.list_manifest,
            stage="list",
            release_id=self.release_id,
            release_manifest_sha256=self.release_sha,
            authority_config_sha256=self.config_sha,
            code_sha256_pin=self.code_sha,
            snapshot_epoch=self.snapshot,
        )
        self.list_sha = helper.sha(self.list_manifest)

    def response(self, body, names=("synthetic-a", "synthetic-b")):
        fields = body["fields"].split(",")
        if body["api_name"] == "p_list":
            source = [
                {
                    "id": index,
                    "name": name,
                    "desc": None,
                    "create_time": None,
                    "update_time": None,
                }
                for index, name in enumerate(names, 1)
            ]
        else:
            source = [
                {
                    "id": 10,
                    "ts_code": "opaque-component",
                    "ts_type": "custom",
                    "name": "synthetic-component",
                    "desc": None,
                    "weight": 0.5,
                    "create_time": None,
                    "update_time": None,
                }
            ]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [[row.get(field) for field in fields] for row in source],
                    "has_more": False,
                },
            },
        )

    def execute(
        self, manifest_path, manifest, receipt_path, responder=None, token="fixture"
    ):
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body)
            return (responder or self.response)(body)

        client = httpx.Client(transport=httpx.MockTransport(respond))
        with (
            patch.object(helper.pipeline_module, "ROOT", self.root),
            patch.object(helper.pipeline_module, "authority"),
            patch.object(helper.pipeline_module, "get_secret", return_value=token),
            patch.object(helper.httpx, "Client", return_value=client),
            patch.object(
                helper.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=helper.MIN_FREE_BYTES + 1),
            ),
        ):
            result = helper.run_batch(
                self.root,
                manifest_path,
                helper.sha(manifest_path),
                expected_task_ids_sha256=manifest["all_task_ids_sha256"],
                expected_config_sha256=self.config_sha,
                expected_code_sha256=self.code_sha,
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                receipt_path=receipt_path,
                execute=True,
            )
        return result, calls

    def prepare_members(self, list_receipt, output="members-manifest.json"):
        target = self.private / output
        result = helper.prepare_manifest(
            self.root,
            target,
            stage="members",
            release_id=self.release_id,
            release_manifest_sha256=self.release_sha,
            authority_config_sha256=self.config_sha,
            code_sha256_pin=self.code_sha,
            snapshot_epoch=self.snapshot,
            source_manifest=self.list_manifest,
            source_manifest_sha256=self.list_sha,
            source_receipt=list_receipt,
            source_receipt_sha256=helper.sha(list_receipt),
        )
        return target, result

    def test_default_plan_only_is_offline_read_only_and_private(self):
        before = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        result = helper.run_batch(self.root, self.list_manifest, self.list_sha)
        after = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "plan_only")
        self.assertFalse(any(result[key] for key in result if key.startswith("would_")))
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.list_manifest.stat().st_mode), 0o600)
        self.assertNotIn("records", result)
        self.assertNotIn("params", json.dumps(result))

        database_before = (self.root / "pipeline.sqlite").read_bytes()
        second = self.private / "second-list-manifest.json"
        with (
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ),
            patch.object(
                socket,
                "getaddrinfo",
                side_effect=AssertionError("dns forbidden"),
            ),
            patch.object(
                helper.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credentials forbidden"),
            ),
        ):
            helper.prepare_manifest(
                self.root,
                second,
                stage="list",
                release_id=self.release_id,
                release_manifest_sha256=self.release_sha,
                authority_config_sha256=self.config_sha,
                code_sha256_pin=self.code_sha,
                snapshot_epoch=self.snapshot,
            )
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), database_before)
        with self.assertRaisesRegex(ValueError, "create-only"):
            helper.prepare_manifest(
                self.root,
                second,
                stage="list",
                release_id=self.release_id,
                release_manifest_sha256=self.release_sha,
                authority_config_sha256=self.config_sha,
                code_sha256_pin=self.code_sha,
                snapshot_epoch=self.snapshot,
            )
        failed = self.private / "failed-atomic.json"
        with (
            patch.object(helper.os, "link", side_effect=OSError("fixture")),
            self.assertRaises(OSError),
        ):
            helper._write_private(self.root, failed, {"private": "fixture"})
        self.assertFalse(failed.exists())
        self.assertFalse(any(self.private.glob(".failed-atomic.json.*.tmp")))

    def test_two_stages_are_exact_private_and_token_precedes_enqueue(self):
        events = []
        original_enqueue = helper.pipeline_module.Pipeline.enqueue

        def token(_name):
            events.append("token")
            return "fixture"

        def enqueue(pipeline, *args, **kwargs):
            self.assertIn("token", events)
            events.append("enqueue")
            return original_enqueue(pipeline, *args, **kwargs)

        list_receipt = self.private / "list-receipt.json"
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: self.response(json.loads(request.content))
            )
        )
        with (
            patch.object(helper.pipeline_module, "ROOT", self.root),
            patch.object(helper.pipeline_module, "authority"),
            patch.object(helper.pipeline_module, "get_secret", side_effect=token),
            patch.object(helper.pipeline_module.Pipeline, "enqueue", new=enqueue),
            patch.object(helper.httpx, "Client", return_value=client),
            patch.object(
                helper.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=helper.MIN_FREE_BYTES + 1),
            ),
        ):
            first = helper.run_batch(
                self.root,
                self.list_manifest,
                self.list_sha,
                expected_task_ids_sha256=self.list["all_task_ids_sha256"],
                expected_config_sha256=self.config_sha,
                expected_code_sha256=self.code_sha,
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                receipt_path=list_receipt,
                execute=True,
            )
        self.assertEqual(first["upstream_calls"], 1)
        self.assertEqual(first["attempted_by_api"], {"p_list": 1})
        self.assertEqual(events[:2], ["token", "enqueue"])
        members_path, members = self.prepare_members(list_receipt)
        self.assertEqual(len(members["records"]), 2)
        self.assertEqual(
            {record["job"]["params"]["name"] for record in members["records"]},
            {"synthetic-a", "synthetic-b"},
        )
        plan = helper.run_batch(self.root, members_path, helper.sha(members_path))
        self.assertNotIn("synthetic", json.dumps(plan))
        members_receipt = self.private / "members-receipt.json"
        second, calls = self.execute(members_path, members, members_receipt)
        self.assertEqual(second["upstream_calls"], 2)
        self.assertEqual(second["effective_api_rpm"], 30)
        self.assertGreaterEqual(second["elapsed_seconds"], 1.8)
        self.assertEqual({call["api_name"] for call in calls}, {"p_get"})
        self.assertEqual(
            {call["params"]["name"] for call in calls},
            {"synthetic-a", "synthetic-b"},
        )
        receipt_text = members_receipt.read_text()
        self.assertNotIn("synthetic-a", receipt_text)
        self.assertNotIn("opaque-component", receipt_text)
        self.assertEqual(stat.S_IMODE(members_receipt.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads((self.root / "CURRENT.json").read_bytes())["release_id"],
            self.release_id,
        )

    def test_missing_token_never_enqueues(self):
        receipt = self.private / "missing-token-receipt.json"
        before = (self.root / "pipeline.sqlite").read_bytes()
        with (
            patch.object(helper.pipeline_module, "ROOT", self.root),
            patch.object(helper.pipeline_module, "authority"),
            patch.object(helper.pipeline_module, "get_secret", return_value=None),
            patch.object(
                helper.pipeline_module.Pipeline,
                "enqueue",
                side_effect=AssertionError("enqueue before token"),
            ),
            patch.object(
                helper.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=helper.MIN_FREE_BYTES + 1),
            ),
            self.assertRaisesRegex(ValueError, "before enqueue"),
        ):
            helper.run_batch(
                self.root,
                self.list_manifest,
                self.list_sha,
                expected_task_ids_sha256=self.list["all_task_ids_sha256"],
                expected_config_sha256=self.config_sha,
                expected_code_sha256=self.code_sha,
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                receipt_path=receipt,
                execute=True,
            )
        self.assertEqual((self.root / "pipeline.sqlite").read_bytes(), before)
        self.assertFalse(receipt.exists())

    def test_member_prepare_rejects_prior_attempt_and_pin_drift(self):
        list_receipt = self.private / "list-receipt.json"
        self.execute(self.list_manifest, self.list, list_receipt)
        members_path, members = self.prepare_members(list_receipt)
        member = members["records"][0]
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute(
                "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,result,group_name) "
                "VALUES(?,?,?,?,?,'pending',0,NULL,?)",
                (
                    member["task_id"],
                    member["logical_key"],
                    member["epoch"],
                    json.dumps(member["job"]),
                    member["priority"],
                    member["group_name"],
                ),
            )
            db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,1,?)",
                (member["task_id"], json.dumps({"status": "transport_error"})),
            )
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "prior execution evidence"):
            self.prepare_members(list_receipt, "members-second.json")
        with self.assertRaisesRegex(ValueError, "code hash"):
            helper.run_batch(
                self.root,
                members_path,
                helper.sha(members_path),
                expected_code_sha256="0" * 64,
            )

    def test_execution_pins_fail_before_token_or_enqueue(self):
        correct = {
            "expected_task_ids_sha256": self.list["all_task_ids_sha256"],
            "expected_config_sha256": self.config_sha,
            "expected_code_sha256": self.code_sha,
            "expected_release_id": self.release_id,
            "expected_release_manifest_sha256": self.release_sha,
        }
        changes = (
            {"expected_task_ids_sha256": "0" * 64},
            {"expected_config_sha256": "0" * 64},
            {"expected_code_sha256": "0" * 64},
            {"expected_release_id": "data-" + "0" * 64},
            {"expected_release_manifest_sha256": "0" * 64},
        )
        for index, changed in enumerate(changes):
            with (
                self.subTest(changed=next(iter(changed))),
                patch.object(helper.pipeline_module, "ROOT", self.root),
                patch.object(helper.pipeline_module, "authority"),
                patch.object(
                    helper.pipeline_module,
                    "get_secret",
                    side_effect=AssertionError("pin drift reached token"),
                ),
                patch.object(
                    helper.pipeline_module.Pipeline,
                    "enqueue",
                    side_effect=AssertionError("pin drift reached enqueue"),
                ),
                self.assertRaises(ValueError),
            ):
                helper.run_batch(
                    self.root,
                    self.list_manifest,
                    self.list_sha,
                    **(correct | changed),
                    receipt_path=self.private / f"drift-{index}.json",
                    execute=True,
                )

    def test_more_than_thirty_portfolios_fails_without_names(self):
        names = tuple(f"private-{index:02d}" for index in range(31))
        list_receipt = self.private / "list-receipt.json"
        self.execute(
            self.list_manifest,
            self.list,
            list_receipt,
            responder=lambda body: self.response(body, names=names),
        )
        with self.assertRaises(ValueError) as error:
            self.prepare_members(list_receipt)
        message = str(error.exception)
        self.assertEqual(
            message, "Observed portfolio count exceeds one-shot member limit"
        )
        self.assertFalse(any(name in message for name in names))

    def test_cross_epoch_same_request_is_not_rejected(self):
        other = helper._job_record("p_list", {}, "20260912T090000Z")
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute(
                "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,result,group_name) "
                "VALUES(?,?,?,?,?,'done',1,?,?)",
                (
                    other["task_id"],
                    other["logical_key"],
                    other["epoch"],
                    json.dumps(other["job"]),
                    other["priority"],
                    json.dumps({"status": "sample_ok"}),
                    other["group_name"],
                ),
            )
            db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,1,?)",
                (other["task_id"], json.dumps({"status": "sample_ok"})),
            )
            db.commit()
        finally:
            db.close()
        target = self.private / "same-request-new-epoch.json"
        prepared = helper.prepare_manifest(
            self.root,
            target,
            stage="list",
            release_id=self.release_id,
            release_manifest_sha256=self.release_sha,
            authority_config_sha256=self.config_sha,
            code_sha256_pin=self.code_sha,
            snapshot_epoch=self.snapshot,
        )
        self.assertEqual(prepared["stage"], "list")

    def test_verified_empty_list_needs_no_member_token_or_http(self):
        list_receipt = self.private / "empty-list-receipt.json"
        self.execute(
            self.list_manifest,
            self.list,
            list_receipt,
            responder=lambda body: self.response(body, names=()),
        )
        members_path, members = self.prepare_members(
            list_receipt, "empty-members-manifest.json"
        )
        self.assertEqual(members["records"], [])
        receipt = self.private / "empty-members-receipt.json"
        with (
            patch.object(helper.pipeline_module, "ROOT", self.root),
            patch.object(helper.pipeline_module, "authority"),
            patch.object(
                helper.pipeline_module,
                "get_secret",
                side_effect=AssertionError("empty member set needs no token"),
            ),
            patch.object(
                helper.httpx,
                "Client",
                side_effect=AssertionError("empty member set needs no HTTP"),
            ),
        ):
            result = helper.run_batch(
                self.root,
                members_path,
                helper.sha(members_path),
                expected_task_ids_sha256=members["all_task_ids_sha256"],
                expected_config_sha256=self.config_sha,
                expected_code_sha256=self.code_sha,
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                receipt_path=receipt,
                execute=True,
            )
        self.assertEqual(result["status"], "verified_empty_list_no_member_calls")
        self.assertEqual(result["upstream_calls"], 0)


if __name__ == "__main__":
    unittest.main()
