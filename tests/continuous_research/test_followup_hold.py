import copy
import unittest

from backend.services.research_agent import continuous_state as st
from scripts.continuous_research.hold_followup import hold


class FollowupHoldTests(unittest.TestCase):
    def setUp(self):
        self.proposal = {
            "topic": "stock_signal",
            "question": "unsupported coefficient doubling",
            "reason": "unmeasured covariance",
        }
        self.c = {
            "sequence": 0,
            "events": [],
            "tasks": {
                "parent": {
                    "status": "done",
                    "kind": "stock_factor",
                    "reports": [
                        {
                            "text": "original report",
                            "followups": [copy.deepcopy(self.proposal)],
                        }
                    ],
                    "experiments": {"original": {}},
                },
                "review": {
                    "status": "done",
                    "kind": "evidence_review",
                    "reports": [{"text": "review evidence"}],
                },
            },
        }
        self.digest = st.fingerprint(self.proposal)
        self.reason = (
            "Need measured training covariance before another coefficient trial"
        )

    def test_hold_preserves_history_and_prevents_promotion(self):
        receipt = hold(self.c, "parent", self.digest, "review", self.reason)
        self.assertFalse(receipt["already_held"])
        before = copy.deepcopy(self.c)
        self.assertTrue(
            hold(self.c, "parent", self.digest, "review", self.reason)["already_held"]
        )
        self.assertEqual(self.c, before)
        st.promote_followups(self.c)
        self.assertEqual(set(self.c["tasks"]), {"parent", "review"})
        parent = self.c["tasks"]["parent"]
        self.assertEqual(parent["reports"][0]["text"], "original report")
        self.assertEqual(parent["experiments"], {"original": {}})
        self.assertEqual(
            parent["reports"][0]["withheld_followups"][0]["proposal"], self.proposal
        )
        self.assertEqual(self.c["events"][-1]["kind"], "followup_held")

    def test_dispatched_or_changed_proposal_is_not_modified(self):
        for mode in ("receipt", "task_exists", "wrong_hash", "unfinished_review"):
            c = copy.deepcopy(self.c)
            digest = self.digest
            if mode == "receipt":
                c["tasks"]["parent"]["reports"][0]["followups"][0]["task_id"] = (
                    "existing"
                )
            elif mode == "task_exists":
                task_id = st.fingerprint(
                    ["stock_signal", self.proposal["question"], "stock_factor"]
                )[:24]
                c["tasks"][task_id] = {"status": "running"}
            elif mode == "wrong_hash":
                digest = "0" * 64
            else:
                c["tasks"]["review"]["status"] = "running"
            before = copy.deepcopy(c)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                hold(c, "parent", digest, "review", self.reason)
            self.assertEqual(c, before)


if __name__ == "__main__":
    unittest.main()
