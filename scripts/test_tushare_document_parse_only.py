"""Parse-only document runs: parse already-downloaded PDFs, never download."""

import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402


class ParseOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tushare-parse-only-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(socket.socket, "connect", side_effect=AssertionError("No network")).start()
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")).start()
        self.pdf = docs._save(self.root, "attachments", ".pdf", b"%PDF-fixture\n%%EOF",
                              "application/pdf")
        db = docs._document_db(self.root)
        for i, (download, parse) in enumerate([("pending", "not_attempted"),
                                               ("pending", "not_attempted"),
                                               ("downloaded", "parse_pending")]):
            ident = hashlib.sha256(str(i).encode()).hexdigest()
            result = {"status": "downloaded", "mime": "application/pdf",
                      "parse_status": "parse_pending", "files": [self.pdf]} if download == "downloaded" else {}
            db.execute("INSERT INTO documents(id,observation,url,expected_mime,download_status,"
                       "parse_status,result) VALUES(?,?,?,?,?,?,?)",
                       (ident, f"obs-{i}", f"https://example.com/{i}", "application/pdf",
                        download, parse, json.dumps(result)))
        db.commit()
        db.close()

    def states(self):
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            return sorted(db.execute("SELECT download_status,parse_status FROM documents").fetchall())

    def parsed(self, *args, **kwargs):
        return {"parse_status": "parsed", "page_count": 1,
                "pages": [{"page_number": 1, "text": "正文"}], "parser": "pypdf"}

    def test_parse_only_never_downloads_and_parses_saved_pdf(self):
        with patch.object(docs, "_download_job", side_effect=AssertionError("download attempted")), \
                patch.object(docs, "_parse_pdf", side_effect=self.parsed):
            report = docs.run_documents(self.root, max_documents=10, max_seconds=30, phases=("parse",))
        self.assertEqual(report["phase_counts"].get("download", 0), 0)
        self.assertEqual(self.states(), [("downloaded", "parsed"),
                                         ("pending", "not_attempted"),
                                         ("pending", "not_attempted")])
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            result = json.loads(db.execute(
                "SELECT result FROM documents WHERE download_status='downloaded'").fetchone()[0])
        self.assertTrue(any(f["path"].startswith("extracted/") for f in result["files"]))

    def test_parse_only_with_parallel_options_still_never_downloads(self):
        with patch.object(docs, "_download_job", side_effect=AssertionError("download attempted")), \
                patch.object(docs, "_parse_pdf", side_effect=self.parsed):
            docs.run_documents(self.root, max_documents=10, max_seconds=30, phases=("parse",),
                               download_workers=4, overlap_parse_download=True, parse_workers=1)
        self.assertIn(("downloaded", "parsed"), self.states())
        self.assertEqual(self.states().count(("pending", "not_attempted")), 2)

    def test_default_phases_unchanged(self):
        import inspect
        self.assertIn("phases", inspect.signature(docs.run_documents).parameters)
        self.assertIsNone(inspect.signature(docs.run_documents).parameters["phases"].default)

    def test_invalid_phase_rejected(self):
        with self.assertRaises(ValueError):
            docs.run_documents(self.root, max_documents=1, max_seconds=30, phases=("upload",))


if __name__ == "__main__":
    unittest.main()
