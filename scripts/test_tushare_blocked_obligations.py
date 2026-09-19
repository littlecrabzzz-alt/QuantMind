"""Blocked acquisition jobs remain visible with an explicit reason class."""

import json
from pathlib import Path
import tempfile
import unittest

from backend.shared.tushare_pipeline import Pipeline
from scripts import tushare_archive_worker


ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "config/tushare-catalog.json").read_bytes())


class BlockedObligations(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pipeline = Pipeline(self.root, CATALOG)
        self.addCleanup(self.pipeline.close)

    def blocked(self, api, result):
        job_id = self.pipeline.enqueue(api, {}, epoch="fixture")
        self.pipeline.db.execute(
            "UPDATE jobs SET state='blocked',result=? WHERE id=?",
            (json.dumps({"api_name": api, **result}), job_id),
        )
        self.pipeline.db.commit()
        return job_id

    def test_empty_inventory_is_fully_classified(self):
        self.assertEqual(
            self.pipeline.blocked_obligations(),
            {
                "total": 0,
                "by_kind": {},
                "unclassified": 0,
                "all_blocked_jobs_classified": True,
                "changes_job_state": False,
            },
        )

    def test_worker_reads_inventory_through_a_separate_read_only_connection(self):
        self.blocked("npr", {"status": "possibly_truncated", "row_count": 500})
        self.assertEqual(
            tushare_archive_worker.read_blocked_obligations(self.root),
            self.pipeline.blocked_obligations(),
        )

    def test_each_durable_blocked_reason_is_reported_without_mutation(self):
        replacement = self.blocked(
            "dc_member", {"status": "possibly_truncated", "row_count": 8000}
        )
        child = self.pipeline.enqueue(
            "dc_member", {"ts_code": "BK0001.DC"}, epoch="fixture"
        )
        self.pipeline.record_partition(
            replacement,
            [child],
            "identifier_fanout",
            False,
            {"universe_complete": False},
        )
        self.pipeline.db.execute(
            "UPDATE partition_splits SET status='blocked',gap=? WHERE parent_id=?",
            ("replaced_by_stock_range_plan_v1", replacement),
        )
        self.blocked(
            "bo_daily",
            {
                "status": "api_error",
                "code": 40101,
                "supplier_api_unavailable": True,
            },
        )
        self.blocked("stk_mins", {"status": "rate_limited"})
        self.blocked("npr", {"status": "possibly_truncated", "row_count": 500})
        self.blocked("daily", {"status": "invalid_values"})

        before = list(
            self.pipeline.db.execute(
                "SELECT id,state,result FROM jobs ORDER BY id"
            )
        )
        report = self.pipeline.blocked_obligations()
        after = list(
            self.pipeline.db.execute(
                "SELECT id,state,result FROM jobs ORDER BY id"
            )
        )

        self.assertEqual(
            [tuple(row) for row in after], [tuple(row) for row in before]
        )
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["unclassified"], 1)
        self.assertFalse(report["all_blocked_jobs_classified"])
        self.assertFalse(report["changes_job_state"])
        self.assertEqual(
            {kind: value["jobs"] for kind, value in report["by_kind"].items()},
            {
                "replacement_plan_retained_parent": 1,
                "retained_rate_limit_probe": 1,
                "supplier_api_unavailable": 1,
                "unclassified": 1,
                "unsplittable_source_cap": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
