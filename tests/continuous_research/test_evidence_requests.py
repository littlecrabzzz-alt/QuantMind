"""Evidence requests stay outside execution; missing packets never prompt churn."""

import copy
import threading
import unittest
from unittest.mock import MagicMock

from backend.services.research_agent import continuous_state as st
from scripts.continuous_research import controller


class EvidenceRequestTests(unittest.TestCase):
    def test_pending_request_never_becomes_claimable_and_old_followup_does(self):
        c = st.initial({"concurrency": 3})
        for task in c["tasks"].values():
            task["status"] = "done"
        task = next(iter(c["tasks"].values()))
        proposal = {
            "kind": "evidence_review",
            "topic": "trend",
            "question": "review",
            "reason": "missing originals",
            "backtest_ids": ["owned-run"],
        }
        task["reports"].append({"followups": [proposal]})
        st.promote_followups(c)
        self.assertTrue(proposal["awaiting_evidence"])
        self.assertNotIn("task_id", proposal)
        before = copy.deepcopy(c["tasks"])
        st.control(c, "start")
        c["quota"] = {"status": "known", "remaining_percent": 99, "observed_at": 1000}
        self.assertIsNone(st.claim(c, "worker", 1000))
        self.assertEqual(c["tasks"], before)
        old = {"topic": "trend", "question": "new experiment", "reason": "evidence"}
        task["reports"][0]["followups"].append(old)
        st.promote_followups(c)
        self.assertEqual(st.claim(c, "worker", 1000)["id"], old["task_id"])
        self.assertEqual(len(c["tasks"]), 4)

    def worker(self, action_error=None, model_error=None):
        task = {"id": "task", "lease": "lease", "kind": "research", "reports": []}
        worker = controller.Controller.__new__(controller.Controller)
        worker.stop = threading.Event()
        worker.api = MagicMock()

        def call(op, *args, **kwargs):
            if op == "context":
                return {"task": task, "results": {}, "quota_state": "available"}
            if op == "action" and action_error:
                raise action_error
            return {}

        worker.api.call.side_effect = call
        worker.model = MagicMock(
            return_value=({"action": "report", "text": "a" * 100}, model_error, {})
        )
        worker.work(task)
        return worker

    def test_missing_public_experiment_blocks_once_without_rewrite(self):
        worker = self.worker(
            controller.APIError(409, "report_requires_public_experiment")
        )
        worker.model.assert_called_once()
        self.assertNotIn(
            "feedback", [c.args[0] for c in worker.api.call.call_args_list]
        )
        settlement = worker.api.call.call_args.args[2]
        self.assertEqual(settlement["outcome"], "blocked")
        self.assertIn("add_evidence_review", settlement["reason"])

    def test_quota_and_server_failure_keep_existing_retry_semantics(self):
        for error in ("waiting_quota", "retrying", "quota_unknown"):
            with self.subTest(error=error):
                worker = self.worker(model_error=error)
                worker.model.assert_called_once()
                self.assertEqual(worker.api.call.call_args.args[2]["outcome"], error)
        for detail in ("temporarily unavailable", "report_requires_public_experiment"):
            worker = self.worker(controller.APIError(503, detail))
            self.assertEqual(worker.api.call.call_args.args[2]["outcome"], "retrying")


if __name__ == "__main__":
    unittest.main()
