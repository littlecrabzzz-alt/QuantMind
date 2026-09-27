import copy
import unittest

from backend.services.research_agent import continuous_state as st
from scripts.continuous_research.link_evidence_request import link, request_hash


class LinkEvidenceRequestTests(unittest.TestCase):
    def setUp(self):
        self.c = st.initial({"end_date": "2026-03-24"})
        self.parent = next(iter(self.c["tasks"].values()))
        self.parent["status"] = "done"
        self.p = {
            "kind": "evidence_review",
            "topic": "risk",
            "question": "originals",
            "reason": "read existing results",
            "backtest_ids": ["r01bt-owned"],
            "awaiting_evidence": True,
        }
        self.parent["reports"] = [{"text": "unaltered report", "followups": [self.p]}]
        self.sha = request_hash(self.p)
        packet = {
            "boundary": "2026-03-24",
            "origin_request": {
                "parent_id": self.parent["id"],
                "proposal_sha256": self.sha,
                "backtest_ids": ["r01bt-owned"],
            },
        }
        h = st.fingerprint(packet)
        self.c["tasks"]["review"] = {
            "kind": "evidence_review",
            "status": "queued",
            "reports": [],
            "evidence": {**packet, "id": h[:32], "sha256": h},
        }

    def test_link_idempotent_preserves_report_and_stops_pending_promotion(self):
        original = copy.deepcopy(self.p)
        args = (self.c, self.parent["id"], self.sha, "review")
        self.assertFalse(link(*args)["already_linked"])
        after = copy.deepcopy(self.c)
        self.assertTrue(link(*args)["already_linked"])
        self.assertEqual(self.c, after)
        st.promote_followups(self.c)
        self.assertEqual(self.c, after)
        self.assertFalse(self.p["awaiting_evidence"])
        self.assertEqual(self.p["task_id"], "review")
        self.assertEqual(self.parent["reports"][0]["text"], "unaltered report")
        for key in ("kind", "topic", "question", "reason", "backtest_ids"):
            self.assertEqual(self.p[key], original[key])

    def test_missing_wrong_tampered_or_changed_request_rejected_without_write(self):
        cases = [
            lambda: self.c["tasks"].pop("review"),
            lambda: self.p.update(question="changed"),
            lambda: self.p.update(task_id="another-review"),
            lambda: self.c["tasks"]["review"]["evidence"].update(boundary="2026-04-01"),
            lambda: self.c["tasks"]["review"]["evidence"]["origin_request"].update(
                backtest_ids=[]
            ),
            lambda: self.c["tasks"]["review"]["evidence"].update(extra="tampered"),
        ]
        for change in cases:
            self.setUp()
            change()
            before = copy.deepcopy(self.c)
            with self.assertRaises(ValueError):
                link(self.c, self.parent["id"], self.sha, "review")
            self.assertEqual(self.c, before)


if __name__ == "__main__":
    unittest.main()
