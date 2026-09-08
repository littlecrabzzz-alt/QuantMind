"""HTTP failures retain immutable, redacted response evidence without network."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import tushare_intake as intake  # noqa: E402
from backend.shared.tushare_pipeline import verify_data  # noqa: E402

TOKEN = "fixture-token-not-a-real-credential"
JOB = {
    "api_name": "trade_cal",
    "params": {"exchange": "SSE", "start_date": "20260904", "end_date": "20260904"},
    "fields": "cal_date,is_open",
    "row_cap": 6000,
    "required_fields": ["cal_date", "is_open"],
}


class HttpEvidence(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="tushare-http-evidence-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guard = patch(
                target, side_effect=AssertionError("No network or credentials")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def capture(self, status, body):
        def handle(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["token"], TOKEN)
            self.assertEqual(payload["params"], JOB["params"])
            return httpx.Response(status, content=body)

        with httpx.Client(
            transport=httpx.MockTransport(handle), trust_env=False
        ) as client:
            return intake.capture_sample(client, TOKEN, JOB, self.root)

    def saved(self, result):
        raw = (self.root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
        observation = (self.root / "observations" / result["observation"]).read_bytes()
        self.assertEqual(intake.digest(raw), result["object_sha256"])
        self.assertEqual(intake.digest(observation), result["observation_sha256"])
        return raw, json.loads(observation)

    def test_429_500_401_json_and_html_are_complete_but_never_data(self):
        # Even an apparent code=0/data payload is rejected under an HTTP error.
        bodies = [
            b'{"code":0,"data":{"fields":["cal_date","is_open"],"items":[["20260904",1]]}}',
            b"<html><body>Upstream unavailable</body></html>",
        ]
        with patch.object(
            intake,
            "assess_response",
            side_effect=AssertionError("HTTP error cannot be assessed as data"),
        ):
            for status in (429, 500, 401):
                for body in bodies:
                    with self.subTest(status=status, body=body[:5]):
                        result = self.capture(status, body)
                        raw, observation = self.saved(result)
                        self.assertEqual(raw, body)
                        self.assertEqual(
                            result["status"],
                            "rate_limited" if status == 429 else "transport_error",
                        )
                        self.assertEqual(result["http_status"], status)
                        self.assertEqual(result["error_type"], "HTTPStatusError")
                        self.assertTrue(result["response_complete"])
                        self.assertEqual(
                            result["response_format"],
                            "json" if body.startswith(b"{") else "non_json",
                        )
                        self.assertEqual(
                            observation["assessment"]["http_status"], status
                        )
                        self.assertNotIn("token", observation["request"])
                        self.assertNotIn("row_count", result)
                        self.assertNotIn("parquet", result)

    def test_secret_echo_is_redacted_before_hash_and_persistence(self):
        for status in (429, 500, 401):
            for body in (
                json.dumps({"msg": "echo " + TOKEN}).encode(),
                ("<html>echo " + TOKEN + "</html>").encode(),
            ):
                result = self.capture(status, body)
                raw, observation = self.saved(result)
                self.assertEqual(
                    raw, body.replace(TOKEN.encode(), b"[REDACTED_SECRET]")
                )
                self.assertTrue(observation["response_redacted"])
                self.assertNotIn(TOKEN, json.dumps(result))
        for path in self.root.rglob("*.json"):
            self.assertNotIn(TOKEN.encode(), path.read_bytes())

    def test_equal_error_bodies_dedupe_objects_but_keep_observations_and_status(self):
        body = b"<html>temporarily blocked</html>"
        first = self.capture(429, body)
        first_raw, first_observation = self.saved(first)
        results = [first, self.capture(500, body), self.capture(401, body)]
        self.assertEqual(len({result["object_sha256"] for result in results}), 1)
        self.assertEqual(len({result["observation"] for result in results}), 3)
        self.assertEqual(len(list((self.root / "objects").glob("*.json"))), 1)
        self.assertEqual(len(list((self.root / "observations").glob("*.json"))), 3)
        self.assertEqual(self.saved(first), (first_raw, first_observation))
        different = self.capture(500, body + b"new version")
        self.assertNotEqual(different["object_sha256"], first["object_sha256"])
        obj = self.root / "objects" / (first["object_sha256"] + ".json")
        obj.write_bytes(b"corrupted existing evidence")
        with self.assertRaisesRegex(ValueError, "Existing object checksum mismatch"):
            self.capture(429, body)
        self.assertEqual(obj.read_bytes(), b"corrupted existing evidence")
        self.assertEqual(len(list((self.root / "observations").glob("*.json"))), 4)

    def test_error_evidence_verifies_under_existing_probe_and_fixed_release_format(
        self,
    ):
        results = [
            self.capture(429, b"<html>wait</html>"),
            self.capture(500, b'{"error":"later"}'),
        ]
        probe = "probe-" + "a" * 32
        folder = self.root / "releases" / probe
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_bytes(intake.json_bytes({"results": results}))
        verified = intake.verify_release(self.root, probe)
        self.assertEqual(verified["observations"], 2)
        self.assertEqual(verified["unarchived_requests"], 0)
        files = {}
        for result in results:
            for name in (
                "objects/" + result["object_sha256"] + ".json",
                "observations/" + result["observation"],
            ):
                body = (self.root / name).read_bytes()
                files[name] = {"sha256": intake.digest(body), "bytes": len(body)}
        manifest = intake.json_bytes({"files": files, "datasets": []})
        release = "data-" + intake.digest(manifest)
        folder = self.root / "releases" / release
        folder.mkdir()
        (folder / "manifest.json").write_bytes(manifest)
        self.assertEqual(verify_data(self.root, release)["files"], files)

    def test_interrupted_response_never_fabricates_complete_evidence(self):
        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"<html>partial " + TOKEN.encode()
                raise httpx.ReadError(TOKEN)

        def timeout(request):
            raise httpx.ReadTimeout(TOKEN, request=request)

        for handler in (timeout, lambda _: httpx.Response(500, stream=BrokenStream())):
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = intake.capture_sample(client, TOKEN, JOB, self.root)
            self.assertEqual(result["status"], "transport_error")
            self.assertFalse(result["response_complete"])
            self.assertNotIn("observation", result)
            self.assertNotIn("object_sha256", result)
            self.assertNotIn(TOKEN, json.dumps(result))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_caller_status_exception_keeps_http_classification_and_only_read_body(self):
        request = httpx.Request("POST", intake.API_ROOT)
        for complete in (True, False):
            response = httpx.Response(
                429,
                request=request,
                **(
                    {"content": b"<html>rate limited</html>"}
                    if complete
                    else {"stream": httpx.ByteStream(b"not read")}
                ),
            )
            with patch.object(
                httpx.Client,
                "post",
                side_effect=httpx.HTTPStatusError(
                    TOKEN, request=request, response=response
                ),
            ):
                with httpx.Client(trust_env=False) as client:
                    result = intake.capture_sample(client, TOKEN, JOB, self.root)
            self.assertEqual(result["status"], "rate_limited")
            self.assertEqual(result["http_status"], 429)
            self.assertEqual(result["response_complete"], complete)
            self.assertNotIn(TOKEN, json.dumps(result))
            if complete:
                self.assertEqual(self.saved(result)[0], b"<html>rate limited</html>")
            else:
                self.assertNotIn("observation", result)

    def test_200_invalid_and_successful_payload_behavior_is_retained(self):
        result = self.capture(200, b"<html>unexpected success body</html>")
        self.assertEqual(result["status"], "invalid_response")
        self.assertTrue(result["response_complete"])
        self.assertEqual(self.saved(result)[0], b"<html>unexpected success body</html>")
        result = self.capture(
            200,
            b'{"code":0,"data":{"fields":["cal_date","is_open"],"items":[["20260904",1]]}}',
        )
        self.assertEqual(result["status"], "sample_ok")
        self.assertEqual(result["row_count"], 1)
        result = self.capture(200, b'{"code":2002}')
        self.assertEqual(result["status"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
