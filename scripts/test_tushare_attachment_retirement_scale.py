"""Retirement must stay cheap on hot paths: 1.6M PDFs share a few thousand receipts.

Hot paths (publish, index, inventory, manifest_at, match_retired, archive scan) may
not re-hash extracted text per retired PDF, and may read each batch receipt at most
a bounded number of times per call. Integrity of extracted text is the archive
scanner's normal job (see test_extracted_loss_after_retirement_is_not_hidden).
"""

import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COUNT = 40


class RetirementScale(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tushare-retirement-scale-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.retirement = importlib.import_module("backend.shared.tushare_attachment_retirement")
        self.docs = importlib.import_module("backend.shared.tushare_documents")
        self.archive = importlib.import_module("backend.shared.tushare_archive")
        self.pipeline = importlib.import_module("backend.shared.tushare_pipeline")
        self.db = self.docs._document_db(self.root)
        self.addCleanup(self.db.close)
        self.paths = []
        for n in range(COUNT):
            label = f"doc{n}"
            pdf = self.docs._save(self.root, "attachments", ".pdf",
                                  f"%PDF-1.4\n{label}\n%%EOF\n".encode(), "application/pdf")
            extracted = self.docs._save(self.root, "extracted", ".json", self.docs._json({
                "parse_status": "parsed", "document_sha256": pdf["sha256"], "page_count": 1,
                "pages": [{"page_number": 1, "text": "正文" + label}],
                "parser": "fixture", "parser_version": "1"}), "application/json")
            record = {"title": label, "url": f"https://example.com/{label}.pdf"}
            self.docs.enqueue_documents(self.root, "observation-" + label, "anns_d", [record], ["url"])
            row = self.db.execute("SELECT id FROM documents WHERE url=?", (record["url"],)).fetchone()
            result = {"status": "downloaded", "mime": "application/pdf", "parse_status": "parsed",
                      "validation_status": "pdf_structure_valid",
                      "document_sha256": pdf["sha256"], "files": [pdf, extracted]}
            self.db.execute("UPDATE documents SET download_status='downloaded',parse_status='parsed',"
                            "result=? WHERE id=?", (json.dumps(result), row["id"]))
            self.db.commit()
            self.paths.append(pdf["path"])
        self.db.commit()
        self.publisher = self.pipeline.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.publisher.db.close)
        self.publisher.publish()
        plan = self.root / "plan.json"
        summary = self.retirement.build_plan(self.root, plan)
        report = self.retirement.apply_plan(self.root, plan, confirm_sha=summary["plan_sha256"])
        self.assertEqual(report["status"], "complete")
        self.receipts = len(report["receipts"])
        self.assertLessEqual(self.receipts, 2)

    def counting(self):
        calls = {"text": 0, "receipt_reads": 0}
        real_text, real_read = self.retirement._text, self.retirement._read

        def text(*args, **kwargs):
            calls["text"] += 1
            return real_text(*args, **kwargs)

        def read(root, item, *args, **kwargs):
            if str(item.get("path", "")).startswith("documents/"):
                calls["receipt_reads"] += 1
            return real_read(root, item, *args, **kwargs)

        return calls, patch.object(self.retirement, "_text", text), patch.object(self.retirement, "_read", read)

    def assertCheap(self, action, label):
        calls, text, read = self.counting()
        with text, read:
            action()
        self.assertEqual(calls["text"], 0, f"{label} re-hashed extracted text per PDF")
        self.assertLessEqual(calls["receipt_reads"], 2 * self.receipts,
                             f"{label} re-read receipts per PDF: {calls}")

    def test_match_retired_is_cheap(self):
        self.assertCheap(lambda: [self.retirement.match_retired(self.root, p) for p in self.paths[:1]],
                         "match_retired")

    def test_retired_files_listing_is_cheap(self):
        self.assertCheap(lambda: self.assertEqual(len(self.retirement.retired_files(self.root)), COUNT),
                         "retired_files")

    def test_index_and_inventory_are_cheap(self):
        self.assertCheap(lambda: self.docs.document_index(self.root), "document_index")
        self.assertCheap(lambda: self.docs.document_inventory(self.root), "document_inventory")

    def test_publish_and_manifest_read_are_cheap(self):
        holder = {}
        self.assertCheap(lambda: holder.setdefault("release", self.publisher.publish()), "publish")
        self.assertCheap(lambda: self.pipeline.manifest_at(self.root, holder["release"]), "manifest_at")

    def test_archive_scan_is_cheap(self):
        def scan():
            for _ in range(200):
                if self.archive.recover_archive(self.root, max_items=500, max_seconds=5)["status"] != "recovering":
                    return
            self.fail("scan did not finish")
        self.assertCheap(scan, "recover_archive")
        self.assertEqual(self.archive.archive_inventory(self.root)["gaps"], [])


if __name__ == "__main__":
    unittest.main()
