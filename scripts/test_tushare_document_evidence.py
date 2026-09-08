"""Unexpected attachment responses stay immutable evidence, never parsed text."""

import gzip
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402
from scripts.test_tushare_documents import Response, connection, resolution  # noqa: E402


class Evidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tushare-evidence-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.net = patch.object(
            socket.socket, "connect", side_effect=AssertionError("No network")
        ).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.net.assert_not_called()

    def fetch(self, response, **kwargs):
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=connection(response)),
            patch.object(
                docs,
                "_parse_pdf",
                side_effect=AssertionError("Never parse unexpected content"),
            ),
        ):
            return docs.fetch_document(
                "https://example.com/report.pdf",
                self.root,
                download_only=True,
                **kwargs,
            )

    def assert_evidence(self, result, body, status, kind):
        self.assertEqual(result["status"], status)
        self.assertEqual(result["content_kind"], kind)
        self.assertTrue(result["raw_complete"])
        self.assertEqual(result["received_bytes"], len(body))
        self.assertEqual(result["validation_status"], "unexpected_content")
        self.assertEqual(result["parse_status"], "not_attempted")
        self.assertNotIn("mime", result)
        self.assertEqual(len(result["files"]), 1)
        item = result["files"][0]
        self.assertEqual(
            item["path"], "attachments/" + hashlib.sha256(body).hexdigest() + ".bin"
        )
        self.assertEqual(item["mime"], "application/octet-stream")
        self.assertEqual((self.root / item["path"]).read_bytes(), body)

    def test_html_error_with_only_bounded_allowlisted_headers(self):
        body = b"<html><body>Access denied</body></html>"
        result = self.fetch(
            Response(
                body,
                Content_Type="application/pdf",
                Content_Length=str(len(body)),
                Set_Cookie="private",
                Authorization="private",
                Location="https://secret@example.com/",
                Server="private",
            )
        )
        self.assert_evidence(result, body, "pdf_content_mismatch", "html")
        self.assertEqual(
            result["response_headers"],
            {"content-type": "application/pdf", "content-length": str(len(body))},
        )
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["http_status"], 200)
        repeat = self.fetch(Response(body, Content_Type="application/pdf"))
        self.assertEqual(repeat["files"], result["files"])
        long_header = self.fetch(Response(body, Content_Type="a" * 2000))
        self.assertEqual(len(long_header["response_headers"]["content-type"]), 1024)
        self.assertEqual(long_header["response_headers_truncated"], ["content-type"])

    def test_encoded_and_malformed_pdf_remain_uninterpreted(self):
        compressed = gzip.compress(b"%PDF-fixture\n%%EOF")
        for encoding in ("gzip", "identity"):
            result = self.fetch(
                Response(
                    compressed,
                    Content_Type="application/pdf",
                    Content_Encoding=encoding,
                )
            )
            self.assert_evidence(
                result, compressed, "unsupported_content_encoding", "encoded_body"
            )
        malformed = b"%PDF-1.7\ntruncated or malformed file"
        result = self.fetch(Response(malformed, Content_Type="application/pdf"))
        self.assert_evidence(
            result, malformed, "pdf_content_mismatch", "malformed_pdf_envelope"
        )
        binary = b"unrecognized binary\x00"
        result = self.fetch(Response(binary, Content_Type="application/pdf"))
        self.assert_evidence(result, binary, "pdf_content_mismatch", "unknown")

    def test_non200_and_mime_mismatch_keep_raw_with_failure_status(self):
        for status in (403, 404, 429, 503):
            body = b"<html>service unavailable</html>"
            result = self.fetch(Response(body, status=status, Content_Type="text/html"))
            self.assert_evidence(result, body, "http_error", "html")
            self.assertEqual(result["http_status"], status)
        body = b"%PDF-fixture\n%%EOF"
        result = self.fetch(Response(body, Content_Type="text/html"))
        self.assert_evidence(result, body, "mime_content_mismatch", "pdf_envelope")

    def test_limits_truncation_and_timeout_never_claim_complete_raw(self):
        class TimedOut(Response):
            def read(self, size):
                if self.tell():
                    raise TimeoutError("fixture socket timeout")
                return super().read(size)

        cases = [
            (Response(b"x" * 11, status=500), {"max_bytes": 10}, "size_limit"),
            (Response(b"x", Content_Length="20"), {"max_bytes": 10}, "size_limit"),
            (Response(b"x", Content_Length="2"), {}, "incomplete_download"),
            (TimedOut(b"<html>partial"), {}, "download_error"),
        ]
        for response, kwargs, status in cases:
            result = self.fetch(response, **kwargs)
            self.assertEqual(result["status"], status)
            self.assertFalse(result["raw_complete"])
            self.assertEqual(result["files"], [])
        self.assertFalse((self.root / "attachments").exists())

    def test_retries_and_both_indexes_keep_all_evidence_versions(self):
        docs.enqueue_documents(
            self.root,
            "observations/test.json",
            "anns_d",
            [{"url": "https://example.com/report.pdf"}],
            ["url"],
        )
        bodies = [b"<html>first failure</html>", b"<html>second failure</html>"]
        for body in bodies:
            result = self.fetch(Response(body, Content_Type="application/pdf"))
            with patch.object(docs, "_download_job", return_value=result):
                docs.run_documents(self.root, 1, 2, download_workers=2)
            db = docs._document_db(self.root)
            db.execute("UPDATE documents SET retry_after=0")
            db.commit()
            db.close()
        old = docs.document_inventory(self.root)
        current = docs.document_index(self.root)
        for body in bodies:
            path = "attachments/" + hashlib.sha256(body).hexdigest() + ".bin"
            self.assertIn(path, {item["path"] for item in old["files"]})
            self.assertIn(path, {item["path"] for item in current["files"]})
        self.assertEqual(len(old["attempts"]), 2)
        self.assertTrue(all(item["result"]["raw_complete"] for item in old["attempts"]))
        latest = old["mappings"][0]["latest_result"]
        self.assertEqual(latest["status"], "pdf_content_mismatch")
        self.assertEqual(old["counts"][0]["download_status"], "retry")
        db = docs._document_db(self.root)
        self.assertEqual(
            tuple(
                db.execute(
                    "SELECT download_tries,parse_tries FROM documents"
                ).fetchone()
            ),
            (2, 0),
        )
        db.close()
        # Evidence left by a process after save but before queue commit is retained too.
        orphan = self.fetch(
            Response(b"<html>orphan</html>", Content_Type="application/pdf")
        )["files"][0]
        self.assertIn(
            orphan["path"],
            {item["path"] for item in docs.document_index(self.root)["files"]},
        )
        (self.root / orphan["path"]).unlink()
        (self.root / orphan["path"]).symlink_to(self.root / "outside")
        with self.assertRaisesRegex(docs.DocumentError, "unsafe_storage_path"):
            docs.document_index(self.root)


if __name__ == "__main__":
    unittest.main()
