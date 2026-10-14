"""Held attachments (e.g. periodic reports kept for a later model double-check) are never retired."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402
from backend.shared import tushare_attachment_retirement as retirement  # noqa: E402


class Holds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tushare-holds-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.pdfs = [self.add(n) for n in range(3)]

    def add(self, n):
        pdf = docs._save(self.root, "attachments", ".pdf", f"%PDF-1.4\n{n}\n%%EOF\n".encode(), "application/pdf")
        extracted = docs._save(self.root, "extracted", ".json", docs._json({
            "parse_status": "parsed", "document_sha256": pdf["sha256"], "page_count": 1,
            "pages": [{"page_number": 1, "text": f"正文{n}"}], "parser": "fixture", "parser_version": "1"}),
            "application/json")
        db = docs._document_db(self.root)
        result = {"status": "downloaded", "mime": "application/pdf", "parse_status": "parsed",
                  "validation_status": "pdf_structure_valid", "document_sha256": pdf["sha256"],
                  "files": [pdf, extracted]}
        db.execute("INSERT INTO documents(id,observation,url,expected_mime,download_status,parse_status,result)"
                   " VALUES(?,?,?,?,?,?,?)", (hashlib.sha256(str(n).encode()).hexdigest(), f"o{n}",
                                             f"https://example.com/{n}.pdf", "application/pdf",
                                             "downloaded", "parsed", json.dumps(result)))
        db.commit()
        db.close()
        return pdf

    def test_held_pdf_is_excluded_from_plan_and_survives_apply(self):
        held = self.pdfs[0]
        report = retirement.hold_attachments(self.root, [held["sha256"]], reason="periodic_report")
        self.assertEqual(report["held"], 1)
        plan = self.root / "plan.json"
        summary = retirement.build_plan(self.root, plan)
        self.assertEqual(summary["candidate_count"], 2)
        items = json.loads(plan.read_bytes())["items"]
        self.assertNotIn(held["path"], [i["path"] for i in items])
        retirement.apply_plan(self.root, plan, confirm_sha=summary["plan_sha256"])
        self.assertTrue((self.root / held["path"]).exists())
        self.assertFalse((self.root / self.pdfs[1]["path"]).exists())

    def test_hold_is_idempotent_and_listable(self):
        retirement.hold_attachments(self.root, [self.pdfs[0]["sha256"]] * 2, reason="periodic_report")
        again = retirement.hold_attachments(self.root, [self.pdfs[0]["sha256"]], reason="periodic_report")
        self.assertEqual(again["held"], 0)
        self.assertEqual(retirement.held_attachments(self.root), {self.pdfs[0]["sha256"]: "periodic_report"})

    def test_release_hold_makes_pdf_eligible_again(self):
        retirement.hold_attachments(self.root, [self.pdfs[0]["sha256"]], reason="periodic_report")
        retirement.release_holds(self.root, [self.pdfs[0]["sha256"]])
        summary = retirement.build_plan(self.root, self.root / "plan.json")
        self.assertEqual(summary["candidate_count"], 3)

    def test_invalid_sha_rejected(self):
        with self.assertRaises(ValueError):
            retirement.hold_attachments(self.root, ["not-a-sha"], reason="x")


if __name__ == "__main__":
    unittest.main()
