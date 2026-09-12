#!/usr/bin/env python3
"""Simulated acquisition + a locally generated two-page PDF; never contacts APIs."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, **headers):
        super().__init__(body)
        self.status = status
        self.headers = {k.lower().replace("_", "-"): v for k, v in headers.items()}

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)


def resolution(ip="93.184.216.34"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def connection(response):
    conn = Mock()
    conn.getresponse.return_value = response
    return conn


def pdf():
    from reportlab.pdfgen.canvas import Canvas

    stream = io.BytesIO()
    canvas = Canvas(stream, invariant=1)
    for number in (1, 2):
        canvas.drawString(72, 720, f"QuantMind document fixture page {number}")
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def broken_xref_pdf():
    body = pdf()
    match = re.search(rb"startxref\s+(\d+)", body)
    replacement = str(int(match.group(1)) + 1).encode()
    assert len(replacement) == len(match.group(1))
    return body[: match.start(1)] + replacement + body[match.end(1) :]


class Documents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def fetch(self, response, url="https://example.com/report.pdf", **options):
        conn = connection(response)
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=conn),
        ):
            result = docs.fetch_document(url, self.root, **options)
        return result, conn

    def test_real_pdf_pages_and_immutable_repeats(self):
        body = pdf()
        first, conn = self.fetch(
            Response(
                body, Content_Type="application/pdf", Content_Length=str(len(body))
            )
        )
        self.assertEqual(first["status"], "downloaded")
        if first["parse_status"] == "parse_unavailable":
            if first["parse_detail"]["reason"] == "pypdf_not_installed":
                self.assertEqual(len(first["files"]), 1)
                self.skipTest("pypdf not installed; graceful preservation checked")
            # macOS does not implement RLIMIT_AS. Only this known generated
            # fixture may exercise the extraction core without the worker;
            # production keeps parse_unavailable instead of weakening limits.
            self.assertEqual(
                first["parse_detail"]["reason"], "resource_limits_unavailable"
            )
            with patch.object(
                docs,
                "_parse_pdf",
                side_effect=lambda path, timeout: docs._extract_pdf(path),
            ):
                first, conn = self.fetch(Response(body, Content_Type="application/pdf"))
        self.assertEqual(first["parse_status"], "parsed", first)
        self.assertEqual(len(first["files"]), 2)
        pages = json.loads((self.root / first["files"][1]["path"]).read_text())["pages"]
        self.assertEqual([p["page_number"] for p in pages], [1, 2])
        self.assertIn("fixture page 2", pages[1]["text"])
        self.assertNotIn("parser_mode", first["parse_detail"])
        with patch.object(
            docs,
            "_parse_pdf",
            side_effect=lambda path, timeout: docs._extract_pdf(path),
        ):
            second, _ = self.fetch(Response(body, Content_Type="application/pdf"))
        self.assertEqual(first["files"], second["files"])
        for item in first["files"]:
            content = (self.root / item["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"])
            self.assertEqual(len(content), item["bytes"])
        headers = conn.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_broken_xref_lenient_fallback_preserves_raw(self):
        body = broken_xref_pdf()
        raw = docs._save(
            self.root, "attachments", ".pdf", body, "application/pdf"
        )
        original = (self.root / raw["path"]).read_bytes()
        with patch.object(
            docs,
            "_parse_pdf",
            side_effect=lambda path, timeout: docs._extract_pdf(path),
        ):
            result = docs._parse_saved(
                self.root,
                {"status": "downloaded", "parse_status": "parse_failed", "files": [raw]},
                15,
            )
            repeated = docs._parse_saved(
                self.root,
                {"status": "downloaded", "parse_status": "parse_failed", "files": [raw]},
                15,
            )
        self.assertEqual(result["parse_status"], "parsed")
        self.assertEqual(result["validation_status"], "pdf_structure_valid")
        self.assertEqual(result["parse_detail"]["parser_mode"], "lenient_fallback")
        self.assertEqual(result["parse_detail"]["strict_error_type"], "PdfReadError")
        self.assertEqual((self.root / raw["path"]).read_bytes(), original)
        self.assertEqual(hashlib.sha256(original).hexdigest(), raw["sha256"])
        self.assertEqual(result["files"], repeated["files"])
        extracted = json.loads((self.root / result["files"][1]["path"]).read_text())
        self.assertEqual(extracted["parser_mode"], "lenient_fallback")
        self.assertEqual([page["page_number"] for page in extracted["pages"]], [1, 2])

    def test_lenient_fallback_failure_stays_failed(self):
        import pypdf

        with patch.object(
            pypdf,
            "PdfReader",
            side_effect=[
                pypdf.errors.PdfReadError("strict failure"),
                RuntimeError("lenient failure"),
            ],
        ):
            result = docs._extract_pdf(self.root / "unused.pdf")
        self.assertEqual(
            result,
            {
                "parse_status": "parse_failed",
                "error_type": "RuntimeError",
                "strict_error_type": "PdfReadError",
            },
        )

    def test_url_and_dns_denials(self):
        urls = [
            "file:///etc/passwd",
            "https://user:secret@example.com/a",
            "https://example.com:8443/a",
            "http://127.0.0.1/a",
            "http://[::1]/a",
            "http://169.254.169.254/a",
            "http://[::ffff:93.184.216.34]/a",
            "https://example.com/\nfoo",
            "https://example.com\\@127.0.0.1/",
            "http://localhost/a",
        ]
        with (
            patch.object(docs.socket, "getaddrinfo") as resolver,
            patch.object(docs, "_connection") as connect,
        ):
            for url in urls:
                result = docs.fetch_document(url, self.root)
                self.assertNotEqual(result["status"], "downloaded", url)
            resolver.assert_not_called()
            connect.assert_not_called()
        with (
            patch.object(
                docs.socket,
                "getaddrinfo",
                return_value=resolution() + resolution("10.0.0.1"),
            ),
            patch.object(docs, "_connection") as connect,
        ):
            result = docs.fetch_document("https://example.com/a", self.root)
            self.assertEqual(result["status"], "non_public_address")
            connect.assert_not_called()

    def test_redirect_validation_and_limit(self):
        public = connection(Response(status=302, Location="http://127.0.0.1/admin"))
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=public) as connect,
        ):
            result = docs.fetch_document("https://example.com/a", self.root)
            self.assertEqual(result["status"], "non_public_address")
            self.assertEqual(connect.call_count, 1)
        chain = [
            connection(Response(status=302, Location=f"/redirect-{n}"))
            for n in range(4)
        ]
        with (
            patch.object(
                docs.socket, "getaddrinfo", return_value=resolution()
            ) as resolver,
            patch.object(docs, "_connection", side_effect=chain),
        ):
            result = docs.fetch_document("https://example.com/a", self.root)
            self.assertEqual(result["status"], "redirect_limit")
            self.assertEqual(resolver.call_count, 4)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_ip_connection_pins_tls_hostname(self):
        with patch.object(
            docs.socket, "getaddrinfo", return_value=resolution()
        ) as resolver:
            _, scheme, host, port, _, address = docs._target("https://example.com/a")
        sock, context = Mock(), Mock()
        with (
            patch.object(docs.socket, "socket", return_value=sock),
            patch.object(docs.ssl, "create_default_context", return_value=context),
        ):
            conn = docs._connection(scheme, host, port, address, 20)
        resolver.assert_called_once()
        sock.connect.assert_called_once_with(("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")
        self.assertIs(conn.sock, context.wrap_socket.return_value)

    def test_caps_incomplete_mismatch_and_http_errors(self):
        cases = [
            (Response(b"x" * 11), {"max_bytes": 10}, "size_limit"),
            (Response(b"", Content_Length="11"), {"max_bytes": 10}, "size_limit"),
            (Response(b"a", Content_Length="2"), {}, "incomplete_download"),
            (
                Response(b"<html>not a PDF</html>", Content_Type="application/pdf"),
                {},
                "pdf_content_mismatch",
            ),
            (
                Response(b"<html>not a PDF</html>", Content_Type="text/html"),
                {},
                "pdf_content_mismatch",
            ),
            (Response(b"", status=404), {}, "http_error"),
            (
                Response(b"", Content_Encoding="gzip"),
                {},
                "unsupported_content_encoding",
            ),
        ]
        for response, options, expected in cases:
            result, _ = self.fetch(response, **options)
            self.assertEqual(result["status"], expected)
            if expected in ("size_limit", "incomplete_download"):
                self.assertEqual(result["files"], [])
                self.assertFalse(result["raw_complete"])
            else:
                self.assertEqual(len(result["files"]), 1)
                self.assertTrue(result["raw_complete"])
                self.assertEqual(result["validation_status"], "unexpected_content")

    def test_pdf_survives_parser_failure_and_timeout(self):
        for state in (
            "parse_unavailable",
            "parse_failed",
            "encrypted",
            "parse_timeout",
        ):
            with patch.object(docs, "_parse_pdf", return_value={"parse_status": state}):
                result, _ = self.fetch(Response(pdf(), Content_Type="application/pdf"))
            self.assertEqual(result["status"], "downloaded")
            self.assertEqual(result["parse_status"], state)
            self.assertEqual(len(result["files"]), 1)
        with patch.object(
            docs.subprocess, "run", side_effect=subprocess.TimeoutExpired("parser", 1)
        ):
            self.assertEqual(
                docs._parse_pdf(self.root / "dummy", 1)["parse_status"], "parse_timeout"
            )

    def test_html_and_existing_corruption_or_symlink(self):
        body = b"<!DOCTYPE html><html><body>Original policy</body></html>"
        result, _ = self.fetch(
            Response(body, Content_Type="text/html"), url="https://example.com/policy"
        )
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["parse_status"], "not_applicable")
        path = self.root / result["files"][0]["path"]
        path.write_bytes(b"corrupt")
        retry, _ = self.fetch(
            Response(body, Content_Type="text/html"), url="https://example.com/policy"
        )
        self.assertEqual(retry["status"], "immutable_file_conflict")
        self.assertEqual(path.read_bytes(), b"corrupt")
        path.unlink()
        path.symlink_to(self.root / "elsewhere")
        retry, _ = self.fetch(
            Response(body, Content_Type="text/html"), url="https://example.com/policy"
        )
        self.assertEqual(retry["status"], "unsafe_storage_path")


class DocumentQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.network = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        )
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        )
        self.network.start()
        self.dns.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.dns.stop)

    def saved(self, body=None, *, mime="application/pdf", parse="parsed"):
        body = pdf() if body is None else body
        suffix = ".pdf" if mime == "application/pdf" else ".html"
        item = docs._save(self.root, "attachments", suffix, body, mime)
        return {
            "status": "downloaded",
            "parse_status": parse,
            "source_url": "https://example.com/original",
            "mime": mime,
            "document_sha256": item["sha256"],
            "files": [item],
        }

    def due(self):
        db = docs._document_db(self.root)
        with db:
            db.execute("UPDATE documents SET retry_after=0,parse_retry_after=0")
        db.close()

    def test_references_idempotence_empty_and_missing(self):
        rows = [
            {
                "title": "a",
                "url": "https://example.com/original",
                "_row_identity": "a" * 64,
            },
            {
                "title": "b",
                "url": None,
                "pub_time": datetime(2026, 9, 9, tzinfo=timezone.utc),
            },
        ]
        first = docs.enqueue_documents(self.root, "obs-1", "anns_d", rows, ["url"])
        again = docs.enqueue_documents(self.root, "obs-1", "anns_d", rows, ["url"])
        docs.enqueue_documents(self.root, "obs-empty", "anns_d", [], ["url"])
        self.assertEqual(first["enqueued"], 1)
        self.assertEqual(again["enqueued"], 0)
        self.assertEqual(again["existing"], 1)
        inventory = docs.document_inventory(self.root)
        self.assertEqual(len(inventory["mappings"]), 3)
        self.assertEqual(
            {r["status"] for r in inventory["mappings"]},
            {"queued", "missing_url", "no_records"},
        )
        self.assertEqual(inventory["files"], [])
        self.assertIn("a" * 64, [r["record_sha256"] for r in inventory["mappings"]])

    def test_bounded_resume_and_url_revision_bytes_preserved(self):
        for observation in ("old", "new"):
            docs.enqueue_documents(
                self.root,
                observation,
                "npr",
                [{"url": "https://example.com/original", "title": observation}],
                ["url"],
            )
        with patch.object(
            docs,
            "_download_job",
            side_effect=[
                self.saved(
                    b"<html>v1</html>", mime="text/html", parse="not_applicable"
                ),
                self.saved(
                    b"<html>v2</html>", mime="text/html", parse="not_applicable"
                ),
            ],
        ) as fetch:
            self.assertEqual(docs.run_documents(self.root)["processed"], 1)
            self.assertEqual(docs.run_documents(self.root)["processed"], 1)
            self.assertEqual(docs.run_documents(self.root)["processed"], 0)
            self.assertEqual(fetch.call_count, 2)
        inventory = docs.document_inventory(self.root)
        self.assertEqual(len(inventory["files"]), 2)
        self.assertEqual(len(inventory["attempts"]), 2)
        self.assertEqual(
            {r["observation"] for r in inventory["mappings"]}, {"old", "new"}
        )
        self.assertTrue(
            all(r["download_status"] == "downloaded" for r in inventory["mappings"])
        )

    def test_parse_retry_uses_saved_pdf_without_download(self):
        docs.enqueue_documents(
            self.root,
            "obs",
            "anns_d",
            [{"url": "https://example.com/report.pdf"}],
            ["url"],
        )
        with patch.object(
            docs, "_download_job", return_value=self.saved(parse="parse_unavailable")
        ) as fetch:
            docs.run_documents(self.root)
            self.assertEqual(docs.run_documents(self.root)["processed"], 0)
            self.due()
            with patch.object(
                docs,
                "_parse_pdf",
                return_value={
                    "parse_status": "parsed",
                    "page_count": 1,
                    "pages": [{"page_number": 1, "text": "retained evidence"}],
                },
            ):
                self.assertEqual(docs.run_documents(self.root)["processed"], 1)
            self.assertEqual(fetch.call_count, 1)
        inventory = docs.document_inventory(self.root)
        mapping = inventory["mappings"][0]
        self.assertEqual(
            (mapping["download_status"], mapping["parse_status"]),
            ("downloaded", "parsed"),
        )
        self.assertEqual(mapping["download_tries"], 1)
        self.assertEqual(len(inventory["files"]), 2)
        self.assertEqual(
            [a["phase"] for a in inventory["attempts"]], ["download", "parse"]
        )

    def test_download_failure_backoff_exhaustion_and_mime_check(self):
        docs.enqueue_documents(
            self.root,
            "obs",
            "anns_d",
            [{"url": "https://example.com/download"}],
            ["url"],
        )
        html = self.saved(
            b"<html>login</html>", mime="text/html", parse="not_applicable"
        )
        with patch.object(docs, "_download_job", return_value=html):
            docs.run_documents(self.root)
        result = docs.document_inventory(self.root)["mappings"][0]
        self.assertEqual(result["download_status"], "retry")
        self.assertEqual(result["latest_result"]["status"], "expected_mime_mismatch")
        reused = docs.enqueue_documents(
            self.root,
            "obs-retry",
            "anns_d",
            [{"url": "https://example.com/download"}],
            ["url"],
        )
        self.assertEqual((reused["enqueued"], reused["reused"]), (0, 1))
        with patch.object(
            docs,
            "_download_job",
            return_value={
                "status": "download_error",
                "parse_status": "not_attempted",
                "files": [],
            },
        ) as fetch:
            self.assertEqual(docs.run_documents(self.root)["processed"], 0)
            for _ in range(4):
                self.due()
                docs.run_documents(self.root)
            self.due()
            self.assertEqual(docs.run_documents(self.root)["processed"], 0)
            self.assertEqual(fetch.call_count, 4)
        inventory = docs.document_inventory(self.root)
        self.assertEqual(inventory["mappings"][0]["download_status"], "blocked")
        self.assertEqual(
            len(inventory["files"]), 1
        )  # Failed MIME bytes remain evidence.

    def test_cross_observation_reuse_preserves_fetch_time_and_parse_retry(self):
        original = {
            "title": "unchanged",
            "url": "https://example.com/original",
            "_row_identity": "b" * 64,
            "_fetched_at": "observation-one",
        }
        first = docs.enqueue_documents(
            self.root, "obs-one", "anns_d", [original], ["url"]
        )
        pending = docs.enqueue_documents(
            self.root,
            "obs-two",
            "anns_d",
            [{**original, "_fetched_at": "observation-two"}],
            ["url"],
        )
        self.assertEqual(first["enqueued"], 1)
        self.assertEqual((pending["enqueued"], pending["reused"]), (0, 1))
        result = {
            **self.saved(parse="parse_unavailable"),
            "fetched_at": "2026-09-09T01:00:00Z",
        }
        with patch.object(docs, "_download_job", return_value=result) as fetch:
            docs.run_documents(self.root)
            reused = docs.enqueue_documents(
                self.root, "obs-three", "anns_d", [original], ["url"]
            )
            repeated = docs.enqueue_documents(
                self.root, "obs-three", "anns_d", [original], ["url"]
            )
            self.assertEqual((reused["enqueued"], reused["reused"]), (0, 1))
            self.assertEqual(
                (repeated["enqueued"], repeated["reused"], repeated["existing"]),
                (0, 0, 1),
            )
            self.due()
            with patch.object(
                docs,
                "_parse_pdf",
                return_value={
                    "parse_status": "parsed",
                    "pages": [{"page_number": 1, "text": "text"}],
                },
            ):
                docs.run_documents(self.root)
            self.assertEqual(fetch.call_count, 1)
        mappings = docs.document_inventory(self.root)["mappings"]
        self.assertEqual(len(mappings), 3)
        self.assertEqual(len({m["document_id"] for m in mappings}), 1)
        self.assertEqual(
            {m["status"] for m in mappings}, {"queued", "reused_pending", "reused"}
        )
        self.assertEqual({m["validation_observation"] for m in mappings}, {"obs-one"})
        self.assertEqual(
            {m["latest_result"]["fetched_at"] for m in mappings}, {result["fetched_at"]}
        )
        self.assertTrue(all(m["parse_status"] == "parsed" for m in mappings))

    def test_changed_row_url_or_expected_mime_creates_work(self):
        original = {
            "title": "old",
            "url": "https://example.com/original",
            "_row_identity": "b" * 64,
        }
        changed_row = {**original, "title": "new", "_row_identity": "c" * 64}
        changed_url = {**original, "url": "https://example.com/new-url"}
        for observation, record in (
            ("old", original),
            ("changed-row", changed_row),
            ("changed-url", changed_url),
        ):
            stats = docs.enqueue_documents(
                self.root, observation, "anns_d", [record], ["url"]
            )
            self.assertEqual(stats["enqueued"], 1)
            self.assertEqual(stats["reused"], 0)
        with patch.object(docs, "_download_job", return_value=self.saved()) as fetch:
            self.assertEqual(
                docs.run_documents(self.root, max_documents=3)["processed"], 3
            )
            self.assertEqual(fetch.call_count, 3)
        # Simulate an older contract which accepted unspecified MIME for the
        # exact same API/row/field/URL. The new PDF requirement cannot reuse it.
        db = docs._document_db(self.root)
        with db:
            db.execute(
                "UPDATE documents SET expected_mime=NULL WHERE observation='old'"
            )
        db.close()
        stronger = docs.enqueue_documents(
            self.root, "stronger-mime", "anns_d", [original], ["url"]
        )
        self.assertEqual((stronger["enqueued"], stronger["reused"]), (1, 0))
        self.assertEqual(len(docs.document_inventory(self.root)["mappings"]), 4)

    def test_legacy_rows_ignore_acquisition_metadata_for_reuse(self):
        for observation in ("one", "two"):
            stats = docs.enqueue_documents(
                self.root,
                observation,
                "anns_d",
                [
                    {
                        "title": "unchanged",
                        "url": "https://example.com/original",
                        "_observation": observation,
                        "_fetched_at": observation,
                    }
                ],
                ["url"],
            )
        self.assertEqual((stats["enqueued"], stats["reused"]), (0, 1))
        mappings = docs.document_inventory(self.root)["mappings"]
        self.assertEqual(len({m["document_id"] for m in mappings}), 1)
        self.assertEqual(len(mappings), 2)

    def test_v1_index_migration_retains_existing_jobs(self):
        docs.enqueue_documents(
            self.root,
            "existing",
            "anns_d",
            [{"url": "https://example.com/original"}],
            ["url"],
        )
        db = docs._document_db(self.root)
        db.execute("DROP INDEX document_reference_reuse")
        db.execute("PRAGMA user_version=1")
        db.close()
        db = docs._document_db(self.root)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(db.execute("SELECT count(*) FROM documents").fetchone()[0], 1)
        self.assertTrue(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='document_reference_reuse'"
            ).fetchone()
        )
        self.assertTrue(
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='document_status_counts'"
            ).fetchone()
        )
        db.close()

    def test_worker_deadline_schema_and_unreferenced_files(self):
        worker = Mock(pid=123)
        worker.communicate.side_effect = [
            subprocess.TimeoutExpired("document", 1),
            (b"", b""),
        ]
        with (
            patch.object(docs.subprocess, "Popen", return_value=worker) as start,
            patch.object(docs.os, "killpg") as kill,
        ):
            result = docs._download_job("https://example.com/a", self.root, 1)
        self.assertEqual(result["status"], "download_timeout")
        self.assertTrue(start.call_args.kwargs["start_new_session"])
        kill.assert_called_once_with(123, docs.signal.SIGKILL)
        self.saved(parse="parse_unavailable")  # Simulate bytes saved before a crash.
        self.assertEqual(len(docs.document_inventory(self.root)["files"]), 1)
        db = docs._document_db(self.root)
        db.execute("PRAGMA user_version=99")
        db.close()
        with self.assertRaises(ValueError):
            docs.run_documents(self.root)


if __name__ == "__main__":
    unittest.main()
