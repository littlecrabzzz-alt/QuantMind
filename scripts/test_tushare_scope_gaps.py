"""Scope accounting must not turn aliases or implemented readers into completion."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from audit_tushare_scope_gaps import ROOT, audit


class ScopeAuditTests(unittest.TestCase):
    def fixture(self):
        return {
            "entries": [
                {"doc_id": "1", "api_names": ["income"], "acquisition_api_names": ["income_vip"],
                 "permission_status": "unverified", "known_field_gaps": [{"field": "hidden"}]},
                {"doc_id": "2", "api_names": [], "status": "review_required"},
                {"doc_id": "3", "api_names": ["ggt_daily", "p_list", "p_save", "pro_bar"]},
            ],
            "discovered_entries": [{"doc_id": "4", "api_names": ["income_vip", "new_unknown"]}],
            "unresolved_api_mentions": [{"api_name": "index_member", "status": "unresolved"}],
            "discovery_seeds": [{"doc_id": "5", "name": "not_a_verified_api"}],
        }

    def run_audit(self, reader=("income_vip", "income", "adjacent")):
        return audit(self.fixture(), {"income_vip": {"history_gap": "unknown"}, "adjacent": {}},
                     {}, reader, {"p_list": {}}, {"adjacent": {"gap": "permission unknown"}})

    def test_alias_overlap_adjacent_and_unresolved_denominators(self):
        result = self.run_audit()
        self.assertEqual(result["counts"]["baseline_pages"], 3)
        self.assertEqual(result["counts"]["catalog_and_discovered_named_apis"], 6)
        self.assertEqual(result["counts"]["total_named_scope"], 7)
        self.assertEqual(result["counts"]["nameless_pages"], 1)
        self.assertEqual(result["reader_only_aliases"], ["income"])
        self.assertEqual(result["source_ledger"], self.fixture())
        self.assertNotIn("index_member", [r["api_name"] for r in result["apis"]])

    def test_classification_not_permission_or_completion(self):
        rows = {r["api_name"]: r for r in self.run_audit()["apis"]}
        expected = {"income_vip": "runtime_readable", "p_list": "pure_contract_only_private",
                    "p_save": "excluded_mutation", "pro_bar": "sdk_only",
                    "ggt_daily": "public_read_only_contract_blocked",
                    "new_unknown": "unclassified_named_obligation"}
        for api, state in expected.items():
            self.assertEqual(rows[api]["implementation"], state)
            self.assertEqual(rows[api]["live_enablement"], "not_inspected")
        self.assertEqual(rows["income_vip"]["known_field_gaps"], [{"field": "hidden"}])
        self.assertEqual(rows["income_vip"]["contract_gap_metadata"], {"history_gap": "unknown"})
        self.assertEqual(rows["income_vip"]["permission_evidence"][0]["status"], "unverified")

    def test_registered_missing_reader_is_not_silent(self):
        result = self.run_audit(reader=[])
        self.assertEqual(result["registered_without_reader"], ["adjacent", "income_vip"])
        self.assertEqual(result["counts"]["implementation_classes"]["registered_reader_missing"], 2)

    def test_no_network_and_input_not_mutated(self):
        source = self.fixture()
        before = json.dumps(source, sort_keys=True)
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            audit(source, {}, {}, (), {}, {})
        self.assertEqual(json.dumps(source, sort_keys=True), before)

    def test_frozen_parent_snapshot_keeps_full_denominator_and_evidence(self):
        frozen = json.loads((ROOT / "docs/tushare-scope-gap-2abcd7f.evidence.json").read_bytes())
        self.assertEqual(frozen["counts"]["total_named_scope"], 236)
        self.assertEqual(frozen["counts"]["registered_union"], 227)
        self.assertEqual(frozen["counts"]["not_registered_in_scope"], 9)
        self.assertEqual(len(frozen["source_ledger"]["unresolved_api_mentions"]), 3)
        rows = {r["api_name"]: r for r in frozen["apis"]}
        self.assertEqual(len(rows["research_report"]["known_field_gaps"]), 2)
        archived = frozen["archived_connect4_review"]["retained-raw-audit.json"]["report"]
        daily = next(r for r in archived["checks"] if r["api_name"] == "ggt_daily")
        self.assertTrue(daily["supplier_has_more"])
        self.assertEqual(daily["requested_fields"], "")

    def test_real_cli_and_frozen_evidence_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/audit_tushare_scope_gaps.py"),
                                   "--output", str(output)], capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(output.read_bytes())
            source = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
            self.assertEqual(result["source_ledger"], source)
            self.assertEqual(result["counts"]["baseline_pages"], 263)
            self.assertEqual(result["registered_without_reader"], [])
            self.assertEqual(result["registered_outside_named_scope"], [])


if __name__ == "__main__":
    unittest.main()
