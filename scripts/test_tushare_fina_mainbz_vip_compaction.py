"""Offline coverage-gated fina_mainbz VIP queue compaction tests."""

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.shared import tushare_pipeline as module  # noqa: E402


CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "config/tushare-catalog.json").read_bytes()
)


class FinaMainbzVipCompactionTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.pipeline = module.Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)
        self.stack.enter_context(
            patch("socket.socket.connect", side_effect=AssertionError("no network"))
        )
        self.stack.enter_context(
            patch.object(module, "get_secret", side_effect=AssertionError("no secrets"))
        )

    def vip(self, period, kind, rows, *, offset=None, state="done"):
        params = {"period": period, "type": kind}
        if offset is not None:
            params["offset"] = offset
        job_id = self.pipeline.enqueue("fina_mainbz_vip", params, 40, "history")
        result = json.dumps(
            {
                "api_name": "fina_mainbz_vip",
                "status": "sample_ok" if rows else "empty_unverified",
                "row_count": rows,
            }
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state=?,result=?,tries=1 WHERE id=?",
            (state, result, job_id),
        )
        return job_id

    def ordinary(self, kind="P", *, epoch="history", start="20200101"):
        return self.pipeline.enqueue(
            "fina_mainbz",
            {
                "ts_code": "000001.SZ",
                "type": kind,
                "start_date": start,
                "end_date": "20201231",
            },
            40,
            epoch,
        )

    def legacy_vip(self, period, kind, rows=200, *, epoch="history"):
        current = self.pipeline.enqueue(
            "fina_mainbz_vip", {"period": period, "type": kind}, 40, epoch
        )
        job = json.loads(
            self.pipeline.db.execute(
                "SELECT job FROM jobs WHERE id=?", (current,)
            ).fetchone()[0]
        )
        job["params"].pop("limit")
        job["row_cap"] = 100
        logical = module.digest(module.json_bytes(job))
        task_id = module.digest(module.json_bytes([logical, epoch]))
        result = json.dumps(
            {
                "api_name": "fina_mainbz_vip",
                "status": "possibly_truncated",
                "row_count": rows,
                "object_sha256": "a" * 64,
                "observation": task_id[:32] + ".json",
                "parquet": {
                    "path": "parquet/" + "b" * 64 + ".parquet",
                    "sha256": "b" * 64,
                    "bytes": 1,
                },
            }
        )
        self.pipeline.db.execute(
            "INSERT INTO jobs(id,logical_key,epoch,job,priority,state,tries,result,"
            "group_name) VALUES(?,?,?,?,?,'blocked',1,?,'research_extra')",
            (task_id, logical, epoch, json.dumps(job), 40, result),
        )
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (task_id, 1, result)
        )
        return task_id

    def state(self, job_id):
        return self.pipeline.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job_id,)
        ).fetchone()[0]

    def complete_product_year(self):
        self.vip("20200331", "P", 17)
        self.vip("20200630", "P", 10000)
        self.vip("20200630", "P", 23, offset=10000)
        self.vip("20200930", "P", 19)
        self.vip("20201231", "P", 31)

    def test_retires_only_matching_full_year_after_closed_pagination(self):
        self.complete_product_year()
        covered = self.ordinary()
        self.pipeline.db.execute("UPDATE jobs SET tries=1 WHERE id=?", (covered,))
        attempt = json.dumps({"api_name": "fina_mainbz", "status": "transport_error"})
        self.pipeline.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)", (covered, 1, attempt)
        )
        different_type = self.ordinary("D")
        partial_year = self.ordinary(start="20200201")
        recent = self.ordinary(epoch="week-20201227")
        terminal = self.pipeline.enqueue(
            "fina_mainbz",
            {
                "ts_code": "000002.SZ",
                "type": "P",
                "start_date": "20200101",
                "end_date": "20201231",
            },
            40,
            "history",
        )
        self.pipeline.db.execute(
            "UPDATE jobs SET state='done',result=? WHERE id=?",
            (json.dumps({"api_name": "fina_mainbz", "row_count": 1}), terminal),
        )
        self.pipeline.db.commit()

        report = self.pipeline.compact_fina_mainbz_vip_coverage()

        self.assertEqual(report["status"], "compacted")
        self.assertEqual(report["vip_complete_period_types"], 4)
        self.assertEqual(report["covered_year_types"], 1)
        self.assertEqual(report["superseded_open_jobs"], 1)
        self.assertEqual(report["retired_job_attempts_preserved"], 1)
        self.assertEqual(self.state(covered), "superseded")
        self.assertEqual(self.state(different_type), "pending")
        self.assertEqual(self.state(partial_year), "pending")
        self.assertEqual(self.state(recent), "pending")
        self.assertEqual(self.state(terminal), "done")
        self.assertEqual(
            self.pipeline.db.execute("SELECT result FROM attempts").fetchone()[0],
            attempt,
        )

        second = self.pipeline.compact_fina_mainbz_vip_coverage()
        self.assertEqual(second["status"], "no_covered_open_jobs")
        self.assertEqual(second["superseded_open_jobs"], 0)

    def test_missing_page_and_empty_root_never_establish_coverage(self):
        self.vip("20200331", "P", 1)
        self.vip("20200630", "P", 10000)
        self.vip("20200930", "P", 1)
        self.vip("20201231", "P", 0, state="empty")
        ordinary = self.ordinary()
        self.pipeline.db.commit()

        report = self.pipeline.compact_fina_mainbz_vip_coverage()

        self.assertEqual(report["status"], "no_complete_years")
        self.assertEqual(report["covered_year_types"], 0)
        self.assertGreaterEqual(report["vip_open_or_empty_chains"], 2)
        self.assertEqual(report["vip_empty_roots"], 1)
        self.assertEqual(self.state(ordinary), "pending")

    def test_page_after_terminal_marks_chain_invalid(self):
        self.vip("20200331", "P", 1)
        self.vip("20200331", "P", 1, offset=10000)
        ordinary = self.ordinary()
        self.pipeline.db.commit()

        report = self.pipeline.compact_fina_mainbz_vip_coverage()

        self.assertEqual(report["vip_invalid_pages"], 1)
        self.assertEqual(report["vip_complete_period_types"], 0)
        self.assertEqual(self.state(ordinary), "pending")

    def test_complete_period_retires_matching_legacy_vip_without_full_year(self):
        self.vip("20200331", "P", 17)
        covered = self.legacy_vip("20200331", "P")
        incomplete = self.legacy_vip("20200630", "P")
        covered_result = self.pipeline.db.execute(
            "SELECT result FROM jobs WHERE id=?", (covered,)
        ).fetchone()[0]
        covered_attempt = self.pipeline.db.execute(
            "SELECT result FROM attempts WHERE job_id=?", (covered,)
        ).fetchone()[0]
        self.pipeline.db.commit()

        report = self.pipeline.compact_fina_mainbz_vip_coverage()

        self.assertEqual(report["status"], "compacted")
        self.assertEqual(report["vip_complete_period_types"], 1)
        self.assertEqual(report["covered_year_types"], 0)
        self.assertEqual(report["legacy_vip_blocked_jobs"], 2)
        self.assertEqual(report["legacy_vip_eligible_jobs"], 1)
        self.assertEqual(report["superseded_legacy_vip_jobs"], 1)
        self.assertEqual(report["legacy_vip_attempts_preserved"], 1)
        self.assertEqual(report["retired_job_attempts_preserved"], 1)
        self.assertEqual(self.state(covered), "superseded")
        self.assertEqual(self.state(incomplete), "blocked")
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT result FROM jobs WHERE id=?", (covered,)
            ).fetchone()[0],
            covered_result,
        )
        self.assertEqual(
            self.pipeline.db.execute(
                "SELECT result FROM attempts WHERE job_id=?", (covered,)
            ).fetchone()[0],
            covered_attempt,
        )
        capability = self.pipeline.db.execute(
            "SELECT status,reason FROM capability "
            "WHERE scope='planning:fina_mainbz_vip:legacy_contract'"
        ).fetchone()
        self.assertEqual(capability["status"], "replaced_by_verified_pagination")
        self.assertEqual(json.loads(capability["reason"])["upstream_calls"], 0)


if __name__ == "__main__":
    unittest.main()
