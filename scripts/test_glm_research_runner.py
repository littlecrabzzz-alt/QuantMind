"""Focused isolation/recovery checks. No cloud data, API credentials or network."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

import glm_research_runner as runner


class RecoveryTests(unittest.TestCase):
    def test_api_response_is_reused_and_unknown_request_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cred = {"base_url": "https://fixture.invalid", "api_key": "fixture"}
            payload = {"choices": [{"message": {"tool_calls": [{"id": "call1",
                "function": {"name": "decision", "arguments": '{"selected":"E00"}'}}]}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
            def ask(folder):
                return runner.request_tool(root, folder, cred, "glm-5.3-flash", "decision",
                    {"selected": {"type": "string"}}, "fixture", time.time()+60)
            with patch.object(runner.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
                self.assertEqual(ask(root/"ok"), {"selected": "E00"})
                self.assertEqual(ask(root/"ok"), {"selected": "E00"})
                self.assertEqual(request.call_count, 1)
            uncertain = root/"unknown"
            runner.save(uncertain/"attempt-01.json", {"status": "request_intent"})
            with patch.object(runner.urllib.request, "urlopen") as request:
                with self.assertRaises(runner.StopRun):
                    ask(uncertain)
                request.assert_not_called()

    def test_429_honors_retry_after_and_records_unknown_usage(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            error = urllib.error.HTTPError("https://fixture.invalid", 429, "limited", {"Retry-After": "7"}, io.BytesIO(b'{}'))
            payload = {"choices": [{"message": {"tool_calls": [{"id": "c", "function": {
                "name": "decision", "arguments": '{"selected":"E00"}'}}]}}]}
            with patch.object(runner.urllib.request, "urlopen", side_effect=[error, io.BytesIO(json.dumps(payload).encode())]), patch.object(runner, "pause") as wait:
                runner.request_tool(root, root/"api", {"base_url": "https://fixture.invalid", "api_key": "fixture"},
                    "glm-5.3", "decision", {"selected": {"type": "string"}}, "fixture", time.time()+60)
                wait.assert_called_once()
                self.assertEqual(wait.call_args.args[-1], 7)
            self.assertIsNone(runner.read(root/"api/attempt-01.json")["usage"])

    def test_deadline_and_stop_prevent_api_call(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(runner.StopRun):
                runner.check_deadline(root, time.time()-1)
            (root/"STOP").touch()
            with self.assertRaises(runner.StopRun):
                runner.check_deadline(root, time.time()+60)

    def test_existing_experiment_is_reconciled_not_submitted_twice(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            session = root/"glm-5.3"
            proposal = {"kind": "baseline", "hypothesis": "fixture"}
            runner.save(session/"experiments/E00/state.json", {
                "id": "E00", "proposal_sha256": runner.experiment.fingerprint(proposal)})
            with patch.object(runner.experiment, "submit") as submit, patch.object(runner.experiment, "refresh",
                return_value={"id": "E00", "status": "completed"}):
                self.assertEqual(runner.run_experiment(root,session,proposal,time.time()+60)["id"], "E00")
                submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
