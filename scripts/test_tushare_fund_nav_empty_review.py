"""First-round fund_nav empty review plans remain offline and evidence-pinned."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from scripts import prepare_tushare_fund_nav_empty_review as review  # noqa: E402


class FundNavEmptyReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.authority = self.base / "authority"
        self.release_root = self.base / "fixed"
        self.first_fetched = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        pipeline = pipeline_module.Pipeline(self.authority, catalog)
        parent = pipeline.enqueue(
            "fund_nav",
            {
                "ts_code": "000022.OF",
                "start_date": "19900101",
                "end_date": "20260901",
            },
            priority=45,
            epoch="history",
        )
        parent_row = pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (parent,)
        ).fetchone()
        split = pipeline.split_request(parent_row, json.loads(parent_row["job"]))
        pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',result=? WHERE id=?",
            (
                json.dumps(
                    {
                        "api_name": "fund_nav",
                        "status": "possibly_truncated",
                        "split": split,
                    }
                ),
                parent,
            ),
        )
        children = pipeline.db.execute(
            "SELECT j.* FROM partition_children c JOIN jobs j ON j.id=c.child_id "
            "WHERE c.parent_id=? ORDER BY json_extract(j.job,'$.params.start_date')",
            (parent,),
        ).fetchall()
        self.target_id = children[0]["id"]
        self.sibling_id = children[1]["id"]
        self._save_empty(pipeline, children[0], 1, self.first_fetched, "a" * 32)
        pipeline.db.commit()
        pipeline.reconcile_partitions(child_id=self.target_id)
        pipeline.close()
        self.release_id = self._fixed_release()

    def _save_empty(self, pipeline, row, attempt, fetched_at, observation_name):
        job = json.loads(row["job"])
        payload = {
            "code": 0,
            "data": {
                "fields": job["fields"].split(","),
                "items": [],
                "has_more": False,
            },
        }
        object_raw = review.json_bytes(payload)
        object_sha = review.digest(object_raw)
        assessment = {
            "status": "empty_unverified",
            "row_count": 0,
            "supplier_has_more": False,
            "missing_fields": [],
            "http_status": 200,
            "response_complete": True,
            "response_format": "json",
            "field_coverage": "complete_for_explicit_request",
        }
        observation = {
            "schema_version": 1,
            "request": {key: job[key] for key in ("api_name", "params", "fields")},
            "requested_at": (fetched_at - timedelta(seconds=1)).isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "object_sha256": object_sha,
            "response_redacted": False,
            "assessment": assessment,
        }
        observation_raw = review.json_bytes(observation)
        (self.authority / "objects").mkdir(exist_ok=True)
        (self.authority / "observations").mkdir(exist_ok=True)
        (self.authority / "objects" / f"{object_sha}.json").write_bytes(object_raw)
        (self.authority / "observations" / f"{observation_name}.json").write_bytes(
            observation_raw
        )
        result = {
            "api_name": "fund_nav",
            "observation": f"{observation_name}.json",
            "observation_sha256": review.digest(observation_raw),
            "object_sha256": object_sha,
            **assessment,
        }
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (row["id"], attempt, json.dumps(result)),
        )
        pipeline.db.execute(
            "UPDATE jobs SET state='empty',tries=?,result=? WHERE id=?",
            (attempt, json.dumps(result), row["id"]),
        )

    def _fixed_release(self):
        observation_name = "b" * 32 + ".json"
        observation = {
            "schema_version": 1,
            "request": {
                "api_name": "fund_nav",
                "params": {
                    "ts_code": "000022.OF",
                    "start_date": "20130503",
                    "end_date": "20130503",
                },
                "fields": "ts_code,ann_date,nav_date,unit_nav",
            },
            "requested_at": "2026-09-10T12:05:00+00:00",
            "fetched_at": "2026-09-10T12:05:01+00:00",
            "object_sha256": "c" * 64,
            "response_redacted": False,
            "assessment": {"status": "sample_ok", "row_count": 1},
        }
        observation_raw = review.json_bytes(observation)
        observation_path = self.release_root / "observations" / observation_name
        observation_path.parent.mkdir(parents=True)
        observation_path.write_bytes(observation_raw)
        temporary = self.release_root / "control.parquet"
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "ts_code": "000022.OF",
                        "nav_date": "20130503",
                        "ann_date": None,
                        "_observation": observation_name,
                    }
                ]
            ),
            temporary,
        )
        parquet_sha = review.sha(temporary)
        parquet_name = f"parquet/{parquet_sha}.parquet"
        parquet_path = self.release_root / parquet_name
        parquet_path.parent.mkdir()
        temporary.replace(parquet_path)
        manifest = {
            "files": {
                f"observations/{observation_name}": {
                    "sha256": review.digest(observation_raw),
                    "bytes": len(observation_raw),
                },
                parquet_name: {
                    "sha256": parquet_sha,
                    "bytes": parquet_path.stat().st_size,
                },
            },
            "datasets": [
                {
                    "api_name": "fund_nav",
                    "quality_state": "sample_ok",
                    "path": parquet_name,
                    "sha256": parquet_sha,
                    "bytes": parquet_path.stat().st_size,
                }
            ],
            "history_complete": False,
            "historical_versions_complete": False,
        }
        raw = review.json_bytes(manifest)
        release_id = "data-" + review.digest(raw)
        release = self.release_root / "releases" / release_id
        release.mkdir(parents=True)
        (release / "manifest.json").write_bytes(raw)
        return release_id

    def _prepare(self, now, output=None):
        with (
            patch("socket.socket.connect", side_effect=AssertionError("offline")),
            patch("socket.getaddrinfo", side_effect=AssertionError("offline")),
            patch(
                "backend.shared.tushare_pipeline.get_secret",
                side_effect=AssertionError("no credentials"),
            ),
        ):
            return review.prepare(
                self.authority,
                self.release_root,
                self.release_id,
                output,
                now=now,
            )

    def test_due_plan_pins_original_and_positive_control_without_writing_inputs(self):
        authority_before = (self.authority / "pipeline.sqlite").read_bytes()
        release_before = (
            self.release_root / "releases" / self.release_id / "manifest.json"
        ).read_bytes()
        output = self.base / "review.json"
        manifest = self._prepare(self.first_fetched + timedelta(hours=24), output)
        self.assertEqual(
            (manifest["eligible_targets"], manifest["selected_targets"]), (1, 1)
        )
        record = manifest["records"][0]
        self.assertEqual(record["target"]["task_id"], self.target_id)
        self.assertEqual(record["target"]["state"], "empty")
        self.assertEqual(record["first_empty"]["attempt"], 1)
        self.assertEqual(
            record["first_empty"]["observation"]["sha256"],
            review.sha(self.authority / record["first_empty"]["observation"]["path"]),
        )
        self.assertEqual(record["control"]["request_params"]["start_date"], "20130503")
        self.assertEqual(record["control"]["natural_key"]["ann_date"], None)
        self.assertEqual(record["review_round"], 1)
        self.assertEqual(
            record["not_before"],
            (self.first_fetched + timedelta(hours=24)).isoformat(),
        )
        self.assertIn("do not prove", manifest["boundaries"]["empty_semantics"])
        self.assertEqual(
            (self.authority / "pipeline.sqlite").read_bytes(), authority_before
        )
        self.assertEqual(
            (
                self.release_root / "releases" / self.release_id / "manifest.json"
            ).read_bytes(),
            release_before,
        )

    def test_not_due_prior_review_and_nonfrontier_targets_are_not_frozen(self):
        before = self._prepare(self.first_fetched + timedelta(hours=23, minutes=59))
        self.assertEqual(before["records"], [])
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())
        pipeline = pipeline_module.Pipeline(self.authority, catalog)
        target = pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (self.target_id,)
        ).fetchone()
        self._save_empty(
            pipeline,
            target,
            2,
            self.first_fetched + timedelta(days=1),
            "d" * 32,
        )
        pipeline.db.commit()
        pipeline.close()
        reviewed = self._prepare(self.first_fetched + timedelta(days=3))
        self.assertEqual(reviewed["records"], [])

        # Restore one empty attempt, then make the sibling an unresolved split.
        pipeline = pipeline_module.Pipeline(self.authority, catalog)
        pipeline.db.execute(
            "DELETE FROM attempts WHERE job_id=? AND attempt=2", (self.target_id,)
        )
        first = pipeline.db.execute(
            "SELECT result FROM attempts WHERE job_id=? AND attempt=1",
            (self.target_id,),
        ).fetchone()[0]
        pipeline.db.execute(
            "UPDATE jobs SET tries=1,result=? WHERE id=?", (first, self.target_id)
        )
        sibling = pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (self.sibling_id,)
        ).fetchone()
        nested = pipeline.split_request(sibling, json.loads(sibling["job"]))
        pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',result=? WHERE id=?",
            (
                json.dumps(
                    {
                        "api_name": "fund_nav",
                        "status": "possibly_truncated",
                        "split": nested,
                    }
                ),
                self.sibling_id,
            ),
        )
        pipeline.db.commit()
        pipeline.reconcile_partitions(child_id=self.sibling_id)
        pipeline.close()
        nonfrontier = self._prepare(self.first_fetched + timedelta(days=3))
        self.assertEqual(nonfrontier["records"], [])

    def test_corrupt_empty_and_control_evidence_are_rejected(self):
        manifest = self._prepare(self.first_fetched + timedelta(days=2))
        original_object = (
            self.authority / manifest["records"][0]["first_empty"]["object"]["path"]
        )
        raw = original_object.read_bytes()
        original_object.write_bytes(raw + b" ")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self._prepare(self.first_fetched + timedelta(days=2))
        original_object.write_bytes(raw)

        parquet = (
            self.release_root
            / manifest["records"][0]["control"]["source_parquet"]["path"]
        )
        parquet_raw = parquet.read_bytes()
        parquet.write_bytes(parquet_raw + b" ")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self._prepare(self.first_fetched + timedelta(days=2))
        parquet.write_bytes(parquet_raw)

    def test_missing_positive_control_skips_only_that_code(self):
        manifest = json.loads(
            (
                self.release_root / "releases" / self.release_id / "manifest.json"
            ).read_bytes()
        )
        controls = review._controls(
            self.release_root.resolve(),
            manifest,
            {"000022.OF": "20080502", "000113.OF": "20080502"},
        )
        self.assertEqual(set(controls), {"000022.OF"})

    def test_output_must_be_new_and_outside_both_input_roots(self):
        now = self.first_fetched + timedelta(days=2)
        for output in (
            self.authority / "review.json",
            self.release_root / "review.json",
        ):
            with self.assertRaisesRegex(ValueError, "outside input roots"):
                self._prepare(now, output)
        existing = self.base / "existing.json"
        existing.write_text("keep")
        with self.assertRaisesRegex(ValueError, "outside input roots"):
            self._prepare(now, existing)
        self.assertEqual(existing.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
