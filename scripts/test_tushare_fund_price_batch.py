import json
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from backend.shared.tushare_intake import digest, json_bytes
from scripts import prepare_tushare_fund_price_batch as preparation
from scripts import run_tushare_fund_price_batch as runner


class FundPriceBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "authority"
        self.root.mkdir()
        (self.root / "pipeline.lock").touch()
        (self.root / "ENABLED").touch()
        (self.root / "pipeline-config.json").write_bytes(
            json_bytes({"rate_policy": "tiered_v1"})
        )
        self.calendar_rows = self._calendar_rows()
        self.release_id, self.release_sha, self.parquet_path = self._release()
        self._database()
        self.output = self.base / "batch.json"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _calendar_rows():
        rows = []
        day = date(2025, 1, 1)
        for offset in range(270):
            current = day + timedelta(days=offset)
            rows.append(
                {
                    "cal_date": current.strftime("%Y%m%d"),
                    "exchange": "SSE",
                    "is_open": int(current.weekday() < 5),
                }
            )
        return rows

    def _release(self):
        parquet_dir = self.root / "parquet"
        parquet_dir.mkdir()
        temporary = parquet_dir / "calendar.tmp"
        pq.write_table(pa.Table.from_pylist(self.calendar_rows), temporary)
        parquet_sha = digest(temporary.read_bytes())
        parquet_path = parquet_dir / f"{parquet_sha}.parquet"
        temporary.rename(parquet_path)
        relative = f"parquet/{parquet_path.name}"
        manifest = {
            "datasets": [
                {
                    "api_name": "trade_cal",
                    "path": relative,
                    "sha256": parquet_sha,
                    "bytes": parquet_path.stat().st_size,
                }
            ],
            "files": {
                relative: {
                    "sha256": parquet_sha,
                    "bytes": parquet_path.stat().st_size,
                }
            },
        }
        manifest_bytes = json_bytes(manifest)
        manifest_sha = digest(manifest_bytes)
        release_id = "data-" + manifest_sha
        release_dir = self.root / "releases" / release_id
        release_dir.mkdir(parents=True)
        (release_dir / "manifest.json").write_bytes(manifest_bytes)
        (self.root / "CURRENT.json").write_bytes(
            json_bytes({"manifest_sha256": manifest_sha, "release_id": release_id})
        )
        return release_id, manifest_sha, parquet_path

    def _database(self):
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        db.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, logical_key TEXT NOT NULL, epoch TEXT NOT NULL,
                job TEXT NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL,
                tries INTEGER NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
                result TEXT, expanded INTEGER NOT NULL DEFAULT 0,
                group_name TEXT NOT NULL DEFAULT 'rrg'
            );
            CREATE TABLE attempts (
                job_id TEXT NOT NULL, attempt INTEGER NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(job_id,attempt)
            );
            PRAGMA user_version=6;
            """
        )
        for row in self.calendar_rows:
            for api in preparation.ALLOWED_APIS:
                self._insert_job(db, api, row["cal_date"], "history")
        open_dates = sorted(
            (row["cal_date"] for row in self.calendar_rows if row["is_open"]),
            reverse=True,
        )
        self._insert_job(db, "fund_daily", open_dates[0], "20250911", "done")
        self._insert_job(
            db, "fund_adj", open_dates[1], "history-page-2", "done", offset=1000
        )
        self._insert_job(
            db,
            "fund_daily",
            open_dates[2],
            "diagnostic-range",
            params={
                "ts_code": "510300.SH",
                "start_date": open_dates[2],
                "end_date": open_dates[2],
            },
        )
        db.commit()
        db.close()
        self.excluded_open_dates = set(open_dates[:2])

    @staticmethod
    def _insert_job(
        db, api, trade_date, epoch, state="pending", tries=0, offset=0, params=None
    ):
        params = dict(params or {"trade_date": trade_date})
        if api == "fund_adj" and "trade_date" in params:
            params.update(offset=offset, limit=1000)
        job = {
            "api_name": api,
            "params": params,
            "fields": "trade_date,ts_code",
            "row_cap": 5000 if api == "fund_daily" else 2000,
            "required_fields": ["ts_code", "trade_date"],
            "nullable_fields": [],
            "positive_fields": [],
        }
        logical_key = digest(json_bytes(job))
        task_id = digest(json_bytes([logical_key, epoch]))
        db.execute(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,"
            "group_name) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                task_id,
                logical_key,
                epoch,
                json.dumps(job, sort_keys=True),
                45,
                state,
                tries,
                "rrg",
            ),
        )

    def _prepare(self):
        return preparation.prepare(
            self.root, self.output, self.release_id, self.release_sha
        )

    def test_prepare_selects_latest_180_common_pristine_open_dates(self):
        manifest = self._prepare()
        selected = manifest["selected"]["trade_dates"]
        expected = sorted(
            (
                row["cal_date"]
                for row in self.calendar_rows
                if row["is_open"]
                and row["cal_date"] not in self.excluded_open_dates
            ),
            reverse=True,
        )[: preparation.DAYS_PER_API]
        self.assertEqual(selected, expected)
        self.assertEqual(len(manifest["records"]), 360)
        self.assertEqual(
            manifest["api_counts"],
            dict.fromkeys(sorted(preparation.ALLOWED_APIS), 180),
        )
        self.assertTrue(all(record["tries"] == 0 for record in manifest["records"]))

    def test_plan_only_does_not_need_authority_credentials_network_or_writes(self):
        manifest = self._prepare()
        before = self.output.read_bytes()
        result = runner.run_batch(
            self.output,
            preparation.sha(self.output),
            root=self.base / "does-not-exist",
        )
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["verified_jobs"], 360)
        self.assertEqual(self.output.read_bytes(), before)
        for key in (
            "would_access_authority",
            "would_access_credentials",
            "would_call_upstream",
            "would_write",
            "would_publish",
        ):
            self.assertFalse(result[key])
        self.assertEqual(result["release_id"], self.release_id)
        self.assertEqual(result["release_manifest_sha256"], self.release_sha)
        self.assertEqual(
            manifest["source"]["preparation_sha256"], runner.preparation_sha256()
        )
        with self.assertRaisesRegex(ValueError, "1 to 360"):
            runner.run_batch(
                self.output, preparation.sha(self.output), max_requests=361
            )
        with self.assertRaisesRegex(ValueError, "at most 90"):
            runner.run_batch(
                self.output, preparation.sha(self.output), max_seconds=91
            )

    def test_manifest_and_fixed_calendar_tampering_fail_closed(self):
        manifest = self._prepare()
        tampered = self.base / "tampered.json"
        changed = dict(manifest)
        changed["selected"] = dict(manifest["selected"])
        changed["selected"]["trade_dates"] = list(
            reversed(changed["selected"]["trade_dates"])
        )
        tampered.write_bytes(json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "selected trade dates"):
            preparation.verify_manifest(tampered, preparation.sha(tampered))

        original = self.parquet_path.read_bytes()
        self.parquet_path.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(ValueError, "Parquet hash mismatch"):
            preparation.calendar_evidence(self.root, self.release_id, self.release_sha)

    def test_execute_pins_release_hashes_pristine_tasks_and_stop_lines(self):
        manifest = self._prepare()
        with self.assertRaisesRegex(ValueError, "requires pinned release"):
            runner.run_batch(
                self.output,
                preparation.sha(self.output),
                execute=True,
            )

        class OfflinePipeline:
            def __init__(inner_self, root, _catalog):
                inner_self.db = sqlite3.connect(root / "pipeline.sqlite")
                inner_self.db.row_factory = sqlite3.Row

            def _install_exact_task_scope(inner_self, task_ids):
                inner_self.db.execute(
                    "CREATE TEMP TABLE exact_task_scope(task_id TEXT PRIMARY KEY)"
                )
                inner_self.db.executemany(
                    "INSERT INTO exact_task_scope(task_id) VALUES(?)",
                    ((task_id,) for task_id in task_ids),
                )

            def close(inner_self):
                inner_self.db.close()

        database_sha = preparation.sha(self.root / "pipeline.sqlite")
        pointer_sha = preparation.sha(self.root / "CURRENT.json")
        pinned = {
            "expected_task_ids_sha256": manifest["all_task_ids_sha256"],
            "expected_config_sha256": manifest["source"]["authority_config_sha256"],
            "expected_helper_sha256": runner.helper_sha256(),
            "expected_preparation_sha256": runner.preparation_sha256(),
            "expected_release_id": self.release_id,
            "expected_release_manifest_sha256": self.release_sha,
            "root": self.root,
            "execute": True,
        }
        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority"),
            patch.object(runner.pipeline_module, "Pipeline", OfflinePipeline),
            patch.object(
                runner.pipeline_module,
                "get_secret",
                side_effect=AssertionError("disk stop must precede credentials"),
            ),
            patch.object(
                runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=runner.MIN_FREE_BYTES - 1),
            ),
        ):
            disk_result = runner.run_batch(
                self.output, preparation.sha(self.output), **pinned
            )
        self.assertEqual(disk_result["status"], "blocked_disk_reserve")
        self.assertEqual(disk_result["upstream_calls"], 0)
        self.assertFalse(disk_result["release_published"])
        self.assertFalse(disk_result["current_release_switched"])

        with (
            patch.object(runner.pipeline_module, "ROOT", self.root),
            patch.object(runner.pipeline_module, "authority"),
            patch.object(runner.pipeline_module, "Pipeline", OfflinePipeline),
            patch.object(runner.pipeline_module, "get_secret", return_value=None),
            patch.object(
                runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=runner.MIN_FREE_BYTES + 1),
            ),
        ):
            result = runner.run_batch(
                self.output,
                preparation.sha(self.output),
                **pinned,
            )
        self.assertEqual(result["status"], "blocked_missing_token")
        self.assertEqual(result["upstream_calls"], 0)
        self.assertFalse(result["release_published"])
        self.assertFalse(result["current_release_switched"])
        self.assertEqual(preparation.sha(self.root / "pipeline.sqlite"), database_sha)
        self.assertEqual(preparation.sha(self.root / "CURRENT.json"), pointer_sha)

        first = manifest["records"][0]
        db = sqlite3.connect(self.root / "pipeline.sqlite")
        db.row_factory = sqlite3.Row
        db.execute("UPDATE jobs SET tries=1 WHERE id=?", (first["task_id"],))
        db.commit()
        pipeline = type("Pipeline", (), {"db": db})()
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            runner._verify_authority_jobs(pipeline, manifest["records"])
        db.close()

    def test_release_manifest_must_remain_current(self):
        self._prepare()
        (self.root / "CURRENT.json").write_bytes(
            json_bytes({"manifest_sha256": "0" * 64, "release_id": "data-" + "0" * 64})
        )
        with self.assertRaisesRegex(ValueError, "no longer CURRENT"):
            runner._verify_release(
                self.root,
                preparation.verify_manifest(self.output, preparation.sha(self.output)),
            )


if __name__ == "__main__":
    unittest.main()
