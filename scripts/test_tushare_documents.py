#!/usr/bin/env python3
"""Simulated acquisition + a locally generated two-page PDF; never contacts APIs."""

import hashlib
import io
import json
from pathlib import Path
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


class Documents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

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
            self.assertEqual(result["files"], [])
        self.assertEqual(list(self.root.iterdir()), [])

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


if __name__ == "__main__":
    unittest.main()
