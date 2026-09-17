"""Announcement cap handling uses legal historical stock-code fanout only."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.shared.tushare_intake import digest, json_bytes
from backend.shared.tushare_pipeline import (
    ANNOUNCEMENT_IDENTIFIER_SOURCE_APIS,
    Pipeline,
)
from backend.shared.tushare_registry import contract_for
from backend.shared.tushare_text_contracts import normalize_anns_d_ts_code


CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class AnnouncementSaturationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def seed(self, api, params, fields, items, epoch="history"):
        task = self.pipeline.enqueue(api, params, epoch=epoch)
        raw = json_bytes(
            {"code": 0, "data": {"fields": fields, "items": items, "has_more": False}}
        )
        sha = digest(raw)
        objects = self.root / "objects"
        objects.mkdir(exist_ok=True)
        (objects / f"{sha}.json").write_bytes(raw)
        result = {
            "api_name": api,
            "object_sha256": sha,
            "status": "sample_ok",
            "response_format": "json",
            "row_count": len(items),
        }
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',tries=1,result=? WHERE id=?",
            (json.dumps(result), task),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (task, 1, json.dumps(result)),
        )
        self.pipeline.db.commit()
        return task

    def test_output_code_normalization_matches_live_filter_syntax(self):
        self.assertEqual(normalize_anns_d_ts_code("SZ300604"), "300604.SZ")
        self.assertEqual(normalize_anns_d_ts_code("SH600666"), "600666.SH")
        self.assertEqual(normalize_anns_d_ts_code("BJ920009"), "920009.BJ")
        self.assertEqual(normalize_anns_d_ts_code("600666.SH"), "600666.SH")
        self.assertIsNone(normalize_anns_d_ts_code("SZ30060"))
        self.assertIsNone(normalize_anns_d_ts_code(None))

    def test_identifier_projection_uses_historical_stock_universe(self):
        self.seed(
            "stock_basic",
            {"list_status": "D", "exchange": "SSE"},
            ["ts_code"],
            [["600001.SH"]],
        )
        identifiers = self.pipeline.identifiers(
            _source_apis=ANNOUNCEMENT_IDENTIFIER_SOURCE_APIS
        )
        self.assertEqual(identifiers["announcement_securities"], ["600001.SH"])

    def test_recent_cap_stays_explicit_but_history_uses_bounded_fanout(self):
        spec = contract_for("anns_d")
        self.assertEqual(spec["row_cap"], 2000)
        self.assertEqual(spec["saturation_fallback"], "announcement_securities")
        self.assertTrue(spec["saturation_history_only"])
        params = {"start_date": "20260915", "end_date": "20260915"}
        recent = self.pipeline.enqueue("anns_d", params, epoch="2026091716")
        history = self.pipeline.enqueue("anns_d", params, epoch="history")
        recent_row = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (recent,)
        ).fetchone()
        history_row = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (history,)
        ).fetchone()
        job = json.loads(history_row["job"])
        self.assertFalse(
            self.pipeline.identifier_split_needs_discovery(
                job, epoch=recent_row["epoch"]
            )
        )
        self.assertTrue(
            self.pipeline.identifier_split_needs_discovery(
                job, epoch=history_row["epoch"]
            )
        )
        with patch.object(
            self.pipeline,
            "identifiers",
            return_value={"announcement_securities": ["300604.SZ", "600666.SH"]},
        ):
            self.assertIsNone(
                self.pipeline.split_request(
                    recent_row, json.loads(recent_row["job"]), {"row_count": 2000}
                )
            )
            split = self.pipeline.split_request(history_row, job, {"row_count": 2000})
        self.assertEqual(split["method"], "identifier_fanout")
        self.assertEqual(split["children"], 2)
        self.assertFalse(split["universe_complete"])
        child_params = {
            json.loads(row[0])["params"]["ts_code"]
            for row in self.pipeline.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j "
                "ON j.id=c.child_id WHERE c.parent_id=?",
                (history,),
            )
        }
        self.assertEqual(child_params, {"300604.SZ", "600666.SH"})

    def test_history_fanout_normalizes_codes_observed_in_parent(self):
        task = self.seed(
            "anns_d",
            {"start_date": "20260915", "end_date": "20260915"},
            ["ts_code"],
            [["SZ300604"], ["600002.SH"], ["bad"]],
        )
        row = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (task,)
        ).fetchone()
        with patch.object(
            self.pipeline,
            "identifiers",
            return_value={"announcement_securities": ["600001.SH"]},
        ):
            split = self.pipeline.split_request(row, json.loads(row["job"]))
        self.assertEqual(split["method"], "identifier_fanout")
        child_params = {
            json.loads(child[0])["params"]["ts_code"]
            for child in self.pipeline.db.execute(
                "SELECT j.job FROM partition_children c JOIN jobs j "
                "ON j.id=c.child_id WHERE c.parent_id=?",
                (task,),
            )
        }
        self.assertEqual(child_params, {"300604.SZ", "600001.SH", "600002.SH"})

    def test_deferred_history_fanout_resumes_in_1000_job_batches(self):
        task = self.pipeline.enqueue(
            "anns_d",
            {"start_date": "20260915", "end_date": "20260915"},
            epoch="history",
        )
        result = {
            "api_name": "anns_d",
            "status": "possibly_truncated",
            "row_count": 2208,
            "partition_deferred": {"version": 1, "kind": "identifier_fanout"},
        }
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',result=? WHERE id=?",
            (json.dumps(result), task),
        )
        self.pipeline.db.commit()
        codes = [f"{value:06d}.SZ" for value in range(1205)]
        with patch.object(
            self.pipeline,
            "identifiers",
            return_value={"announcement_securities": codes},
        ):
            first = self.pipeline.resume_identifier_split(float("inf"), {})
            saved = json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM jobs WHERE id=?", (task,)
                ).fetchone()[0]
            )
            second = self.pipeline.resume_identifier_split(float("inf"), {})
        self.assertEqual(first["status"], "partition_progress")
        self.assertEqual(first["split"]["children"], 1000)
        self.assertEqual(first["split"]["remaining_observed_values"], 205)
        self.assertIn("partition_deferred", saved)
        self.assertEqual(second["status"], "partitioned")
        self.assertEqual(second["split"]["children"], 1205)
        final = json.loads(
            self.pipeline.db.execute(
                "SELECT result FROM jobs WHERE id=?", (task,)
            ).fetchone()[0]
        )
        self.assertNotIn("partition_deferred", final)

    def test_recent_caps_retire_only_after_canonical_history_fanout(self):
        params = {"start_date": "20260915", "end_date": "20260915"}
        fields = ["ann_date", "ts_code", "name", "title", "url", "rec_time"]
        items = [["20260915", "SZ300604", "A", "T", "U", None]]
        history = self.seed("anns_d", params, fields, items)
        history_row = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (history,)
        ).fetchone()
        history_result = json.loads(history_row["result"])
        history_result.update(status="possibly_truncated", observation="history.json")
        with patch.object(
            self.pipeline,
            "identifiers",
            return_value={"announcement_securities": ["300604.SZ", "600000.SH"]},
        ):
            split = self.pipeline.split_request(
                history_row, json.loads(history_row["job"]), history_result
            )
        history_result["split"] = split
        self.pipeline.db.execute(
            "UPDATE jobs SET state='split_pending',result=? WHERE id=?",
            (json.dumps(history_result), history),
        )

        recent = []
        for epoch in ("2026091705", "20260918"):
            task = self.seed("anns_d", params, fields, items, epoch=epoch)
            result = json.loads(
                self.pipeline.db.execute(
                    "SELECT result FROM jobs WHERE id=?", (task,)
                ).fetchone()[0]
            )
            result.update(status="possibly_truncated", observation=epoch + ".json")
            self.pipeline.db.execute(
                "UPDATE jobs SET state='blocked',result=? WHERE id=?",
                (json.dumps(result), task),
            )
            recent.append(task)
        unrelated = self.seed(
            "anns_d",
            {"start_date": "20260916", "end_date": "20260916"},
            fields,
            items,
            epoch="20260918",
        )
        unrelated_result = json.loads(
            self.pipeline.db.execute(
                "SELECT result FROM jobs WHERE id=?", (unrelated,)
            ).fetchone()[0]
        )
        unrelated_result.update(
            status="possibly_truncated", observation="unrelated.json"
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',result=? WHERE id=?",
            (json.dumps(unrelated_result), unrelated),
        )
        self.pipeline.db.commit()
        before = dict(
            self.pipeline.db.execute(
                "SELECT id,result FROM jobs WHERE id IN (?,?,?)",
                (*recent, unrelated),
            )
        )

        report = self.pipeline.maintain_announcement_saturation()
        self.assertEqual(report["status"], "maintained")
        self.assertEqual(report["superseded_recent_caps"], 2)
        self.assertEqual(report["recovered_date_split_parents"], 0)
        self.assertEqual(report["preserved_result_jobs"], 2)
        self.assertEqual(report["preserved_attempts"], 2)
        rows = {
            row["id"]: (row["state"], row["result"])
            for row in self.pipeline.db.execute(
                "SELECT id,state,result FROM jobs WHERE id IN (?,?,?,?)",
                (history, *recent, unrelated),
            )
        }
        self.assertEqual(rows[history][0], "split_pending")
        self.assertTrue(all(rows[task][0] == "superseded" for task in recent))
        self.assertEqual(rows[unrelated][0], "blocked")
        self.assertTrue(all(rows[task][1] == before[task] for task in recent))
        self.assertEqual(
            self.pipeline.maintain_announcement_saturation()["status"], "no_action"
        )

    def test_legacy_date_split_parent_recovers_without_changing_evidence(self):
        task = self.pipeline.enqueue(
            "anns_d",
            {"start_date": "20200416", "end_date": "20200423"},
            epoch="history",
        )
        row = self.pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (task,)
        ).fetchone()
        result = {
            "api_name": "anns_d",
            "status": "possibly_truncated",
            "row_count": 6000,
            "object_sha256": "a" * 64,
            "observation": "legacy.json",
            "normalization_error": "TimeoutError",
        }
        result["split"] = self.pipeline.split_request(
            row, json.loads(row["job"]), result
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',tries=1,result=? WHERE id=?",
            (json.dumps(result), task),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (task, 1, json.dumps(result)),
        )
        self.pipeline.db.commit()
        saved = self.pipeline.db.execute(
            "SELECT result FROM jobs WHERE id=?", (task,)
        ).fetchone()[0]

        report = self.pipeline.maintain_announcement_saturation()
        self.assertEqual(report["recovered_date_split_parents"], 1)
        self.assertEqual(report["superseded_recent_caps"], 0)
        parent = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        self.assertEqual(parent["state"], "split_pending")
        self.assertEqual(parent["result"], saved)
        split = self.pipeline.db.execute(
            "SELECT status,gap FROM partition_splits WHERE parent_id=?", (task,)
        ).fetchone()
        self.assertEqual(tuple(split), ("gap", "child_not_verified"))
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT count(*) FROM attempts WHERE job_id=?", (task,)
            ).fetchone()[0],
            1,
        )

    def test_new_date_split_keeps_running_when_parent_normalization_fails(self):
        task = self.pipeline.enqueue(
            "anns_d",
            {"start_date": "20200416", "end_date": "20200423"},
            epoch="history",
        )
        captured = {
            "api_name": "anns_d",
            "status": "possibly_truncated",
            "row_count": 6000,
            "supplier_empty_hint": False,
            "object_sha256": "b" * 64,
            "observation": "current.json",
        }
        with (
            patch(
                "backend.shared.tushare_pipeline.capture_sample",
                return_value=captured,
            ),
            patch.object(self.pipeline, "normalize", side_effect=TimeoutError),
        ):
            report = self.pipeline.run(
                None,
                "test-token",
                {},
                max_requests=1,
                max_seconds=30,
                pause=0,
                task_ids=[task],
            )
        self.assertEqual(report["requests"], 1)
        parent = self.pipeline.db.execute(
            "SELECT state,result FROM jobs WHERE id=?", (task,)
        ).fetchone()
        self.assertEqual(parent["state"], "split_pending")
        result = json.loads(parent["result"])
        self.assertEqual(result["normalization_error"], "TimeoutError")
        self.assertEqual(result["split"], {"method": "date_bisection", "children": 2})


if __name__ == "__main__":
    unittest.main()
