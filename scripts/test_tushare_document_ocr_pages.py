"""Page-level parallel OCR: one long document must not serialize on one page at a time."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402


def blank_pdf(pages):
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class SlowClient:
    model = "fake-ocr"

    def __init__(self, fail_on=None):
        self.lock = threading.Lock()
        self.active = self.peak = self.calls = 0
        self.fail_on = fail_on

    def transcribe(self, png):
        with self.lock:
            self.calls += 1
            call = self.calls
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.05)
            if self.fail_on is not None and call == self.fail_on:
                raise RuntimeError("transient page failure")
            return f"page text {call}"
        finally:
            with self.lock:
                self.active -= 1


class PageParallel(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tushare-ocr-pages-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.staging = self.root / "staging"
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        from backend.shared import tushare_document_ocr as ocr
        self.ocr = ocr
        pdf = docs._save(self.root, "attachments", ".pdf", blank_pdf(12), "application/pdf")
        db = docs._document_db(self.root)
        result = {"status": "downloaded", "mime": "application/pdf", "parse_status": "no_text",
                  "document_sha256": pdf["sha256"], "files": [pdf]}
        db.execute("INSERT INTO documents(id,observation,url,expected_mime,download_status,parse_status,result)"
                   " VALUES(?,?,?,?,?,?,?)", (hashlib.sha256(b"d").hexdigest(), "obs", "https://example.com/d.pdf",
                                             "application/pdf", "downloaded", "no_text", json.dumps(result)))
        db.commit()
        db.close()
        self.item, = self.ocr.ocr_candidates(self.root, limit=10)

    def test_pages_of_one_document_run_concurrently(self):
        client = SlowClient()
        report = self.ocr.stage_document(self.root, self.staging, self.item, client,
                                         sleep=lambda s: None, page_workers=4)
        self.assertEqual(report, {"status": "staged", "pages": 12})
        self.assertGreaterEqual(client.peak, 3)
        self.assertLessEqual(client.peak, 4)
        staged = json.loads((self.staging / f"{self.item['sha256']}.json").read_text())
        self.assertEqual([p["page_number"] for p in staged["pages"]], list(range(1, 13)))

    def test_default_is_sequential(self):
        client = SlowClient()
        self.ocr.stage_document(self.root, self.staging, self.item, client, sleep=lambda s: None)
        self.assertEqual(client.peak, 1)

    def test_failed_page_keeps_finished_pages_for_resume(self):
        with self.assertRaises(Exception):
            self.ocr.stage_document(self.root, self.staging, self.item, SlowClient(fail_on=6),
                                    sleep=lambda s: None, page_workers=4)
        client = SlowClient()
        report = self.ocr.stage_document(self.root, self.staging, self.item, client,
                                         sleep=lambda s: None, page_workers=4)
        self.assertEqual(report["status"], "staged")
        self.assertLess(client.calls, 12)


if __name__ == "__main__":
    unittest.main()
