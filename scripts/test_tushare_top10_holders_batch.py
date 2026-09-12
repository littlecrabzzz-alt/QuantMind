"""Paired top10 holder exact-batch contracts."""

import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_top10_holders_batch as preparation
import run_tushare_top10_holders_batch as runner


class Top10HolderBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "authority"
        self.output = self.base / "batch.json"
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        self.ids = []
        for code in (
            "600001.SH",
            "000001.SZ",
            "920001.BJ",
            "600002.SH",
            "000002.SZ",
            "920002.BJ",
        ):
            for api in preparation.APIS:
                self.ids.append(
                    pipeline.enqueue(
                        api,
                        {
                            "ts_code": code,
                            "start_date": "20250101",
                            "end_date": "20251231",
                        },
                        40,
                        "history",
                    )
                )
        self.unrelated = pipeline.enqueue(
            "daily", {"trade_date": "20260911"}, 1, "20260912"
        )
        pipeline.db.commit()
        pipeline.close()
        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").write_text("enabled\n")
        self.config = {
            "rate_policy": "tiered_v1",
            "requests_per_minute": 500,
            "rollout_account_rpm": 500,
        }
        (self.root / "pipeline-config.json").write_bytes(
            json.dumps(self.config, sort_keys=True).encode()
        )
        manifest_bytes = b'{"schema_version":1,"files":{},"datasets":[]}'
        manifest_sha = preparation.digest(manifest_bytes)
        self.release_id = "data-" + manifest_sha
        self.release_sha = manifest_sha
        release_dir = self.root / "releases" / self.release_id
        release_dir.mkdir(parents=True)
        (release_dir / "manifest.json").write_bytes(manifest_bytes)
        self.pointer = {"manifest_sha256": manifest_sha, "release_id": self.release_id}
        (self.root / "CURRENT.json").write_bytes(preparation.json_bytes(self.pointer))
        self.manifest = preparation.prepare(
            self.root,
            self.output,
            "history",
            self.release_id,
            self.release_sha,
            pair_count=3,
        )
        self.manifest_sha = preparation.sha(self.output)

    def test_prepare_selects_complete_market_balanced_pristine_pairs_and_pins_sources(
        self,
    ):
        self.assertEqual(
            self.manifest["api_counts"], {"top10_floatholders": 3, "top10_holders": 3}
        )
        self.assertEqual(self.manifest["selected"]["pair_count"], 3)
        markets = {
            row["job"]["params"]["ts_code"].split(".")[1]
            for row in self.manifest["records"]
        }
        self.assertEqual(markets, {"SH", "SZ", "BJ"})
        self.assertEqual(
            {row["state"] for row in self.manifest["records"]}, {"pending"}
        )
        self.assertEqual({row["tries"] for row in self.manifest["records"]}, {0})
        self.assertEqual({row["attempts"] for row in self.manifest["records"]}, {0})
        source = self.manifest["source"]
        self.assertEqual(source["release_id"], self.release_id)
        self.assertEqual(source["release_manifest_sha256"], self.release_sha)
        self.assertEqual(
            source["authority_config_sha256"],
            preparation.sha(self.root / "pipeline-config.json"),
        )
        self.assertEqual(set(source["code_sha256"]), set(preparation.CODE_PATHS))
        with closing(sqlite3.connect(self.root / "pipeline.sqlite")) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE state='pending'"
                ).fetchone()[0],
                13,
            )

    def test_prepare_excludes_incomplete_and_cross_epoch_semantic_peers(self):
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config/tushare-catalog.json"
            ).read_bytes()
        )
        pipeline = runner.pipeline_module.Pipeline(self.root, catalog)
        for api in preparation.APIS:
            pipeline.enqueue(
                api,
                {
                    "ts_code": "600001.SH",
                    "start_date": "20250101",
                    "end_date": "20251231",
                },
                40,
                "20260912",
            )
        pipeline.enqueue(
            "top10_holders",
            {"ts_code": "300001.SZ", "start_date": "20240101", "end_date": "20241231"},
            40,
            "history",
        )
        pipeline.db.commit()
        pipeline.close()
        another = self.base / "filtered.json"
        result = preparation.prepare(
            self.root,
            another,
            "history",
            self.release_id,
            self.release_sha,
            pair_count=3,
        )
        codes = {r["job"]["params"]["ts_code"] for r in result["records"]}
        self.assertNotIn("600001.SH", codes)
        self.assertNotIn("300001.SZ", codes)

    def test_history_manifest_excludes_prior_selection(self):
        second = self.base / "second.json"
        value = preparation.prepare(
            self.root,
            second,
            "history",
            self.release_id,
            self.release_sha,
            pair_count=2,
            history_manifests=[self.output],
        )
        first = {row["task_id"] for row in self.manifest["records"]}
        later = {row["task_id"] for row in value["records"]}
        self.assertFalse(first & later)
        self.assertEqual(
            value["source"]["history_manifest_sha256"], [self.manifest_sha]
        )

    def test_manifest_rejects_nonpristine_false_invalid_window_and_incomplete_pair(
        self,
    ):
        for mutate, message in (
            (lambda x: x["records"][0].__setitem__("tries", False), "non-pristine"),
            (
                lambda x: x["records"][0]["job"]["params"].__setitem__(
                    "end_date", "20250230"
                ),
                "end_date",
            ),
            (lambda x: x["records"].pop(), "Invalid batch source"),
        ):
            data = json.loads(self.output.read_bytes())
            mutate(data)
            path = self.base / (message.replace(" ", "-") + ".json")
            path.write_bytes(preparation.json_bytes(data))
            with self.assertRaisesRegex(ValueError, message):
                preparation.verify_manifest(path, preparation.sha(path))

    def test_plan_only_is_offline_and_hash_pinned(self):
        moved = self.base / "authority-unavailable"
        self.root.rename(moved)
        result = runner.run_batch(self.output, self.manifest_sha)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 6)
        self.assertEqual(result["max_upstream_calls"], 6)
        self.assertFalse(result["would_access_authority"])
        self.assertFalse(result["would_access_credentials"])
        self.assertFalse(result["would_call_upstream"])
        self.assertFalse(result["would_write"])
        self.assertFalse(result["would_publish"])
        with self.assertRaisesRegex(ValueError, "Request limit must equal"):
            runner.run_batch(self.output, self.manifest_sha, max_requests=5)
        with self.assertRaisesRegex(ValueError, "helper hash"):
            runner.run_batch(
                self.output, self.manifest_sha, expected_helper_sha256="0" * 64
            )

    def test_execute_rechecks_pristine_pins_and_only_passes_exact_task_ids(self):
        calls = {}

        def fake_run(_pipeline, _client, _token, _config, **kwargs):
            calls.update(kwargs)
            return {
                "requests": 0,
                "elapsed_seconds": 0.01,
                "exact_task_scope": {"enabled": True, "tasks": len(kwargs["task_ids"])},
            }

        disk = shutil.disk_usage(self.root)
        abundant = type(disk)(disk.total, disk.used, runner.MIN_FREE_BYTES + 1)
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                return_value="synthetic-noncredential",
            ),
            patch.object(runner.shutil, "disk_usage", return_value=abundant),
            patch.object(runner.httpx, "Client") as client,
            patch.object(runner.pipeline_module.Pipeline, "run", new=fake_run),
        ):
            client.return_value.__enter__.return_value = object()
            receipt = runner.run_batch(
                self.output,
                self.manifest_sha,
                expected_task_ids_sha256=self.manifest["all_task_ids_sha256"],
                expected_config_sha256=self.manifest["source"][
                    "authority_config_sha256"
                ],
                expected_helper_sha256=runner.helper_sha256(),
                expected_preparation_sha256=runner.preparation_sha256(),
                expected_release_id=self.release_id,
                expected_release_manifest_sha256=self.release_sha,
                root=self.root,
                max_requests=6,
                execute=True,
            )
        self.assertEqual(
            set(calls["task_ids"]), {row["task_id"] for row in self.manifest["records"]}
        )
        self.assertNotIn(self.unrelated, calls["task_ids"])
        self.assertEqual(calls["max_requests"], 6)
        self.assertFalse(receipt["release_published"])
        self.assertFalse(receipt["current_release_switched"])
        self.assertNotIn("synthetic-noncredential", json.dumps(receipt))

    def test_execute_refuses_to_create_missing_lock_and_rejects_changed_task(self):
        self.assertTrue((self.root / "pipeline.lock").unlink() is None)
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "pipeline lock"):
                runner.run_batch(
                    self.output,
                    self.manifest_sha,
                    expected_task_ids_sha256=self.manifest["all_task_ids_sha256"],
                    expected_config_sha256=self.manifest["source"][
                        "authority_config_sha256"
                    ],
                    expected_helper_sha256=runner.helper_sha256(),
                    expected_preparation_sha256=runner.preparation_sha256(),
                    expected_release_id=self.release_id,
                    expected_release_manifest_sha256=self.release_sha,
                    root=self.root,
                    max_requests=6,
                    execute=True,
                )
        self.assertFalse((self.root / "pipeline.lock").exists())

    def test_execute_rejects_task_that_is_no_longer_pristine(self):
        task_id = self.manifest["records"][0]["task_id"]
        with closing(sqlite3.connect(self.root / "pipeline.sqlite")) as db:
            with db:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (task_id,))
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority", return_value=None),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("secret must follow pristine gate"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no longer pristine"):
                runner.run_batch(
                    self.output,
                    self.manifest_sha,
                    expected_task_ids_sha256=self.manifest["all_task_ids_sha256"],
                    expected_config_sha256=self.manifest["source"][
                        "authority_config_sha256"
                    ],
                    expected_helper_sha256=runner.helper_sha256(),
                    expected_preparation_sha256=runner.preparation_sha256(),
                    expected_release_id=self.release_id,
                    expected_release_manifest_sha256=self.release_sha,
                    root=self.root,
                    max_requests=6,
                    execute=True,
                )


if __name__ == "__main__":
    unittest.main()
