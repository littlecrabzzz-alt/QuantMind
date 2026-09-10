"""Coverage obligations survive classification and off-catalogue discovery."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CatalogReview(unittest.TestCase):
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
                            self.assertTrue(
                                observed["probe_release_id"].startswith("probe-")
                            )
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
