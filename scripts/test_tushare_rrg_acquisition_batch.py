"""RRG acquisition batches are inert, deterministic and Pipeline-identical."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_tushare_rrg_acquisition_batch as module


class AcquisitionBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.audit = self.base / "audit"
        self.audit.mkdir()
        self.report = self.audit / "report.json"
        self.report.write_text(
            json.dumps(
                {
                    "status": "blocked_data",
                    "release_id": "data-" + "a" * 64,
                    "upstream_calls": 0,
                    "credentials_accessed": False,
                    "window": {"start_date": "20220101", "end_date": "20221231"},
                    "collection_plan": {"jobs": 6},
                }
            )
        )
        self.rows = [
            {
                "api_name": "fund_div",
                "params": {"ts_code": "510300.SH"},
                "gate": "requires_terminal_receipt",
                "reason": "receipt",
            },
            {
                "api_name": "fund_div",
                "params": {"ts_code": "159915.SZ"},
                "gate": "requires_terminal_receipt",
                "reason": "receipt",
            },
            {
                "api_name": "etf_limit",
                "params": {"start_date": "20220101", "end_date": "20220131"},
                "gate": "collection_candidate",
                "reason": "bounds only",
            },
            {
                "api_name": "etf_limit",
                "params": {"start_date": "20220201", "end_date": "20220228"},
                "gate": "collection_candidate",
                "reason": "bounds only",
            },
            {
                "api_name": "fund_daily",
                "params": {
                    "ts_code": "510300.SH",
                    "start_date": "20220104",
                    "end_date": "20220104",
                },
                "gate": "diagnostic_refresh_only",
                "reason": "no fill",
            },
            {
                "api_name": "etf_sh_cons",
                "params": {
                    "ts_code": "510300.SH",
                    "start_date": "20220101",
                    "end_date": "20221231",
                },
                "gate": "blocked_until_authoritative_etf_mapping",
                "reason": "PIT blocked",
            },
        ]
        self.plan = self.audit / "collection-plan.jsonl"
        self._write_plan()

    def _write_plan(self):
        self.plan.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                for row in self.rows
            )
        )
        manifest = {
            "release_id": "data-" + "a" * 64,
            "status": "blocked_data",
            "files": {
                "report.json": {"sha256": module.sha(self.report)},
                "collection-plan.jsonl": {"sha256": module.sha(self.plan)},
            },
        }
        (self.audit / "manifest.json").write_text(json.dumps(manifest))

    def invoke(self, output, **overrides):
        args = {
            "audit_report": self.report,
            "report_sha256": module.sha(self.report),
            "output": output,
            "shard_size": 1,
            "include_diagnostics": False,
        }
        args.update(overrides)
        return module.prepare(**args)

    def test_default_batch_is_inert_sharded_idempotent_and_excludes_diagnostics(self):
        first = self.invoke(self.base / "first")
        second = self.invoke(self.base / "second")
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "prepared_not_enqueued")
        self.assertEqual(first["selection"]["prepared_counts"], {"fund_div": 2, "etf_limit": 2})
        self.assertEqual(first["selection"]["excluded_counts"], {"fund_daily": 1, "etf_sh_cons": 1})
        self.assertFalse(first["activation"]["automatically_enqueued"])
        self.assertEqual(first["activation"]["upstream_calls"], 0)
        self.assertFalse((self.base / "first" / "pipeline.sqlite").exists())
        left = sorted((self.base / "first" / "shards").iterdir())
        right = sorted((self.base / "second" / "shards").iterdir())
        self.assertEqual([path.name for path in left], [path.name for path in right])
        self.assertEqual(
            [hashlib.sha256(path.read_bytes()).hexdigest() for path in left],
            [hashlib.sha256(path.read_bytes()).hexdigest() for path in right],
        )
        jobs = [json.loads(path.read_text()) for path in left]
        self.assertTrue(all(job["task_id"] and job["logical_key"] for job in jobs))
        self.assertEqual({job["epoch"] for job in jobs}, {"history"})
        self.assertEqual({job["job"]["api_name"] for job in jobs}, {"fund_div", "etf_limit"})

    def test_diagnostics_require_explicit_opt_in_and_keep_unclassified_semantics(self):
        result = self.invoke(self.base / "with-diagnostics", include_diagnostics=True)
        self.assertEqual(result["selection"]["prepared_counts"]["fund_daily"], 1)
        self.assertIn("must never be filled", result["terminal_receipt_semantics"]["fund_daily"])
        self.assertNotIn("etf_sh_cons", result["selection"]["prepared_counts"])

    def test_price_diagnostics_can_be_prepared_as_a_bounded_standalone_batch(self):
        result = self.invoke(self.base / "diagnostics-only", diagnostics_only=True)
        self.assertEqual(result["selection"]["apis"], ["fund_daily"])
        self.assertEqual(result["selection"]["prepared_counts"], {"fund_daily": 1})
        self.assertEqual(
            result["selection"]["excluded_counts"],
            {"fund_div": 2, "etf_limit": 2, "etf_sh_cons": 1},
        )
        shard = self.base / "diagnostics-only" / result["shards"][0]["path"]
        self.assertEqual(json.loads(shard.read_text())["group_name"], "rrg")

    def test_rejects_tampering_duplicates_bad_gates_and_protected_output(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            module.prepare(self.report, "0" * 64, self.base / "bad-hash", 10, False)
        self.rows.append(self.rows[0])
        self._write_plan()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.invoke(self.base / "duplicate")
        self.rows.pop()
        self.rows[0] = {**self.rows[0], "gate": "collection_candidate"}
        self._write_plan()
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.invoke(self.base / "bad-gate")
        with self.assertRaisesRegex(ValueError, "Output must be new"):
            self.invoke(self.audit / "inside-source")


if __name__ == "__main__":
    unittest.main()
