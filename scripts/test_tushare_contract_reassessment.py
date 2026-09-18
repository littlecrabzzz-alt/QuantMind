"""Zero-request promotion of retained responses under corrected contracts."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared.tushare_pipeline import Pipeline, manifest_at
from scripts.tushare_reassess_saved_quality import reassess


CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class ContractReassessmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def seed(
        self,
        api,
        fields,
        items,
        *,
        null_counts,
        params=None,
        state="quality",
        result_status="schema_gap",
        job_updates=None,
        legacy_response_metadata=False,
        epoch="default",
        priority=100,
    ):
        task = self.pipeline.enqueue(
            api,
            params
            if params is not None
            else {"start_date": "20260911", "end_date": "20260911"},
            priority,
            epoch,
        )
        job = json.loads(
            self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE id=?", (task,)
            ).fetchone()[0]
        )
        job.update(job_updates or {})
        raw = json_bytes(
            {"code": 0, "data": {"fields": fields, "items": items, "has_more": False}}
        )
        sha = digest(raw)
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / f"{sha}.json").write_bytes(raw)
        observation_body = json_bytes(
            {
                "schema_version": 1,
                "request": {
                    "api_name": api,
                    "fields": job["fields"],
                    "params": job["params"],
                },
                "object_sha256": sha,
                "assessment": {
                    "status": result_status,
                    "row_count": len(items),
                    "null_counts": null_counts,
                },
                "response_redacted": False,
                "requested_at": "2026-09-08T00:00:00+00:00",
                "fetched_at": "2026-09-08T00:00:01+00:00",
            }
        )
        observation_sha = digest(observation_body)
        (self.root / "observations").mkdir(exist_ok=True)
        observation = task[:32] + ".json"
        (self.root / "observations" / observation).write_bytes(observation_body)
        parquet_body = b"retained-parquet-fixture"
        parquet_sha = hashlib.sha256(parquet_body).hexdigest()
        (self.root / "parquet").mkdir(exist_ok=True)
        parquet_path = f"parquet/{parquet_sha}.parquet"
        (self.root / parquet_path).write_bytes(parquet_body)
        result = {
            "api_name": api,
            "status": result_status,
            "row_count": len(items),
            "missing_fields": [],
            "null_counts": null_counts,
            "field_coverage": "gap",
            "requested_missing_fields": ["file_name"]
            if api == "research_report"
            else [],
            "optional_requested_missing_fields": [],
            "unexpected_returned_fields": [],
            "response_complete": True,
            "response_format": "json",
            "http_status": 200,
            "object_sha256": sha,
            "observation": observation,
            "observation_sha256": observation_sha,
            "parquet": {
                "path": parquet_path,
                "sha256": parquet_sha,
                "bytes": len(parquet_body),
            },
        }
        if legacy_response_metadata:
            for field in ("response_complete", "response_format", "http_status"):
                result.pop(field)
        encoded = json.dumps(result, sort_keys=True)
        self.pipeline.db.execute(
            "UPDATE jobs SET state=?,tries=1,job=?,result=? WHERE id=?",
            (state, json.dumps(job), encoded, task),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (task, 1, encoded),
        )
        self.pipeline.db.commit()
        return task, job, result

    def test_filtered_blocked_terminal_response_promotes_without_new_attempt(self):
        from backend.shared.tushare_other_contracts import FIELDS

        fields = list(FIELDS["opt_basic"])
        row = ["IO2609-C-4000.CFX" if field == "ts_code" else None for field in fields]
        task, _, original = self.seed(
            "opt_basic",
            fields,
            [row],
            null_counts={field: int(field != "ts_code") for field in fields},
            params={"exchange": "CFFEX"},
            state="blocked",
            result_status="possibly_truncated",
            job_updates={"row_cap": 1},
        )
        report = reassess(self.pipeline, apply=True, apis=["opt_basic"])
        self.assertEqual(report["candidate_states"], {"blocked": 1})
        self.assertEqual(report["promoted_by_api"], {"opt_basic": 1})
        saved = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        self.assertEqual(saved["state"], "done")
        result = json.loads(saved["result"])
        self.assertEqual(result["supplier_terminal_evidence"], "has_more_false_over_unverified_local_alarm")
        self.assertEqual(result["contract_reassessment"]["previous_state"], "blocked")
        self.assertEqual(
            json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM attempts WHERE job_id=?", (task,)
                ).fetchone()[0]
            ),
            original,
        )

    def test_retired_replacement_parent_is_skipped_before_artifact_validation(self):
        from backend.shared.tushare_other_contracts import FIELDS

        fields = list(FIELDS["opt_basic"])
        row = ["IO2609-C-4000.CFX" if field == "ts_code" else None for field in fields]
        task, _, result = self.seed(
            "opt_basic",
            fields,
            [row],
            null_counts={field: int(field != "ts_code") for field in fields},
            params={"exchange": "CFFEX"},
            state="blocked",
            result_status="possibly_truncated",
            job_updates={"row_cap": 1},
        )
        result["parquet"] = None
        self.pipeline.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), task)
        )
        replacement_gap = "replaced_by_stock_range_plan_v1"
        self.pipeline.db.execute(
            "INSERT INTO partition_splits VALUES(?,?,?,?,?,?,?)",
            (
                task,
                "identifier_fanout",
                0,
                0,
                json.dumps({"replacement_gap": replacement_gap}),
                "blocked",
                replacement_gap,
            ),
        )
        self.pipeline.db.commit()

        report = reassess(self.pipeline, apply=True)

        self.assertEqual(report["promoted_jobs"], 0)
        self.assertEqual(
            report["unchanged_by_api_and_status"],
            [
                {
                    "api_name": "opt_basic",
                    "status": "retired_replacement",
                    "jobs": 1,
                }
            ],
        )
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "blocked",
        )

    def test_dry_run_rolls_back_then_apply_preserves_attempt_and_updates_manifest(self):
        fields = "abstr,author,ind_name,inst_csname,name,report_type,title,trade_date,ts_code,url".split(
            ","
        )
        task, _, original = self.seed(
            "research_report",
            fields,
            [["a", None, "i", "c", None, "r", "t", "20260911", None, "u"]],
            null_counts={"author": 1, "name": 1, "ts_code": 1},
        )
        planned = reassess(self.pipeline, apply=False)
        self.assertEqual(planned["promoted_by_api"], {"research_report": 1})
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "quality",
        )
        applied = reassess(self.pipeline, apply=True)
        self.assertEqual(applied["promoted_jobs"], 1)
        row = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        saved = json.loads(row["result"])
        self.assertEqual(row["state"], "done")
        self.assertEqual(saved["status"], "sample_ok")
        self.assertEqual(saved["field_coverage"], "optional_gap")
        self.assertEqual(saved["optional_requested_missing_fields"], ["file_name"])
        self.assertEqual(saved["contract_reassessment"]["upstream_calls"], 0)
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT count(*) FROM contract_reassessments WHERE job_id=?", (task,)
            ).fetchone()[0],
            1,
        )
        attempt = json.loads(
            self.pipeline.db.execute(
                "SELECT result FROM attempts WHERE job_id=?", (task,)
            ).fetchone()[0]
        )
        self.assertEqual(attempt, original)
        release = self.pipeline.publish()
        manifest = manifest_at(self.root, release)
        dataset = next(
            item
            for item in manifest["datasets"]
            if item["api_name"] == "research_report"
        )
        self.assertEqual(dataset["quality_state"], "sample_ok")
        self.assertEqual(
            dataset["contract_reassessment"]["previous_status"], "schema_gap"
        )
        self.assertNotIn(task, {gap["id"] for gap in manifest["gaps"]})

    def test_capability_probe_retires_without_claiming_coverage(self):
        from backend.shared.tushare_other_contracts import FIELDS

        fields = list(FIELDS["opt_basic"])
        item = ["IO2609-C-4000.CFX" if field == "ts_code" else None for field in fields]
        task, _, original = self.seed(
            "opt_basic",
            fields,
            [item],
            null_counts={field: int(field != "ts_code") for field in fields},
            params={},
            state="quality",
            result_status="possibly_truncated",
            epoch="capability-other-test",
            priority=-100,
        )
        production = self.pipeline.enqueue(
            "opt_basic", {"exchange": "CFFEX"}, 5, "history"
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',tries=1 WHERE id=?", (production,)
        )
        self.pipeline.db.execute(
            "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?)",
            ("opt_basic:", "available", "2026-09-18T00:00:00+00:00", "sample_ok"),
        )
        self.pipeline.db.commit()

        planned = reassess(self.pipeline, apply=False, apis=["opt_basic"])
        self.assertEqual(planned["retired_capability_probe_jobs"], 1)
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "quality",
        )
        applied = reassess(self.pipeline, apply=True, apis=["opt_basic"])

        self.assertEqual(
            applied["retired_capability_probe_by_api"], {"opt_basic": 1}
        )
        row = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        result = json.loads(row["result"])
        self.assertEqual(row["state"], "superseded")
        self.assertEqual(result["status"], "possibly_truncated")
        marker = result["capability_probe_retirement"]
        self.assertFalse(marker["coverage_proven"])
        self.assertEqual(marker["upstream_calls"], 0)
        self.assertEqual(marker["production_plan"]["attempted_jobs"], 1)
        self.assertEqual(
            json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM attempts WHERE job_id=?", (task,)
                ).fetchone()[0]
            ),
            original,
        )

    def test_capability_probe_without_production_attempt_stays_quality(self):
        from backend.shared.tushare_other_contracts import FIELDS

        fields = list(FIELDS["opt_basic"])
        item = ["IO2609-C-4000.CFX" if field == "ts_code" else None for field in fields]
        task, _, _ = self.seed(
            "opt_basic",
            fields,
            [item],
            null_counts={field: int(field != "ts_code") for field in fields},
            params={},
            state="quality",
            result_status="possibly_truncated",
            epoch="capability-other-test",
            priority=-100,
        )
        self.pipeline.db.execute(
            "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?)",
            ("opt_basic:", "available", "2026-09-18T00:00:00+00:00", "sample_ok"),
        )
        self.pipeline.db.commit()

        report = reassess(self.pipeline, apply=True, apis=["opt_basic"])

        self.assertEqual(report["retired_capability_probe_jobs"], 0)
        self.assertEqual(
            report["unchanged_by_api_and_status"],
            [
                {
                    "api_name": "opt_basic",
                    "status": "capability_probe_without_production_attempt",
                    "jobs": 1,
                }
            ],
        )
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "quality",
        )

    def test_current_contract_accepts_observed_nullable_text_content(self):
        task, _, _ = self.seed(
            "cctv_news",
            ["content", "date", "title"],
            [[None, "20260911", "title"]],
            null_counts={"content": 1, "date": 0, "title": 0},
        )
        report = reassess(self.pipeline, apply=True)
        self.assertEqual(report["promoted_by_api"], {"cctv_news": 1})
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "done",
        )

    def test_legacy_response_metadata_uses_verified_code_zero_terminal_evidence(self):
        task, _, original = self.seed(
            "cctv_news",
            ["content", "date", "title"],
            [[None, "20260911", "title"]],
            null_counts={"content": 1, "date": 0, "title": 0},
            params={"date": "20260911"},
            legacy_response_metadata=True,
        )

        report = reassess(self.pipeline, apply=True, apis=["cctv_news"])

        self.assertEqual(report["legacy_response_promoted_by_api"], {"cctv_news": 1})
        row = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        result = json.loads(row["result"])
        self.assertEqual(row["state"], "done")
        self.assertEqual(
            result["contract_reassessment"]["response_evidence"],
            "legacy_code_zero_json_has_more_false",
        )
        self.assertEqual(
            result["response_metadata_recovery"]["http_status"], "not_recorded"
        )
        self.assertEqual(
            json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM attempts WHERE job_id=?", (task,)
                ).fetchone()[0]
            ),
            original,
        )

    def test_legacy_response_with_mismatched_observation_stays_quality(self):
        task, _, result = self.seed(
            "cctv_news",
            ["content", "date", "title"],
            [[None, "20260911", "title"]],
            null_counts={"content": 1, "date": 0, "title": 0},
            params={"date": "20260911"},
            legacy_response_metadata=True,
        )
        observation_path = self.root / "observations" / result["observation"]
        observation = json.loads(observation_path.read_bytes())
        observation["request"]["params"] = {"date": "20260910"}
        body = json_bytes(observation)
        observation_path.write_bytes(body)
        result["observation_sha256"] = digest(body)
        self.pipeline.db.execute(
            "UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), task)
        )
        self.pipeline.db.commit()

        report = reassess(self.pipeline, apply=True, apis=["cctv_news"])

        self.assertEqual(report["promoted_jobs"], 0)
        self.assertEqual(
            report["unchanged_by_api_and_status"],
            [
                {
                    "api_name": "cctv_news",
                    "status": "legacy_response_unverified",
                    "jobs": 1,
                }
            ],
        )
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "quality",
        )

    def test_old_etf_basic_job_uses_current_nullable_contract(self):
        from backend.shared.tushare_rrg_contracts import FIELDS

        fields = FIELDS["etf_basic"]
        task, _, _ = self.seed(
            "etf_basic",
            fields,
            [
                [
                    "159001.SZ"
                    if field == "ts_code"
                    else "L"
                    if field == "list_status"
                    else None
                    for field in fields
                ]
            ],
            null_counts={"ts_code": 0, "list_status": 0, "list_date": 1},
            params={"list_status": "L"},
            job_updates={
                "required_fields": ["ts_code", "list_status", "list_date"],
                "nullable_fields": [],
            },
        )

        report = reassess(self.pipeline, apply=True)

        self.assertEqual(report["promoted_by_api"], {"etf_basic": 1})
        row = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        self.assertEqual(row["state"], "done")
        result = json.loads(row["result"])
        self.assertEqual(result["status"], "sample_ok")
        self.assertEqual(result["null_counts"]["list_date"], 1)

    def test_corrupt_retained_object_aborts_without_mutation(self):
        fields = "abstr,author,ind_name,inst_csname,name,report_type,title,trade_date,ts_code,url".split(
            ","
        )
        task, _, result = self.seed(
            "research_report",
            fields,
            [["a", None, "i", "c", None, "r", "t", "20260911", None, "u"]],
            null_counts={"author": 1, "name": 1, "ts_code": 1},
        )
        (self.root / "objects" / f"{result['object_sha256']}.json").write_bytes(
            b"corrupt"
        )
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            reassess(self.pipeline, apply=True)
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT state FROM jobs WHERE id=?", (task,)
            ).fetchone()[0],
            "quality",
        )


if __name__ == "__main__":
    unittest.main()
