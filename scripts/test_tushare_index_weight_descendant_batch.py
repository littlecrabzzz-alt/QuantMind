"""Exact index_weight descendants preserve complete date-split sibling pairs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from scripts import prepare_tushare_index_weight_descendant_batch as preparation  # noqa: E402
from scripts import run_tushare_index_weight_descendant_batch as runner  # noqa: E402


class IndexWeightDescendantBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.authority = self.base / "authority"
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        pipeline = runner.pipeline_module.Pipeline(self.authority, catalog)
        self.parents = []
        for code in ("000001.SH", "000300.SH", "000905.SH", "000985.CSI"):
            self.parents.append(
                pipeline.enqueue(
                    "index_weight",
                    {
                        "index_code": code,
                        "start_date": "20260801",
                        "end_date": "20260831",
                    },
                    priority=45,
                    epoch="history",
                )
            )
        pipeline.db.commit()
        pipeline.close()

        pipeline = runner.pipeline_module.Pipeline(self.authority, catalog)
        self.children_by_parent = {}
        for parent_id in self.parents:
            parent = pipeline.db.execute(
                "SELECT * FROM jobs WHERE id=?", (parent_id,)
            ).fetchone()
            job = json.loads(parent["job"])
            split = pipeline.split_request(parent, job)
            children = [
                row[0]
                for row in pipeline.db.execute(
                    "SELECT child_id FROM partition_children WHERE parent_id=? "
                    "ORDER BY child_id",
                    (parent_id,),
                )
            ]
            self.assertEqual(len(children), 2)
            self.children_by_parent[parent_id] = children
            result = {
                "api_name": "index_weight",
                "status": "possibly_truncated",
                "row_count": 1000,
                "http_status": 200,
                "response_complete": True,
                "supplier_has_more": False,
                "split": split,
            }
            encoded = json.dumps(result, sort_keys=True)
            pipeline.db.execute(
                "UPDATE jobs SET state='split_pending',tries=1,result=? WHERE id=?",
                (encoded, parent_id),
            )
            pipeline.db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,1,?)",
                (parent_id, encoded),
            )
            pipeline.db.execute(
                "UPDATE partition_splits SET status='gap',gap='child_not_verified' "
                "WHERE parent_id=?",
                (parent_id,),
            )
        pipeline.db.commit()
        pipeline.close()
        (self.authority / "pipeline.lock").touch()

        release_manifest = json_bytes({"schema_version": 1, "files": {}})
        self.release_sha = hashlib.sha256(release_manifest).hexdigest()
        self.release_id = "data-" + self.release_sha
        release_dir = self.authority / "releases" / self.release_id
        release_dir.mkdir(parents=True)
        (release_dir / "manifest.json").write_bytes(release_manifest)
        (self.authority / "CURRENT.json").write_bytes(
            json_bytes(
                {
                    "manifest_sha256": self.release_sha,
                    "release_id": self.release_id,
                }
            )
        )
        (self.authority / "ENABLED").write_text("enabled\n")
        self.config_path = self.authority / "pipeline-config.json"
        self.config_path.write_bytes(
            json_bytes(
                {
                    "rate_policy": "tiered_v1",
                    "requests_per_minute": 500,
                    "rollout_account_rpm": 500,
                }
            )
        )
        self.manifest_path = self.base / "descendants.json"

    def prepare(self, *, output=None, batch_jobs=4):
        output = output or self.manifest_path
        return preparation.prepare(
            root=self.authority,
            output=output,
            release_id=self.release_id,
            release_manifest_sha256=self.release_sha,
            jobs=batch_jobs,
        )

    def plan(self, manifest=None, **overrides):
        manifest = manifest or self.manifest_path
        arguments = {
            "manifest": manifest,
            "manifest_sha256": preparation.sha(manifest),
            "root": self.authority,
            "max_requests": len(json.loads(manifest.read_bytes())["records"]),
            "max_seconds": 10,
        }
        arguments.update(overrides)
        return runner.run_batch(**arguments)

    def execute(self, handler, manifest=None, **overrides):
        manifest = manifest or self.manifest_path
        value = json.loads(manifest.read_bytes())
        pipeline = runner.pipeline_module.Pipeline(
            self.authority,
            json.loads((ROOT / "config/tushare-catalog.json").read_bytes()),
        )
        try:
            parent_ids = [pair["parent"]["task_id"] for pair in value["pairs"]]
            graph_sha = runner._graph_snapshot(pipeline.db, parent_ids)["sha256"]
        finally:
            pipeline.close()
        arguments = {
            "expected_task_ids_sha256": value["all_task_ids_sha256"],
            "expected_pair_set_sha256": value["pair_set_sha256"],
            "expected_config_sha256": runner.sha(self.config_path),
            "expected_helper_sha256": runner.helper_sha256(),
            "expected_preparation_sha256": runner.preparation_sha256(),
            "expected_release_id": self.release_id,
            "expected_release_manifest_sha256": self.release_sha,
            "expected_history_inventory_sha256": value["source"][
                "history_inventory"
            ]["inventory_sha256"],
            "expected_graph_sha256": graph_sha,
            "execute": True,
        }
        arguments.update(overrides)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with (
            patch.object(runner.pipeline_module, "ROOT", self.authority),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.httpx, "Client", return_value=client),
        ):
            return self.plan(manifest, **arguments)

    def selected_ids(self, manifest):
        return {record["task_id"] for record in manifest["records"]}

    def assert_complete_pairs(self, manifest):
        selected = self.selected_ids(manifest)
        self.assertEqual(len(selected), len(manifest["records"]))
        self.assertEqual(len(manifest["records"]), 2 * len(manifest["pairs"]))
        for pair in manifest["pairs"]:
            task_ids = {row["task_id"] for row in pair["children"]}
            parent_id = pair["parent"]["task_id"]
            self.assertEqual(len(task_ids), 2)
            self.assertEqual(task_ids, set(self.children_by_parent[parent_id]))
            self.assertTrue(task_ids <= selected)

    def test_prepare_selects_only_complete_pristine_exact_sibling_pairs(self):
        manifest = self.prepare()
        self.assert_complete_pairs(manifest)
        self.assertEqual(len(manifest["records"]), 4)
        self.assertEqual(manifest["source"]["release_id"], self.release_id)
        self.assertEqual(
            manifest["source"]["release_manifest_sha256"], self.release_sha
        )
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            for task_id in self.selected_ids(manifest):
                state, tries, result = db.execute(
                    "SELECT state,tries,result FROM jobs WHERE id=?", (task_id,)
                ).fetchone()
                self.assertEqual((state, tries, result), ("pending", 0, None))
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM attempts WHERE job_id=?", (task_id,)
                    ).fetchone()[0],
                    0,
                )
        finally:
            db.close()

    def test_batch_size_must_be_even_and_at_most_360(self):
        with self.assertRaisesRegex(ValueError, "even|pair"):
            self.prepare(output=self.base / "odd.json", batch_jobs=3)
        with self.assertRaisesRegex(ValueError, "360"):
            self.prepare(output=self.base / "large.json", batch_jobs=362)

    def test_parent_split_contract_fails_closed(self):
        parent = self.parents[0]
        cases = (
            ("UPDATE jobs SET state='done' WHERE id=?", (parent,)),
            (
                "UPDATE jobs SET result=json_set(result,'$.status','sample_ok') WHERE id=?",
                (parent,),
            ),
            (
                "UPDATE partition_splits SET method='identifier_fanout' WHERE parent_id=?",
                (parent,),
            ),
            (
                "UPDATE partition_splits SET expected_children=1 WHERE parent_id=?",
                (parent,),
            ),
            (
                "UPDATE partition_splits SET coverage_proven=0 WHERE parent_id=?",
                (parent,),
            ),
        )
        original = (self.authority / "pipeline.sqlite").read_bytes()
        for index, (sql, params) in enumerate(cases):
            with self.subTest(case=index):
                (self.authority / "pipeline.sqlite").write_bytes(original)
                db = sqlite3.connect(self.authority / "pipeline.sqlite")
                db.execute(sql, params)
                db.commit()
                db.close()
                with self.assertRaises(ValueError):
                    self.prepare(output=self.base / f"bad-parent-{index}.json", batch_jobs=8)
        (self.authority / "pipeline.sqlite").write_bytes(original)

    def test_child_must_be_exact_pristine_single_parent(self):
        parent = self.parents[0]
        child = self.children_by_parent[parent][0]
        original = (self.authority / "pipeline.sqlite").read_bytes()

        def attempted(db):
            db.execute("UPDATE jobs SET tries=1,result='{}' WHERE id=?", (child,))
            db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,1,'{}')", (child,)
            )

        def shared(db):
            db.execute(
                "INSERT INTO partition_children(parent_id,child_id) VALUES(?,?)",
                (self.parents[1], child),
            )

        def wrong_range(db):
            job = json.loads(
                db.execute("SELECT job FROM jobs WHERE id=?", (child,)).fetchone()[0]
            )
            job["params"]["start_date"] = "20260701"
            db.execute("UPDATE jobs SET job=? WHERE id=?", (json.dumps(job), child))

        for name, mutate in (("attempted", attempted), ("shared", shared), ("range", wrong_range)):
            with self.subTest(case=name):
                (self.authority / "pipeline.sqlite").write_bytes(original)
                db = sqlite3.connect(self.authority / "pipeline.sqlite")
                mutate(db)
                db.commit()
                db.close()
                with self.assertRaises(ValueError):
                    self.prepare(output=self.base / f"bad-child-{name}.json", batch_jobs=8)
        (self.authority / "pipeline.sqlite").write_bytes(original)

    def test_history_task_logical_or_request_overlap_excludes_whole_pair(self):
        first = self.prepare(output=self.base / "first.json", batch_jobs=2)
        excluded = first["pairs"][0]
        excluded_ids = {row["task_id"] for row in excluded["children"]}
        original = first["records"][0]
        history_dir = self.authority / "validation/index-weight-descendant-batch-fixture"

        def changed_request():
            job = json.loads(json.dumps(original["job"]))
            job["params"]["fixture_nonce"] = "different-request"
            return job

        histories = {
            "task": {
                "task_id": original["task_id"],
                "logical_key": "f" * 64,
                "job": changed_request(),
            },
            "logical": {
                "task_id": "e" * 64,
                "logical_key": original["logical_key"],
                "job": changed_request(),
            },
            "request": {
                "task_id": "d" * 64,
                "logical_key": "c" * 64,
                "job": original["job"],
            },
        }
        for _index, (identity, record) in enumerate(histories.items()):
            with self.subTest(identity=identity):
                history_dir.mkdir(parents=True, exist_ok=True)
                history = history_dir / f"batch-{identity}-manifest.json"
                history.write_bytes(json_bytes({"records": [record]}))
                selected = self.prepare(
                    output=self.base / f"after-{identity}.json", batch_jobs=2
                )
                self.assertTrue(excluded_ids.isdisjoint(self.selected_ids(selected)))
                self.assert_complete_pairs(selected)
                history.unlink()

    def test_plan_only_is_read_only_and_offline(self):
        self.prepare()
        before = {
            str(path.relative_to(self.authority)): path.read_bytes()
            for path in self.authority.rglob("*")
            if path.is_file()
        }
        with (
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("plan read credentials"),
            ),
            patch(
                "backend.shared.runtime_secrets.get_secret",
                side_effect=AssertionError("plan read credentials"),
            ),
            patch("socket.socket.connect", side_effect=AssertionError("plan network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("plan network")),
        ):
            plan = self.plan()
        self.assertEqual(plan["status"], "plan_only")
        self.assertFalse(plan["would_access_credentials"])
        self.assertFalse(plan["would_call_upstream"])
        self.assertFalse(plan["would_write"])
        after = {
            str(path.relative_to(self.authority)): path.read_bytes()
            for path in self.authority.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_execute_rejects_every_identity_or_live_drift_before_http(self):
        manifest = self.prepare()
        calls = 0

        def no_http(_request):
            nonlocal calls
            calls += 1
            raise AssertionError("drift must fail before HTTP")

        bad = {
            "expected_task_ids_sha256": "0" * 64,
            "expected_pair_set_sha256": "0" * 64,
            "expected_config_sha256": "0" * 64,
            "expected_helper_sha256": "0" * 64,
            "expected_preparation_sha256": "0" * 64,
        }
        for key, value in bad.items():
            with self.subTest(pin=key), self.assertRaises(ValueError):
                self.execute(no_http, **{key: value})

        manifest_bytes = self.manifest_path.read_bytes()
        self.manifest_path.write_bytes(manifest_bytes + b"\n")
        with self.assertRaises(ValueError):
            runner.run_batch(
                self.manifest_path,
                digest(manifest_bytes),
                root=self.authority,
                max_requests=len(manifest["records"]),
                execute=False,
            )
        self.manifest_path.write_bytes(manifest_bytes)

        pointer = (self.authority / "CURRENT.json").read_bytes()
        (self.authority / "CURRENT.json").write_text('{"release_id":"changed"}\n')
        with self.assertRaises(ValueError):
            self.execute(no_http)
        (self.authority / "CURRENT.json").write_bytes(pointer)

        child = manifest["records"][0]["task_id"]
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        db.execute("UPDATE jobs SET tries=1 WHERE id=?", (child,))
        db.commit()
        db.close()
        with self.assertRaises(ValueError):
            self.execute(no_http)
        self.assertEqual(calls, 0)

    def test_execute_touches_only_selected_tasks_and_never_publishes(self):
        manifest = self.prepare(batch_jobs=2)
        selected = self.selected_ids(manifest)
        unrelated = next(
            child
            for children in self.children_by_parent.values()
            for child in children
            if child not in selected
        )
        calls = []

        def empty(request):
            body = json.loads(request.content)
            calls.append(body["params"])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "fields": body["fields"].split(","),
                        "items": [],
                        "has_more": False,
                    },
                },
            )

        pointer = (self.authority / "CURRENT.json").read_bytes()
        result = self.execute(empty)
        self.assertEqual(result["status"], "exact_descendant_batch_executed")
        self.assertEqual(result["upstream_calls"], 2)
        self.assertEqual(len(calls), 2)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual((self.authority / "CURRENT.json").read_bytes(), pointer)
        self.assertIn("before_graph_sha256", result)
        self.assertIn("after_graph_sha256", result)
        self.assertIsNot(result.get("coverage_complete"), True)
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            attempted = {
                row[0]
                for row in db.execute("SELECT DISTINCT job_id FROM attempts")
                if row[0] not in self.parents
            }
            self.assertEqual(attempted, selected)
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (unrelated,)
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_saturated_children_may_add_grandchildren_but_not_coverage_claim(self):
        manifest = self.prepare(batch_jobs=2)
        selected = self.selected_ids(manifest)

        def saturated(request):
            body = json.loads(request.content)
            fields = body["fields"].split(",")
            values = {
                "index_code": body["params"]["index_code"],
                "con_code": "600000.SH",
                "trade_date": body["params"]["start_date"],
                "weight": 1.0,
            }
            item = [values[field] for field in fields]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"fields": fields, "items": [item] * 1000, "has_more": False},
                },
            )

        result = self.execute(saturated)
        self.assertEqual(result["upstream_calls"], 2)
        self.assertNotEqual(result["before_graph_sha256"], result["after_graph_sha256"])
        self.assertGreater(result["after_graph_tasks"], len(selected))
        self.assertIsNot(result.get("coverage_complete"), True)
        db = sqlite3.connect(self.authority / "pipeline.sqlite")
        try:
            self.assertTrue(
                any(
                    db.execute(
                        "SELECT COUNT(*) FROM partition_children WHERE parent_id=?",
                        (task_id,),
                    ).fetchone()[0]
                    == 2
                    for task_id in selected
                )
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
