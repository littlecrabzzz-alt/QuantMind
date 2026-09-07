import json
from pathlib import Path
import tempfile
import unittest

from run_quantbot_session import summarize_events


class TranscriptTest(unittest.TestCase):
    def test_observable_tools_are_deduplicated_and_model_usage_is_preserved(self):
        call = {"type": "plugin_call", "status": "completed", "content": [
            {"type": "data", "data": {"call_id": "c1", "name": "read_file", "arguments": "{}"}}]}
        data = [call, call, {"object": "response", "status": "completed"},
                {"type": "reasoning", "content": [{"text": "not part of summary"}]},
                {"type": "turn_usage", "usage": {"model_name": "actual-model", "total_tokens": 123}}]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.sse"
            path.write_text("\n".join("data: " + json.dumps(d) for d in data) + "\ndata: [DONE]\n")
            result = summarize_events(path)
        self.assertEqual(result["tool_call_count"], 1)
        self.assertEqual(result["model_usage"]["total_tokens"], 123)
        self.assertNotIn("not part of summary", json.dumps(result))

    def test_no_terminal_event_is_not_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            result = summarize_events(Path(temp) / "missing.sse")
        self.assertIsNone(result["agent_response_status"])
        self.assertEqual(result["tool_call_count"], 0)


if __name__ == "__main__":
    unittest.main()
