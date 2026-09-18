import json
import tempfile
import unittest
from pathlib import Path

from backend.shared.tushare_catalog_watch import (
    assess_catalog_index,
    run_catalog_watch,
)
from scripts.tushare_archive_worker import cycle_log


def html(entries):
    links = "".join(
        f'<a href="/document/2?doc_id={doc_id}">{title}</a>'
        for doc_id, title in entries
    )
    return f'<html><div id="jstree">{links}</div></html>'.encode()


class CatalogWatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(
            json.dumps(
                {
                    "index_sha256": "saved-index",
                    "entries": [
                        {"doc_id": "1", "title": "one"},
                        {"doc_id": "2", "title": "two"},
                    ],
                }
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_pure_diff_detects_added_removed_and_retitled(self):
        baseline = json.loads(self.catalog.read_text())
        report = assess_catalog_index(
            html((("1", "ONE"), ("3", "three"))), baseline, 1000
        )
        self.assertEqual(report["status"], "drift_detected")
        self.assertEqual(report["added_doc_ids"], ["3"])
        self.assertEqual(report["removed_doc_ids"], ["2"])
        self.assertEqual(report["retitled"][0]["doc_id"], "1")
        self.assertEqual(report["change_count"], 3)

    def test_success_is_persisted_and_followup_is_deferred(self):
        calls = []

        def fetch():
            calls.append(True)
            return html((("1", "one"), ("2", "two")))

        config = {"enable_catalog_watch": True, "catalog_watch_interval_seconds": 3600}
        first = run_catalog_watch(
            self.root, config, catalog_path=self.catalog, fetch=fetch, now_epoch=1000
        )
        second = run_catalog_watch(
            self.root, config, catalog_path=self.catalog, fetch=fetch, now_epoch=1001
        )
        self.assertEqual(first["status"], "current")
        self.assertEqual(second["status"], "deferred")
        self.assertEqual(second["last_status"], "current")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            json.loads((self.root / "catalog-watch-status.json").read_text())["status"],
            "current",
        )

    def test_fetch_failure_is_safe_and_retries_in_one_hour(self):
        def fail():
            raise RuntimeError("secret details must not be copied")

        report = run_catalog_watch(
            self.root,
            {"enable_catalog_watch": True},
            catalog_path=self.catalog,
            fetch=fail,
            now_epoch=2000,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_type"], "RuntimeError")
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(report["next_check_epoch"], 5600)

    def test_disabled_mode_has_no_network_or_state_write(self):
        report = run_catalog_watch(self.root, {}, fetch=lambda: self.fail("network"))
        self.assertEqual(report, {"status": "disabled"})
        self.assertFalse((self.root / "catalog-watch-status.json").exists())

    def test_cycle_log_exposes_drift_without_titles(self):
        compact = cycle_log(
            {
                "status": "completed_cycle",
                "catalog_watch": {
                    "status": "drift_detected",
                    "current_entry_count": 271,
                    "change_count": 1,
                    "added_doc_ids": ["499"],
                    "retitled": [{"doc_id": "1", "current_title": "private-noise"}],
                },
            }
        )
        self.assertEqual(compact["catalog_watch"]["added_doc_ids"], ["499"])
        self.assertNotIn("retitled", compact["catalog_watch"])


if __name__ == "__main__":
    unittest.main()
