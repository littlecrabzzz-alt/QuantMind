"""OCR for text-less / encrypted announcement PDFs; temp fixtures and fake model only.

Contract (backend/shared/tushare_document_ocr.py):
- ocr_candidates(root, *, limit, after=None) -> list of {"sha256","path","document_ids","parse_status"}
  downloaded documents whose parse_status is no_text or encrypted, PDF present, not retired.
- stage_document(root, staging, item, client, *, sleep=time.sleep, max_pages=None) -> dict
  renders pages, calls client.transcribe(png_bytes)->str per page, keeps per-page progress in
  `staging` so a rerun never re-sends finished pages; writes staging/<sha>.json when complete.
  Returns {"status": "staged"|"empty", "pages": n}. QuotaExceeded(retry_after) -> sleep(retry_after)
  then retry the same page. Never writes documents.sqlite.
- ingest_staged(root, staging) -> {"ingested": n, ...}: saves extracted JSON
  (parse_status parsed, document_sha256, page_count, pages, parser "glm-ocr", parser_version model)
  and marks every linked document parsed / pdf_structure_valid so retirement can pick it up.
  "empty" results are never ingested as parsed.
"""

import hashlib
import io
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


def blank_pdf(pages):
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class FakeClient:
    model = "fake-ocr"

    def __init__(self, texts=None, fail_on=None, quota_once_on=None):
        self.calls = 0
        self.texts = texts
        self.fail_on = fail_on
        self.quota_once_on = quota_once_on

    def transcribe(self, png):
        from backend.shared.tushare_document_ocr import QuotaExceeded
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "client must receive PNG bytes"
        self.calls += 1
        if self.fail_on is not None and self.calls == self.fail_on:
            raise KeyboardInterrupt("simulated crash")
        if self.quota_once_on is not None and self.calls == self.quota_once_on:
            self.quota_once_on = None
            raise QuotaExceeded(retry_after=123)
        return self.texts(self.calls) if self.texts else f"第{self.calls}页 公告正文"


class DocumentOCR(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tushare-ocr-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.staging = self.root / "ocr-staging"
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        from backend.shared import tushare_document_ocr as ocr
        self.ocr = ocr
        self.n = 0

    def add(self, status, pages=2, download="downloaded"):
        self.n += 1
        pdf = docs._save(self.root, "attachments", ".pdf", blank_pdf(pages) + f"%{self.n}\n".encode(),
                         "application/pdf")
        db = docs._document_db(self.root)
        ident = hashlib.sha256(f"doc{self.n}".encode()).hexdigest()
        result = {"status": "downloaded", "mime": "application/pdf", "parse_status": status,
                  "document_sha256": pdf["sha256"], "files": [pdf]}
        db.execute("INSERT INTO documents(id,observation,url,expected_mime,download_status,parse_status,result)"
                   " VALUES(?,?,?,?,?,?,?)", (ident, f"obs{self.n}", f"https://example.com/{self.n}.pdf",
                                             "application/pdf", download, status, json.dumps(result)))
        db.commit()
        db.close()
        return ident, pdf

    def row(self, ident):
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            status, result = db.execute("SELECT parse_status,result FROM documents WHERE id=?", (ident,)).fetchone()
        return status, json.loads(result)

    def test_candidates_are_only_textless_or_encrypted_with_pdf_present(self):
        a, _ = self.add("no_text")
        b, _ = self.add("encrypted")
        self.add("parsed")
        self.add("parse_failed")
        _, gone = self.add("no_text")
        (self.root / gone["path"]).unlink()
        items = self.ocr.ocr_candidates(self.root, limit=100)
        self.assertEqual(sorted(i["document_ids"][0] for i in items), sorted([a, b]))
        self.assertTrue(all(i["path"].startswith("attachments/") for i in items))

    def test_stage_transcribes_every_page_without_touching_database(self):
        self.add("no_text", pages=3)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        before = (self.root / "documents.sqlite").read_bytes()
        client = FakeClient()
        report = self.ocr.stage_document(self.root, self.staging, item, client, sleep=lambda s: None)
        self.assertEqual(report, {"status": "staged", "pages": 3})
        self.assertEqual(client.calls, 3)
        self.assertEqual((self.root / "documents.sqlite").read_bytes(), before)
        staged = json.loads((self.staging / f"{item['sha256']}.json").read_text())
        self.assertEqual([p["page_number"] for p in staged["pages"]], [1, 2, 3])

    def test_resume_never_resends_finished_pages(self):
        self.add("no_text", pages=3)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        with self.assertRaises(KeyboardInterrupt):
            self.ocr.stage_document(self.root, self.staging, item, FakeClient(fail_on=3), sleep=lambda s: None)
        client = FakeClient()
        report = self.ocr.stage_document(self.root, self.staging, item, client, sleep=lambda s: None)
        self.assertEqual(report["status"], "staged")
        self.assertEqual(client.calls, 1)

    def test_quota_waits_and_retries_same_page(self):
        self.add("no_text", pages=2)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        slept = []
        client = FakeClient(quota_once_on=2)
        report = self.ocr.stage_document(self.root, self.staging, item, client, sleep=slept.append)
        self.assertEqual(slept, [123])
        self.assertEqual(report, {"status": "staged", "pages": 2})
        staged = json.loads((self.staging / f"{item['sha256']}.json").read_text())
        self.assertEqual(len(staged["pages"]), 2)
        self.assertTrue(all(p["text"].strip() for p in staged["pages"]))

    def test_max_pages_limits_calls(self):
        self.add("no_text", pages=5)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        client = FakeClient()
        report = self.ocr.stage_document(self.root, self.staging, item, client,
                                         sleep=lambda s: None, max_pages=2)
        self.assertEqual(client.calls, 2)
        self.assertEqual(report["pages"], 2)

    def test_ingest_marks_parsed_and_retirement_can_plan_it(self):
        ident, pdf = self.add("no_text", pages=2)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        self.ocr.stage_document(self.root, self.staging, item, FakeClient(), sleep=lambda s: None)
        report = self.ocr.ingest_staged(self.root, self.staging)
        self.assertEqual(report["ingested"], 1)
        status, result = self.row(ident)
        self.assertEqual(status, "parsed")
        self.assertEqual(result["parse_status"], "parsed")
        self.assertEqual(result["validation_status"], "pdf_structure_valid")
        extracted = [f for f in result["files"] if f["path"].startswith("extracted/")]
        self.assertEqual(len(extracted), 1)
        body = json.loads((self.root / extracted[0]["path"]).read_bytes())
        self.assertEqual(body["document_sha256"], pdf["sha256"])
        self.assertEqual(body["parser"], "glm-ocr")
        self.assertEqual(body["parser_version"], "fake-ocr")
        self.assertEqual(body["page_count"], 2)
        from backend.shared import tushare_attachment_retirement as retirement
        summary = retirement.build_plan(self.root, self.root / "plan.json")
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(self.ocr.ocr_candidates(self.root, limit=10), [])
        self.assertEqual(self.ocr.ingest_staged(self.root, self.staging)["ingested"], 0)

    def test_blank_transcription_is_never_ingested_as_parsed(self):
        ident, _ = self.add("no_text", pages=2)
        item, = self.ocr.ocr_candidates(self.root, limit=10)
        report = self.ocr.stage_document(self.root, self.staging, item,
                                         FakeClient(texts=lambda n: "  \n"), sleep=lambda s: None)
        self.assertEqual(report["status"], "empty")
        self.ocr.ingest_staged(self.root, self.staging)
        self.assertEqual(self.row(ident)[0], "no_text")


if __name__ == "__main__":
    unittest.main()
