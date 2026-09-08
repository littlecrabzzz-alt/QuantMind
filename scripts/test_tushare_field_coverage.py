"""Explicit request coverage, isolated immutable evidence and zero real network."""

import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared.tushare_intake import capture_sample


class FieldCoverageAcceptance(unittest.TestCase):
    def capture(
        self,
        fields,
        items,
        *,
        requested="ts_code,hidden",
        cap=100,
        code=0,
        http_status=200,
        extra_data=None,
    ):
        payload = {
            "code": code,
            "data": {"fields": fields, "items": items, **(extra_data or {})},
        }
        job = {
            "api_name": "synthetic",
            "params": {},
            "fields": requested,
            "row_cap": cap,
            "required_fields": ["ts_code"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = httpx.Response(http_status, json=payload)
            with patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ):
                with httpx.Client(
                    transport=httpx.MockTransport(lambda _: response)
                ) as client:
                    result = capture_sample(
                        client, "synthetic-not-a-credential", job, root
                    )
            observed = json.loads(
                (root / "observations" / result["observation"]).read_bytes()
            )
            raw = (root / "objects" / (result["object_sha256"] + ".json")).read_bytes()
            self.assertEqual(raw, response.content)
            self.assertEqual(observed["request"]["fields"], requested)
            for field in (
                "status",
                "field_coverage",
                "requested_missing_fields",
                "unexpected_returned_fields",
            ):
                self.assertEqual(result[field], observed["assessment"][field])
            return result, json.loads(raw)

    def test_missing_nonrequired_hidden_field_is_persistent_gap(self):
        result, _ = self.capture(["ts_code"], [["000001.SZ"]])
        self.assertEqual(result["status"], "schema_gap")
        self.assertEqual(result["field_coverage"], "gap")
        self.assertEqual(result["requested_missing_fields"], ["hidden"])
        self.assertEqual(result["missing_fields"], [])
        self.assertFalse(result["history_complete"])

    def test_null_is_present_and_new_source_columns_survive(self):
        result, raw = self.capture(
            ["ts_code", "hidden", "new_source"], [["000001.SZ", None, {"raw": 0}]]
        )
        self.assertEqual(result["status"], "sample_ok")
        self.assertEqual(result["field_coverage"], "complete_for_explicit_request")
        self.assertEqual(result["requested_missing_fields"], [])
        self.assertEqual(result["unexpected_returned_fields"], ["new_source"])
        self.assertEqual(raw["data"]["items"][0], ["000001.SZ", None, {"raw": 0}])

    def test_empty_cap_and_continuation_keep_status_and_gap(self):
        for items, cap, extra, status in (
            ([], 100, {}, "empty_unverified"),
            ([["000001.SZ"]], 1, {}, "possibly_truncated"),
            ([["000001.SZ"]], 100, {"has_more": True}, "possibly_truncated"),
        ):
            with self.subTest(status=status, extra=extra):
                result, _ = self.capture(["ts_code"], items, cap=cap, extra_data=extra)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["field_coverage"], "gap")
                self.assertEqual(result["requested_missing_fields"], ["hidden"])

    def test_errors_cannot_certify_schema_even_with_data(self):
        for code, http_status, status in (
            (2002, 200, "permission_denied"),
            (0, 429, "rate_limited"),
        ):
            result, _ = self.capture(
                ["ts_code", "hidden"],
                [["000001.SZ", None]],
                code=code,
                http_status=http_status,
            )
            self.assertEqual(result["status"], status)
            self.assertEqual(result["field_coverage"], "unverified_default_or_invalid")
            self.assertIsNone(result["requested_missing_fields"])

    def test_default_or_invalid_request_does_not_claim_all_fields(self):
        for requested in ("", "*", "ts_code,,hidden", None):
            result, _ = self.capture(["ts_code"], [["000001.SZ"]], requested=requested)
            self.assertEqual(result["status"], "sample_ok")
            self.assertEqual(result["field_coverage"], "unverified_default_or_invalid")
            self.assertIsNone(result["requested_missing_fields"])

    def test_invalid_response_does_not_claim_schema_coverage(self):
        result, _ = self.capture(["ts_code", "hidden"], [["000001.SZ"]])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(result["field_coverage"], "unverified_default_or_invalid")

    def test_required_gap_remains_separate(self):
        result, _ = self.capture(["hidden"], [[None]])
        self.assertEqual(result["missing_fields"], ["ts_code"])
        self.assertEqual(result["requested_missing_fields"], ["ts_code"])
        self.assertEqual(result["status"], "schema_gap")

    def test_transport_failure_has_explicit_unverified_coverage(self):
        def fail(request):
            raise httpx.ConnectError("synthetic", request=request)

        with (
            tempfile.TemporaryDirectory() as tmp,
            httpx.Client(transport=httpx.MockTransport(fail)) as client,
        ):
            result = capture_sample(
                client,
                "synthetic-not-a-credential",
                {
                    "api_name": "synthetic",
                    "params": {},
                    "fields": "hidden",
                    "row_cap": 100,
                    "required_fields": [],
                },
                Path(tmp),
            )
            self.assertEqual(result["status"], "transport_error")
            self.assertEqual(result["field_coverage"], "unverified_default_or_invalid")
            self.assertIsNone(result["requested_missing_fields"])
            self.assertFalse(list(Path(tmp).iterdir()))


if __name__ == "__main__":
    unittest.main()
