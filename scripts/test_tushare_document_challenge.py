"""Retained script challenge classification; no JS, cookies, sockets or services."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs
from scripts.test_tushare_documents import Response, connection, resolution

# Inert comment containing the observed signature, not executable supplier code.
CHALLENGE = (
    b"<script>/* EO_Bot_Ssid= __tst_status= cookie location.href setTimeout */</script>"
)


class DocumentChallenge(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="qm-script-challenge-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for target in ("socket.socket.connect", "subprocess.Popen"):
            guard = patch(
                target, side_effect=AssertionError("No network or script processes")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def fetch(
        self,
        body=CHALLENGE,
        *,
        status=200,
        encoding=None,
        url="https://example.com/report.pdf",
    ):
        headers = {"Content_Type": "application/pdf", "Content_Length": str(len(body))}
        if encoding:
            headers["Content_Encoding"] = encoding
        conn = connection(Response(body, status=status, **headers))
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=conn),
            patch.object(
                docs,
                "_parse_pdf",
                side_effect=AssertionError("Never parse a challenge"),
            ),
        ):
            result = docs.fetch_document(url, self.root, download_only=True)
        conn.request.assert_called_once()
        self.assertNotIn("Cookie", conn.request.call_args.kwargs["headers"])
        artifact = result["files"][0]
        self.assertEqual(
            artifact["path"], "attachments/" + hashlib.sha256(body).hexdigest() + ".bin"
        )
        self.assertEqual((self.root / artifact["path"]).read_bytes(), body)
        self.assertEqual(result["received_bytes"], len(body))
        self.assertTrue(result["raw_complete"])
        self.assertEqual(result["parse_status"], "not_attempted")
        return result

    def test_script_only_challenge_has_explicit_gap_and_immutable_bytes(self):
        result = self.fetch()
        self.assertEqual(result["status"], "source_challenge")
        self.assertEqual(result["content_kind"], "script_challenge")
        self.assertEqual(result["challenge_kind"], "javascript_cookie_reload")
        self.assertEqual(result["validation_status"], "unexpected_content")
        self.assertNotIn("document_sha256", result)
        self.assertEqual(self.fetch()["files"], result["files"])

    def test_signature_is_narrow_and_other_failures_keep_their_meaning(self):
        for body in (
            b"<script>ordinary script</script>",
            CHALLENGE.replace(b"EO_Bot_Ssid=", b"unknown="),
            b"x" * 16385 + CHALLENGE,
        ):
            result = self.fetch(body)
            self.assertEqual(result["status"], "pdf_content_mismatch")
            self.assertNotIn("challenge_kind", result)
        self.assertEqual(self.fetch(status=403)["status"], "http_error")
        encoded = self.fetch(encoding="gzip")
        self.assertEqual(encoded["status"], "unsupported_content_encoding")
        self.assertNotIn("challenge_kind", encoded)

    def test_terminal_gap_persists_and_does_not_retry_same_job(self):
        args = (
            self.root,
            "observations/test.json",
            "research_report",
            [{"url": "https://example.com/report.pdf"}],
            ["url"],
        )
        docs.enqueue_documents(*args)
        result = self.fetch()
        with patch.object(docs, "_download_job", return_value=result) as download:
            self.assertEqual(
                docs.run_documents(self.root, 1, 2, download_workers=2)["processed"], 1
            )
            # Re-registration/reopening doesn't retry the existing blocked job.
            self.assertEqual(docs.enqueue_documents(*args)["existing"], 1)
            self.assertEqual(
                docs.run_documents(self.root, 3, 2, download_workers=2)["processed"], 0
            )
            download.assert_called_once()
        inventory = docs.document_inventory(self.root)
        mapping = inventory["mappings"][0]
        self.assertEqual(mapping["download_status"], "blocked")
        self.assertEqual(mapping["download_tries"], 1)
        self.assertEqual(mapping["parse_tries"], 0)
        self.assertEqual(mapping["latest_result"]["status"], "source_challenge")
        self.assertEqual(inventory["attempts"][0]["result"], result)
        files = {item["path"] for item in docs.document_index(self.root)["files"]}
        self.assertIn(result["files"][0]["path"], files)
        # The explicit gap is document-scoped; unrelated work remains runnable.
        docs.enqueue_documents(
            self.root,
            "observations/other.json",
            "anns_d",
            [{"url": "https://other.example/report.pdf"}],
            ["url"],
        )
        with patch.object(
            docs,
            "_download_job",
            return_value={
                "status": "download_timeout",
                "parse_status": "not_attempted",
                "files": [],
                "raw_complete": False,
            },
        ) as download:
            self.assertEqual(
                docs.run_documents(self.root, 1, 2, download_workers=2)["processed"], 1
            )
            download.assert_called_once()
        self.assertEqual(
            docs.document_inventory(self.root)["attempts"][-1]["result"]["status"],
            "download_timeout",
        )


if __name__ == "__main__":
    unittest.main()
