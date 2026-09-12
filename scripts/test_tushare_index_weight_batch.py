"""Index-weight batches pin existing history and preserve research boundaries."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_index_weight_batch as preparation
import run_tushare_index_weight_batch as runner


class IndexWeightBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "authority"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.history = []
        for code in ("000001.SH", "000300.SH", "000905.SH", "000985.CSI"):
            for month in ("202606", "202607", "202608"):
                self.history.append(
                    pipeline.enqueue(
                        preparation.API,
                        {
                            "index_code": code,
                            "start_date": month + "01",
                            "end_date": month + ("30" if month == "202606" else "31"),
                        },
                        priority=45,
                        epoch=preparation.EPOCH,
                    )
                )
        parent = pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (self.history[2],)
        ).fetchone()
        pipeline.split_request(parent, json.loads(parent["job"]))
        pipeline.db.execute(
            "UPDATE jobs SET state='split_pending' WHERE id=?", (self.history[2],)
        )
        self.split_children = {
            child[0]
            for child in pipeline.db.execute(
                "SELECT child_id FROM partition_children WHERE parent_id=?",
                (self.history[2],),
            )
        }
        self.recent = pipeline.enqueue(
            preparation.API,
            {
                "index_code": "399001.SZ",
                "start_date": "20260902",
                "end_date": "20260908",
            },
            priority=25,
            epoch="20260909",
        )
        self.unrelated = pipeline.enqueue(
            "fund_nav",
            {
                "ts_code": "510300.SH",
                "start_date": "20260801",
                "end_date": "20260831",
            },
            priority=1,
            epoch=preparation.EPOCH,
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "ENABLED").write_text("enabled\n")
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
        }
        self.config_path = self.root / "pipeline-config.json"
        self.config_path.write_text(json.dumps(self.config))
        (self.root / "pipeline.lock").touch()
        release_bytes = runner.json_bytes({"files": {}, "schema_version": 1})
        self.release_sha = runner.digest(release_bytes)
        self.release_id = "data-" + self.release_sha
        release_path = self.root / "releases" / self.release_id / "manifest.json"
        release_path.parent.mkdir(parents=True)
        release_path.write_bytes(release_bytes)
        (self.root / "CURRENT.json").write_bytes(
            runner.json_bytes(
                {
                    "manifest_sha256": self.release_sha,
                    "release_id": self.release_id,
                }
            )
        )
        self.manifest = self.base / "batch.json"
        preparation.prepare(
            self.root,
            self.manifest,
            self.release_id,
            self.release_sha,
            batch_jobs=6,
        )
        self.manifest_sha = preparation.sha(self.manifest)
        self.verified = preparation.verify_manifest(self.manifest, self.manifest_sha)

    def execution_pins(self):
        source = self.verified["source"]
        return {
            "expected_task_ids_sha256": self.verified["all_task_ids_sha256"],
            "expected_config_sha256": runner.sha(self.config_path),
            "expected_helper_sha256": runner.helper_sha256(),
            "expected_preparation_sha256": runner.preparation_sha256(),
            "expected_release_id": self.release_id,
            "expected_release_manifest_sha256": self.release_sha,
            "expected_history_inventory_sha256": source["history_inventory"][
                "inventory_sha256"
            ],
            "expected_descendant_inventory_sha256": source["descendant_inventory"][
                "inventory_sha256"
            ],
        }

    def prepare(self, output, batch_jobs=6):
        return preparation.prepare(
            self.root,
            output,
            self.release_id,
            self.release_sha,
            batch_jobs=batch_jobs,
        )

    def test_prepare_is_read_only_recent_index_fair_and_history_only(self):
        records = self.verified["records"]
        per_code = {}
        for record in records:
            params = record["job"]["params"]
            per_code.setdefault(params["index_code"], []).append(params["end_date"])
            self.assertEqual(record["epoch"], preparation.EPOCH)
            self.assertEqual(
                {
                    key: record[key]
                    for key in ("state", "tries", "result", "attempts", "parent_count")
                },
                {
                    "state": "pending",
                    "tries": 0,
                    "result": None,
                    "attempts": 0,
                    "parent_count": 0,
                },
            )
        self.assertEqual(
            set(per_code), {"000001.SH", "000300.SH", "000905.SH", "000985.CSI"}
        )
        self.assertEqual(sorted(map(len, per_code.values())), [1, 1, 2, 2])
        self.assertTrue(
            self.split_children.isdisjoint(record["task_id"] for record in records)
        )
        self.assertEqual(max(per_code["000001.SH"]), "20260731")
        self.assertEqual(self.verified["source"]["selection"], preparation.SELECTION)
        self.assertEqual(self.verified["source"]["release_id"], self.release_id)
        self.assertEqual(
            self.verified["source"]["release_manifest_sha256"], self.release_sha
        )
        self.assertEqual(
            self.verified["source"]["preparation_sha256"],
            preparation.preparation_sha256(),
        )
        self.assertEqual(self.verified["source"]["descendant_inventory"]["tasks"], 2)
        self.assertEqual(self.verified["boundaries"], preparation.BOUNDARIES)
        self.assertFalse(self.verified["boundaries"]["known_at_verified"])
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (self.recent,)
                ).fetchone()[0],
                "pending",
            )
        finally:
            db.close()

    def test_plan_only_verifies_hashes_without_authority_credentials_or_network(self):
        before = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        with (
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credential access"),
            ),
            patch.object(
                runner.httpx,
                "Client",
                side_effect=AssertionError("upstream access"),
            ),
        ):
            result = runner.run_batch(self.manifest, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["api_counts"], {preparation.API: 6})
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])
        self.assertEqual(result["release_id"], self.release_id)
        self.assertEqual(result["preparation_sha256"], runner.preparation_sha256())
        self.assertEqual(
            before,
            {
                path.relative_to(self.root): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
        )
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            runner.run_batch(self.manifest, "0" * 64)

    def test_manifest_rejects_boundary_promotion_and_bad_leaf(self):
        value = json.loads(self.manifest.read_bytes())
        value["boundaries"]["known_at_verified"] = True
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid batch manifest"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

    def test_manifest_rejects_pinned_partial_month_root(self):
        value = json.loads(self.manifest.read_bytes())
        record = value["records"][0]
        record["job"]["params"]["end_date"] = str(
            int(record["job"]["params"]["end_date"]) - 1
        )
        record["logical_key"] = runner.digest(runner.json_bytes(record["job"]))
        record["task_id"] = runner.digest(
            runner.json_bytes([record["logical_key"], record["epoch"]])
        )
        value["all_task_ids_sha256"] = runner.digest(
            runner.json_bytes(sorted(row["task_id"] for row in value["records"]))
        )
        value["all_logical_keys_sha256"] = runner.digest(
            runner.json_bytes(sorted(row["logical_key"] for row in value["records"]))
        )
        value["all_request_signatures_sha256"] = runner.digest(
            runner.json_bytes(
                sorted(
                    preparation.request_signature(row["job"])
                    for row in value["records"]
                )
            )
        )
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "non-full-month"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

    def test_manifest_rejects_boolean_pristine_counters(self):
        value = json.loads(self.manifest.read_bytes())
        value["source"]["tries"] = False
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid pinned batch source"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

        value["source"]["tries"] = 0
        value["records"][0]["attempts"] = False
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "non-pristine"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

    def test_manifest_keeps_legacy_selection_compatible(self):
        value = json.loads(self.manifest.read_bytes())
        value["records"] = [
            {
                key: item
                for key, item in record.items()
                if key not in {"state", "tries", "result", "attempts", "parent_count"}
            }
            for record in value["records"]
        ]
        value["source"] = {
            "api_name": preparation.API,
            "epoch": preparation.EPOCH,
            "state": "pending",
            "pending_jobs": 11,
            "pending_indexes": 4,
            "selection": preparation.LEGACY_SELECTION,
        }
        value.pop("all_logical_keys_sha256")
        value.pop("all_request_signatures_sha256")
        value["selected"] = preparation._selected_stats(value["records"])
        self.manifest.write_bytes(runner.json_bytes(value))
        preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))
        plan = runner.run_batch(self.manifest, preparation.sha(self.manifest))
        self.assertEqual(plan["status"], "plan_only")
        self.assertNotIn("release_id", plan)
        self.assertNotIn("preparation_sha256", plan)
        value["source"]["pending_jobs"] = True
        self.manifest.write_bytes(runner.json_bytes(value))
        with self.assertRaisesRegex(ValueError, "Invalid legacy batch selection"):
            preparation.verify_manifest(self.manifest, preparation.sha(self.manifest))

    def test_prepare_never_falls_back_to_split_descendants_when_roots_are_exhausted(
        self,
    ):
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            db.execute(
                "UPDATE jobs SET state='done' WHERE epoch=? "
                "AND json_extract(job,'$.api_name')=? "
                "AND id NOT IN (SELECT child_id FROM partition_children)",
                (preparation.EPOCH, preparation.API),
            )
            db.commit()
        finally:
            db.close()
        fallback = self.base / "fallback.json"
        with self.assertRaisesRegex(ValueError, "Insufficient pristine parentless"):
            self.prepare(fallback, batch_jobs=2)
        self.assertFalse(fallback.exists())

    def test_history_task_logical_or_request_overlap_excludes_each_root(self):
        original = self.verified["records"][:3]
        rows = []
        for index, record in enumerate(original):
            row = json.loads(json.dumps(record))
            if index == 0:
                row["logical_key"] = "task-only-logical"
                row["job"]["params"]["start_date"] = "20260501"
            elif index == 1:
                row["task_id"] = "logical-only-task"
                row["job"]["params"]["start_date"] = "20260501"
            else:
                row["task_id"] = "request-only-task"
                row["logical_key"] = "request-only-logical"
            rows.append(row)
        archived = (
            self.root / "validation/index-weight-batch-fixture/batch-99-manifest.json"
        )
        archived.parent.mkdir(parents=True)
        archived.write_bytes(runner.json_bytes({"records": rows}))
        candidate = self.base / "history-filtered.json"
        result = self.prepare(candidate, batch_jobs=6)
        selected = {record["task_id"] for record in result["records"]}
        self.assertTrue(selected.isdisjoint(record["task_id"] for record in original))
        self.assertEqual(result["source"]["history_inventory"]["tasks"], 3)
        self.assertEqual(result["source"]["history_inventory"]["logical_keys"], 3)
        self.assertEqual(result["source"]["history_inventory"]["requests"], 3)

    def test_recursive_descendant_logical_overlap_excludes_root(self):
        target = self.verified["records"][0]
        pipeline = runner.pipeline_module.Pipeline(
            self.root,
            json.loads(
                (
                    Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
                ).read_bytes()
            ),
        )
        try:
            middle = pipeline.enqueue(
                preparation.API,
                {
                    "index_code": "399006.SZ",
                    "start_date": "20260101",
                    "end_date": "20260131",
                },
                priority=1,
                epoch="fixture-child",
            )
            grandchild = pipeline.enqueue(
                preparation.API,
                target["job"]["params"],
                priority=1,
                epoch="fixture-grandchild",
            )
            pipeline.db.executemany(
                "INSERT INTO partition_children(parent_id,child_id) VALUES (?,?)",
                ((self.history[0], middle), (middle, grandchild)),
            )
            pipeline.db.commit()
        finally:
            pipeline.close()
        candidate = self.base / "descendant-filtered.json"
        result = self.prepare(candidate, batch_jobs=6)
        self.assertNotIn(target["task_id"], {r["task_id"] for r in result["records"]})
        self.assertIn(
            grandchild,
            preparation.descendant_inventory(self._read_db())[1],
        )

    def test_execute_rejects_config_and_release_drift_before_credentials(self):
        def execute(**overrides):
            pins = self.execution_pins()
            pins.update(overrides)
            with (
                patch.object(runner.pipeline_module, "ROOT", self.root),
                patch.object(runner.pipeline_module, "authority", return_value=None),
                patch.object(
                    runner.pipeline_module,
                    "get_secret",
                    side_effect=AssertionError("credential access"),
                ),
                patch.object(
                    runner.httpx,
                    "Client",
                    side_effect=AssertionError("upstream access"),
                ),
            ):
                return runner.run_batch(
                    self.manifest,
                    self.manifest_sha,
                    **pins,
                    root=self.root,
                    execute=True,
                )

        with self.assertRaisesRegex(ValueError, "config hash mismatch"):
            execute(expected_config_sha256="0" * 64)
        current = self.root / "CURRENT.json"
        original = current.read_bytes()
        current.write_bytes(
            runner.json_bytes(
                {"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64}
            )
        )
        try:
            with self.assertRaisesRegex(ValueError, "not the current fixed release"):
                execute()
        finally:
            current.write_bytes(original)
        release = self.root / "releases" / self.release_id / "manifest.json"
        release_bytes = release.read_bytes()
        release.write_bytes(release_bytes + b"\n")
        try:
            with self.assertRaisesRegex(ValueError, "Release manifest hash mismatch"):
                execute()
        finally:
            release.write_bytes(release_bytes)

        lock = self.root / "pipeline.lock"
        lock.unlink()
        with self.assertRaisesRegex(ValueError, "pipeline lock must be a regular file"):
            execute()
        self.assertFalse(lock.exists())

    def test_execute_rejects_history_inventory_drift_before_credentials(self):
        archived = (
            self.root
            / "validation/index-weight-descendant-batch-fixture/batch-1-manifest.json"
        )
        archived.parent.mkdir(parents=True)
        archived.write_bytes(
            runner.json_bytes({"records": [self.verified["records"][0]]})
        )
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credential access"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                runner.run_batch(
                    self.manifest,
                    self.manifest_sha,
                    **self.execution_pins(),
                    root=self.root,
                    execute=True,
                )

    def test_execute_rejects_recursive_descendant_drift_before_credentials(self):
        pipeline = runner.pipeline_module.Pipeline(
            self.root,
            json.loads(
                (
                    Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
                ).read_bytes()
            ),
        )
        try:
            child = pipeline.enqueue(
                preparation.API,
                {
                    "index_code": "399006.SZ",
                    "start_date": "20260201",
                    "end_date": "20260228",
                },
                priority=1,
                epoch="fixture-child",
            )
            pipeline.db.execute(
                "INSERT INTO partition_children(parent_id,child_id) VALUES (?,?)",
                (self.history[0], child),
            )
            pipeline.db.commit()
        finally:
            pipeline.close()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credential access"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "descendant inventory changed"):
                runner.run_batch(
                    self.manifest,
                    self.manifest_sha,
                    **self.execution_pins(),
                    root=self.root,
                    execute=True,
                )

    def test_execute_rejects_eligible_root_drift_before_credentials(self):
        pipeline = runner.pipeline_module.Pipeline(
            self.root,
            json.loads(
                (
                    Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
                ).read_bytes()
            ),
        )
        try:
            pipeline.enqueue(
                preparation.API,
                {
                    "index_code": "399999.SZ",
                    "start_date": "20260101",
                    "end_date": "20260131",
                },
                priority=1,
                epoch=preparation.EPOCH,
            )
            pipeline.db.commit()
        finally:
            pipeline.close()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("credential access"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Eligible root inventory changed"):
                runner.run_batch(
                    self.manifest,
                    self.manifest_sha,
                    **self.execution_pins(),
                    root=self.root,
                    execute=True,
                )

    def test_execute_is_exact_bounded_and_does_not_publish(self):
        calls = []

        def respond(request):
            body = json.loads(request.content)
            calls.append(body["api_name"])
            fields = body["fields"].split(",")
            return httpx.Response(
                200, json={"code": 0, "data": {"fields": fields, "items": []}}
            )

        client = httpx.Client(transport=httpx.MockTransport(respond))
        pointer = (self.root / "CURRENT.json").read_bytes()
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(runner.pipeline_module, "get_secret", return_value="fixture"),
            patch.object(runner.httpx, "Client", return_value=client),
        ):
            result = runner.run_batch(
                self.manifest,
                self.manifest_sha,
                **self.execution_pins(),
                root=self.root,
                max_requests=3,
                max_seconds=10,
                execute=True,
            )
        self.assertEqual(calls, [preparation.API] * 3)
        self.assertEqual(result["upstream_calls"], 3)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual(result["release_id"], self.release_id)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), pointer)
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        try:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM jobs WHERE id=?", (self.unrelated,)
                ).fetchone()[0],
                "pending",
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE job_id=?", (self.unrelated,)
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_bounds_and_execute_pins_are_mandatory(self):
        with self.assertRaisesRegex(ValueError, "1 to 360"):
            runner.run_batch(self.manifest, self.manifest_sha, max_requests=361)
        with self.assertRaisesRegex(ValueError, "at most 90"):
            runner.run_batch(self.manifest, self.manifest_sha, max_seconds=91)
        with self.assertRaisesRegex(ValueError, "Execute requires every root"):
            runner.run_batch(self.manifest, self.manifest_sha, execute=True)
        with self.assertRaisesRegex(ValueError, "helper hash mismatch"):
            runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_helper_sha256="0" * 64,
            )
        with self.assertRaisesRegex(ValueError, "preparation hash mismatch"):
            runner.run_batch(
                self.manifest,
                self.manifest_sha,
                expected_preparation_sha256="0" * 64,
            )

    def _read_db(self):
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db


if __name__ == "__main__":
    unittest.main()
