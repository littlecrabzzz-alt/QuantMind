"""Coverage obligations survive classification and off-catalogue discovery."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CatalogReview(unittest.TestCase):
    def test_purchased_permissions_use_current_mac_production_evidence(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        by_doc = {row["doc_id"]: row for row in ledger["entries"]}
        evidence_path = "docs/tushare-purchased-permissions-production-20260919.json"
        evidence = json.loads((ROOT / evidence_path).read_bytes())
        expected = {
            "143": "news",
            "154": "cctv_news",
            "176": "anns_d",
            "195": "major_news",
            "366": "irm_qa_sh",
            "367": "irm_qa_sz",
            "406": "npr",
            "415": "research_report",
            "465": "monetary_policy",
        }

        self.assertEqual(evidence["doc_id_to_api"], expected)
        self.assertEqual(evidence["authority"]["node"], "mac")
        self.assertFalse(evidence["boundaries"]["history_complete"])
        self.assertFalse(evidence["boundaries"]["pit_complete"])
        for doc_id, api in expected.items():
            row = by_doc[doc_id]
            observed = evidence["apis"][api]
            self.assertEqual(row["status"], "ingested_partial")
            self.assertEqual(row["permission_status"], "available_observed")
            self.assertEqual(row["runtime_evidence"]["path"], evidence_path)
            self.assertEqual(
                row["runtime_evidence"]["checked_at"], evidence["checked_at"]
            )
            self.assertGreater(observed["successful_nonempty_jobs"], 0)
            self.assertGreater(observed["done_reported_rows"], 0)
            self.assertEqual(observed["permission_blocked_jobs"], 0)

    def test_all_special_pages_and_outgoing_links_remain_tracked(self):
        ledger = json.loads((ROOT / "config/tushare-coverage-ledger.json").read_bytes())
        baseline = {r["doc_id"]: r for r in ledger["entries"]}
        discovered = {r["doc_id"]: r for r in ledger["discovered_entries"]}
        self.assertFalse(set(baseline) & set(discovered))
        reviewed = set()
        for n in (1, 2, 3):
            evidence = json.loads(
                (
                    ROOT / f"docs/tushare-catalog-special-review-{n}.evidence.json"
                ).read_bytes()
            )
            for row in evidence["review"]:
                doc = row["doc_id"]
                self.assertNotIn(doc, reviewed)
                reviewed.add(doc)
                self.assertEqual(
                    baseline[doc]["catalog_review"]["classification"],
                    row["classification"],
                )
                self.assertFalse(baseline[doc]["auto_acquisition"])
                self.assertTrue(baseline[doc]["next_action"])
            for link in evidence["linked_evidence"]:
                if link["doc_id"] not in baseline:
                    actual = discovered[link["doc_id"]]
                    self.assertEqual(actual["source_sha256"], link["sha256"])
                    if actual["permission_status"] != "unverified":
                        # A later account probe can supersede the original
                        # documentation-only permission assessment.
                        observed = actual["runtime_evidence"]
                        if actual["permission_status"] == "available_observed":
                            self.assertIn(
                                observed["status"], ("sample_ok", "possibly_truncated")
                            )
                            self.assertGreater(observed["row_count"], 0)
                            probe_id = observed.get(
                                "probe_release_id", observed.get("probe_session_id", "")
                            )
                            self.assertTrue(probe_id.startswith("probe-"))
                        else:
                            self.assertEqual(
                                actual["permission_status"], "permission_denied"
                            )
                            self.assertEqual(observed["status"], "permission_denied")
                            self.assertFalse(observed["enabled"])
                        self.assertTrue(observed["path"])
                    self.assertTrue(actual["next_action"])
        self.assertEqual(len(reviewed), 36)
        self.assertEqual(
            reviewed, {r["doc_id"] for r in baseline.values() if not r["api_names"]}
        )
        for row in baseline.values():
            if row["status"] == "excluded_mutation":
                self.assertFalse(row["auto_acquisition"])
        self.assertEqual(discovered["372"]["api_names"], ["rt_k"])
        self.assertEqual(discovered["400"]["api_names"], ["rt_etf_k"])


if __name__ == "__main__":
    unittest.main()
