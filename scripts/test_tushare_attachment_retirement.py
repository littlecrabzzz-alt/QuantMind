#!/usr/bin/env python3
"""Red acceptance contract; see docs/storage/pdf-retirement-design.md.

Only temporary fixtures. No worker, provider, production archive or migration.
The proposed module is imported in setUp so pytest can collect every test.
Until implemented, execution fails with ModuleNotFoundError (never skip/xfail).
"""

import hashlib
import importlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class AttachmentRetirement(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tushare-retirement-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        # Intentional red gate; no fallback fake implementation.
        self.retirement = importlib.import_module(
            "backend.shared.tushare_attachment_retirement"
        )
        self.docs = importlib.import_module("backend.shared.tushare_documents")
        self.archive = importlib.import_module("backend.shared.tushare_archive")
        self.db = self.docs._document_db(self.root)
        self.addCleanup(self.db.close)

    def fixture(self, label="one", *, status="parsed", extracted_status="parsed",
                document_sha=None, text="公告正文", validation="pdf_structure_valid"):
        # Parsing is already completed in this fixture; no PDF parser is needed.
        pdf = self.docs._save(
            self.root, "attachments", ".pdf",
            ("%PDF-1.4\nfixture " + label + "\n%%EOF\n").encode(),
            "application/pdf",
        )
        extracted = self.docs._save(
            self.root, "extracted", ".json", self.docs._json({
                "parse_status": extracted_status,
                "document_sha256": document_sha or pdf["sha256"],
                "page_count": 1,
                "pages": [{"page_number": 1, "text": text}],
                "parser": "fixture", "parser_version": "1",
            }), "application/json",
        )
        record = {"title": label, "url": f"https://example.com/{label}.pdf"}
        self.docs.enqueue_documents(self.root, "observation-" + label,
                                    "anns_d", [record], ["url"])
        row = self.db.execute(
            "SELECT id FROM documents WHERE url=?", (record["url"],)
        ).fetchone()
        result = {
            "status": "downloaded", "mime": "application/pdf",
            "parse_status": status, "validation_status": validation,
            "document_sha256": pdf["sha256"], "files": [pdf, extracted],
        }
        self.db.execute(
            "UPDATE documents SET download_status='downloaded',parse_status=?,"
            "result=? WHERE id=?", (status, json.dumps(result), row["id"]),
        )
        self.db.commit()
        return {"id": row["id"], "pdf": pdf, "extracted": extracted,
                "record": record, "result": result}

    def plan(self, name="plan.json", **options):
        path = self.root / name
        summary = self.retirement.build_plan(self.root, path, **options)
        self.assertEqual(summary["plan_sha256"], digest(path.read_bytes()))
        return path, summary, json.loads(path.read_bytes())

    def apply(self, path, summary, **options):
        return self.retirement.apply_plan(
            self.root, path, confirm_sha=summary["plan_sha256"], **options
        )

    def retire(self, fixture):
        path, summary, _ = self.plan()
        report = self.apply(path, summary)
        self.assertFalse((self.root / fixture["pdf"]["path"]).exists())
        return path, summary, report

    def manifest(self, files):
        raw = json.dumps({"files": {
            item["path"]: {k: item[k] for k in ("sha256", "bytes")}
            for item in files
        }, "datasets": []}, sort_keys=True).encode()
        release = "data-" + digest(raw)
        path = self.root / "releases" / release / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return release, path, raw

    def scan(self, *, rescan=False):
        for index in range(100):
            progress = self.archive.recover_archive(
                self.root, max_items=100, max_seconds=2,
                rescan=rescan and index == 0,
            )
            if progress["status"] != "recovering":
                return self.archive.archive_inventory(self.root)
        self.fail("Temporary archive scan did not terminate")

    def test_plan_is_non_destructive_and_binds_both_hashes(self):
        fixture = self.fixture()
        before = (self.root / fixture["extracted"]["path"]).read_bytes()
        _, summary, plan = self.plan()
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["candidate_bytes"], fixture["pdf"]["bytes"])
        item, = plan["items"]
        self.assertEqual(item["path"], fixture["pdf"]["path"])
        self.assertEqual(item["sha256"], fixture["pdf"]["sha256"])
        self.assertEqual(item["document_ids"], [fixture["id"]])
        self.assertIn(fixture["extracted"], item["extracted"])
        self.assertTrue((self.root / item["path"]).is_file())
        self.assertEqual((self.root / fixture["extracted"]["path"]).read_bytes(), before)

    def test_unparsed_failed_empty_encrypted_and_unvalidated_are_excluded(self):
        for status in ("not_attempted", "parse_pending", "parse_failed",
                       "parse_timeout", "parse_unavailable", "no_text", "encrypted"):
            self.fixture(status, status=status)
        self.fixture("invalid-structure", validation="pdf_envelope_only")
        self.fixture("empty-text", text=" \n")
        self.fixture("failed-extraction", extracted_status="parse_failed")
        _, summary, plan = self.plan()
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(plan["items"], [])

    def test_missing_mismatched_and_corrupt_extractions_are_excluded(self):
        missing = self.fixture("missing")
        (self.root / missing["extracted"]["path"]).unlink()
        self.fixture("wrong-link", document_sha="0" * 64)
        corrupt = self.fixture("corrupt")
        (self.root / corrupt["extracted"]["path"]).write_bytes(b"{}")
        _, summary, plan = self.plan()
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(plan["items"], [])

    def test_corrupt_pdf_and_unregistered_orphan_are_excluded(self):
        fixture = self.fixture()
        (self.root / fixture["pdf"]["path"]).write_bytes(b"changed")
        self.docs._save(self.root, "attachments", ".pdf", b"%PDF-orphan",
                        "application/pdf")
        _, summary, _ = self.plan()
        self.assertEqual(summary["candidate_count"], 0)

    def test_shared_pdf_is_deduplicated_and_failed_alias_blocks_retirement(self):
        fixture = self.fixture()
        alias = digest(b"second-document")
        self.db.execute(
            "INSERT INTO documents(id,observation,url,download_status,parse_status,"
            "result) VALUES(?,?,?,'downloaded','parse_failed',?)",
            (alias, "alias-observation", "https://example.com/alias.pdf",
             json.dumps({**fixture["result"], "parse_status": "parse_failed"})),
        )
        self.db.commit()
        _, summary, _ = self.plan("blocked.json")
        self.assertEqual(summary["candidate_count"], 0)
        self.db.execute("UPDATE documents SET parse_status='parsed',result=? WHERE id=?",
                        (json.dumps(fixture["result"]), alias))
        self.db.commit()
        _, summary, plan = self.plan("eligible.json")
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(set(plan["items"][0]["document_ids"]), {fixture["id"], alias})

    def test_confirmation_sha_mismatch_refuses_every_deletion(self):
        fixture = self.fixture()
        path, _, _ = self.plan()
        with self.assertRaisesRegex(ValueError, "confirmation_sha_mismatch"):
            self.retirement.apply_plan(self.root, path, confirm_sha="0" * 64)
        self.assertTrue((self.root / fixture["pdf"]["path"]).is_file())

    def test_modified_plan_requires_new_confirmation(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "confirmation_sha_mismatch"):
            self.apply(path, summary)
        self.assertTrue((self.root / fixture["pdf"]["path"]).is_file())

    def test_changed_extraction_after_planning_refuses_deletion(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        (self.root / fixture["extracted"]["path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "extracted_checksum_mismatch"):
            self.apply(path, summary)
        self.assertTrue((self.root / fixture["pdf"]["path"]).is_file())

    def test_changed_pdf_after_planning_refuses_deletion(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        target = self.root / fixture["pdf"]["path"]
        target.write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "pdf_checksum_mismatch"):
            self.apply(path, summary)
        self.assertEqual(target.read_bytes(), b"replacement")

    def test_pdf_symlink_after_planning_never_deletes_target(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        target = self.root / fixture["pdf"]["path"]
        outside = self.root / "keep.pdf"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "unsafe_path"):
            self.apply(path, summary)
        self.assertTrue(target.is_symlink())
        self.assertTrue(outside.is_file())

    def test_missing_pdf_without_prepared_intent_is_not_retirement(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        (self.root / fixture["pdf"]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "pdf_missing_without_intent"):
            self.apply(path, summary)

    def test_bounded_execution_resumes_without_duplicate_receipts(self):
        first, second = self.fixture("first"), self.fixture("second")
        path, summary, _ = self.plan()
        partial = self.apply(path, summary, max_items=1)
        self.assertEqual((partial["status"], partial["remaining"]), ("in_progress", 1))
        self.assertEqual(sum((self.root / f["pdf"]["path"]).exists()
                             for f in (first, second)), 1)
        complete = self.apply(path, summary)
        self.assertEqual((complete["status"], complete["remaining"]), ("complete", 0))
        repeated = self.apply(path, summary)
        self.assertEqual(repeated["deleted_now"], 0)
        self.assertEqual(repeated["receipts"], complete["receipts"])
        rows = self.db.execute("SELECT path,state FROM attachment_retirements").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["state"] == "retired" for row in rows))

    def test_crash_after_unlink_before_commit_can_resume(self):
        fixture = self.fixture()
        path, summary, _ = self.plan()
        original = self.retirement._unlink_verified_pdf

        def crash_after_unlink(root, item):
            original(root, item)
            raise KeyboardInterrupt("simulated process death")

        with patch.object(self.retirement, "_unlink_verified_pdf", crash_after_unlink):
            with self.assertRaises(KeyboardInterrupt):
                self.apply(path, summary)
        self.assertFalse((self.root / fixture["pdf"]["path"]).exists())
        row = self.db.execute(
            "SELECT state,plan_sha256 FROM attachment_retirements WHERE path=?",
            (fixture["pdf"]["path"],),
        ).fetchone()
        self.assertEqual(tuple(row), ("prepared", summary["plan_sha256"]))
        report = self.apply(path, summary)
        self.assertEqual(report["status"], "complete")
        receipt, = report["receipts"]
        raw = (self.root / receipt["path"]).read_bytes()
        self.assertEqual(digest(raw), receipt["sha256"])
        self.assertEqual(len(raw), receipt["bytes"])
        body = json.loads(raw)
        self.assertEqual(body["plan_sha256"], summary["plan_sha256"])
        self.assertEqual(body["items"][0]["path"], fixture["pdf"]["path"])
        self.assertEqual(body["items"][0]["status"], "retired")

    def test_retired_scan_index_and_old_manifest_remain_consistent(self):
        fixture = self.fixture()
        _, old_path, old_raw = self.manifest([fixture["pdf"], fixture["extracted"]])
        self.docs.document_index(self.root)  # Populate the append-only old cache.
        self.assertFalse(self.scan()["gaps"])
        self.retire(fixture)
        inventory = self.scan(rescan=True)
        self.assertEqual(inventory["gaps"], [])
        self.assertEqual(inventory["recovery"]["status"], "complete")
        self.assertNotIn(fixture["pdf"]["path"], inventory["files"])
        self.assertEqual(inventory["retired_files"][fixture["pdf"]["path"]]["status"],
                         "retired")
        self.assertEqual(self.db.execute(
            "SELECT download_status,parse_status FROM documents WHERE id=?",
            (fixture["id"],),
        ).fetchone()[:], ("downloaded", "parsed"))
        for indexed in (self.docs.document_inventory(self.root),
                        self.docs.document_index(self.root)):
            self.assertNotIn(fixture["pdf"]["path"], {f["path"] for f in indexed["files"]})
            self.assertIn(fixture["extracted"]["path"], {f["path"] for f in indexed["files"]})
            self.assertIn(fixture["pdf"]["path"], indexed["retired_files"])
        self.assertEqual(old_path.read_bytes(), old_raw)

    def test_unretired_missing_pdf_still_produces_gap(self):
        fixture = self.fixture()
        self.manifest([fixture["pdf"], fixture["extracted"]])
        (self.root / fixture["pdf"]["path"]).unlink()
        inventory = self.scan()
        self.assertTrue(any(g["path"] == fixture["pdf"]["path"]
                            for g in inventory["gaps"]))
        self.assertNotIn(fixture["pdf"]["path"], inventory.get("retired_files", {}))

    def test_extracted_loss_after_retirement_is_not_hidden(self):
        fixture = self.fixture()
        self.manifest([fixture["pdf"], fixture["extracted"]])
        self.retire(fixture)
        (self.root / fixture["extracted"]["path"]).unlink()
        inventory = self.scan(rescan=True)
        self.assertTrue(any(g["path"] == fixture["extracted"]["path"]
                            for g in inventory["gaps"]))
        self.assertEqual(inventory["recovery"]["status"], "complete_with_gaps")

    def test_retired_documents_are_reused_and_never_claimed_or_reparsed(self):
        fixture = self.fixture()
        self.retire(fixture)
        registered = self.docs.enqueue_documents(
            self.root, "later-observation", "anns_d", [fixture["record"]], ["url"]
        )
        self.assertEqual(registered["enqueued"], 0)
        self.assertEqual(registered["reused"], 1)
        self.docs._claims_setup(self.db)
        retries = self.docs._schedule_terminal_retries(
            self.db, now=time.time(), interval_seconds=1,
            max_documents=10, max_bytes=1024 * 1024,
        )
        self.assertEqual(retries["scheduled"], [])
        self.assertEqual(self.docs._eligible_documents(self.db, None, time.time(), 10), [])
        with patch.object(self.docs, "_parse_pdf",
                          side_effect=AssertionError("Retired PDF must not be parsed")):
            result = self.docs._parse_saved(self.root, fixture["result"], 1)
        self.assertEqual(result["parse_status"], "parsed")
        self.assertEqual(result["attachment_status"], "retired")

    def test_new_publication_omits_pdf_and_retains_receipts_and_text(self):
        fixture = self.fixture()
        pipeline = importlib.import_module("backend.shared.tushare_pipeline")
        publisher = pipeline.Pipeline(self.root, {"entries": []})
        self.addCleanup(publisher.db.close)
        old_release = publisher.publish()
        old_path = self.root / "releases" / old_release / "manifest.json"
        old_raw = old_path.read_bytes()
        _, _, report = self.retire(fixture)
        new_release = publisher.publish()
        self.assertNotEqual(new_release, old_release)
        manifest = pipeline.verify_data(self.root, new_release)
        self.assertNotIn(fixture["pdf"]["path"], manifest["files"])
        self.assertIn(fixture["pdf"]["path"], manifest["retired_files"])
        self.assertIn(fixture["extracted"]["path"], manifest["files"])
        for receipt in report["receipts"]:
            self.assertIn(receipt["path"], manifest["files"])
        self.assertEqual(old_path.read_bytes(), old_raw)
        pipeline.verify_data(self.root, old_release)  # Receipt-aware old closure.

    def test_api_returns_410_for_retired_pdf_and_still_serves_text(self):
        fixture = self.fixture()
        release, _, _ = self.manifest([fixture["pdf"], fixture["extracted"]])
        self.retire(fixture)
        store = importlib.import_module("backend.shared.tushare_store")
        # Prevent import-time deployment-root lookup as well as runtime reads.
        with patch.object(store, "deployed_read_root", return_value=self.root):
            api = importlib.import_module("backend.services.engine.routers.tushare_data")
        from fastapi import HTTPException

        with patch.object(api, "ROOT", self.root):
            with self.assertRaises(HTTPException) as caught:
                api.document_text(release, fixture["pdf"]["path"], 1, 20, 0, 20000)
            self.assertEqual(caught.exception.status_code, 410)
            self.assertEqual(caught.exception.detail["code"], "attachment_retired")
            self.assertEqual(caught.exception.detail["path"], fixture["pdf"]["path"])
            response = api.document_text(
                release, fixture["extracted"]["path"], 1, 20, 0, 20000
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.body)["pages"][0]["text"], "公告正文")
            unrelated, _, _ = self.manifest([fixture["extracted"]])
            with self.assertRaises(HTTPException) as unknown:
                api.document_text(unrelated, fixture["pdf"]["path"], 1, 20, 0, 20000)
            self.assertEqual(unknown.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
