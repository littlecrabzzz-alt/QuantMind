"""Offline fixed-release coverage accounting tests."""

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from audit_tushare_fixed_coverage import audit


class FixedCoverageAuditTests(unittest.TestCase):
    def fixture(self):
        return {
            "files": {"objects/" + "a" * 64 + ".json": {"sha256": "a" * 64, "bytes": 1}},
            "scope": ["ready", "empty", "disabled_elsewhere", "unknown"],
            "datasets": [
                {"api_name": "ready", "path": "parquet/" + "b" * 64 + ".parquet"},
                {"api_name": "unknown", "path": "parquet/" + "c" * 64 + ".parquet"},
            ],
            "coverage_by_api": [
                {"api_name": "ready", "state": "done", "partitions": 2},
                {"api_name": "empty", "state": "empty", "partitions": 3},
                {"api_name": "disabled_elsewhere", "state": "blocked", "partitions": 1},
            ],
            "capabilities": [
                {"scope": "disabled_elsewhere:", "status": "permission_denied", "checked_at": "2026-01-01"},
                {"scope": "planning:ready:history_gap", "status": "coverage_unverified", "checked_at": "2026-01-02"},
            ],
        }

    def test_states_are_counted_separately(self):
        result = audit({"ready", "empty", "never_planned", "disabled_elsewhere"},
                       self.fixture(), "data-" + "1" * 64)
        self.assertEqual(result["counts"], {
            "registered": 4,
            "planned": 4,
            "registered_planned": 3,
            "registered_with_published_dataset": 1,
            "published_dataset_apis": 2,
        })
        self.assertEqual([row["api_name"] for row in result["registered_not_planned"]],
                         ["never_planned"])
        missing = {row["api_name"]: row for row in result["registered_planned_without_published_dataset"]}
        self.assertEqual(missing["empty"]["coverage"], {"empty": 3})
        self.assertEqual(missing["disabled_elsewhere"]["capabilities"], [
            {"status": "permission_denied", "checked_at": "2026-01-01"}
        ])
        self.assertEqual(result["unregistered_planned"], ["unknown"])
        self.assertEqual(result["unregistered_published_dataset_apis"], ["unknown"])

    def test_planning_gap_is_not_misreported_as_api_capability(self):
        result = audit({"ready"}, self.fixture(), "data-" + "1" * 64)
        self.assertEqual(result["registered_not_planned"], [])
        self.assertEqual(result["published_dataset_counts"], {"ready": 1})

    def test_audit_is_deterministic_and_offline(self):
        manifest = self.fixture()
        before = json.dumps(manifest, sort_keys=True)
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            first = audit({"empty", "ready"}, manifest, "data-" + "1" * 64)
            second = audit({"ready", "empty"}, manifest, "data-" + "1" * 64)
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(manifest, sort_keys=True), before)

    def test_cli_reads_verified_release_and_keeps_output_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            mirror = base / "mirror"
            release_doc = {
                "files": {}, "scope": [], "datasets": [],
                "coverage_by_api": [], "capabilities": [],
            }
            raw = json.dumps(release_doc, separators=(",", ":"), sort_keys=True).encode()
            release_id = "data-" + hashlib.sha256(raw).hexdigest()
            release = mirror / "releases" / release_id
            release.mkdir(parents=True)
            (release / "manifest.json").write_bytes(raw)
            (mirror / "CURRENT.json").write_text(json.dumps({
                "release_id": release_id, "manifest_sha256": release_id[5:],
            }))
            output = base / "report.json"
            script = Path(__file__).with_name("audit_tushare_fixed_coverage.py")
            proc = subprocess.run(
                [sys.executable, str(script), "--root", str(mirror), "--output", str(output)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(output.read_text())["release_id"], release_id)
            denied = subprocess.run(
                [sys.executable, str(script), "--root", str(mirror),
                 "--output", str(mirror / "report.json")],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("outside the immutable mirror root", denied.stderr)


if __name__ == "__main__":
    unittest.main()
