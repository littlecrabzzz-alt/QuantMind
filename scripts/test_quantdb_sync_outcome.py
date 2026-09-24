"""Offline sync outcomes: derived/source failures must reach callers."""
import unittest
from unittest.mock import patch
from backend.scripts import quantdb_daily_sync as sync
from backend.shared.quantdb_sync_jobs import has_sync_errors


class SyncOutcome(unittest.TestCase):
    def test_qlib_failure_is_partial_even_when_parquet_pg_succeed(self):
        with patch.object(sync, "_sync_extra_sources", return_value={}), patch.object(sync, "fill_pg_from_parquet", return_value={"status": "ok", "rows": 5}), patch.object(sync, "update_qlib_cache", return_value={"status": "error", "reason": "calendar mismatch"}):
            result = sync.run_daily_sync(skip_parquet=True, skip_snapshot=True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed_stages"], ["qlib_cache"])

    def test_parquet_only_reports_nested_source_failure(self):
        with patch.object(sync, "sync_parquet", return_value={"errors": 0}), patch.object(sync, "_sync_extra_sources", return_value={"north": {"status": "failed"}}):
            result = sync.run_daily_sync(parquet_only=True, dry_run=True)
        self.assertEqual(result["failed_stages"], ["sources"])
        self.assertEqual(result["status"], "partial")

    def test_completed_only_covers_requested_stages(self):
        with patch.object(sync, "_sync_extra_sources", return_value={}):
            result = sync.run_daily_sync(skip_parquet=True, skip_pg=True, skip_qlib=True, skip_snapshot=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["failed_stages"], [])
        self.assertIsNone(result["qlib_cache"])
        self.assertFalse(has_sync_errors(result))


if __name__ == "__main__":
    unittest.main()
