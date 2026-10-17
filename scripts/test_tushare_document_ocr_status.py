"""Read-only staging status: disjoint classification, dedup, no side effects.

Contract (backend/shared/tushare_document_ocr.py status_staging):
- ingested / staged_awaiting_ingest count only documents that pass _validate
  AND carry ingestable text (parse_status parsed, non-blank pages) — the exact
  condition ingest_staged enforces. Valid-but-empty and invalid artifacts are
  reported separately (ingested_empty/invalid, staged_empty/invalid), never as
  finished.
- incomplete_checkpoints[] counts a page as done only when the canonical
  {n}.json exists and matches stage's own {page_number, text} contract;
  duplicate (01.json) / corrupt / mismatched pages are not counted and are
  listed in invalid_page_files.
- The same SHA present both in ingested/ and the staging root is counted once,
  under ingested (staged_overlap_ingested lists it).
- last_checkpoint_age_seconds is an observation time, never a process
  liveness claim.
- Strictly read-only: no directory creation, no checkpoint writes, no DB
  access, no model calls; file bytes are unchanged.
"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_document_ocr as ocr  # noqa: E402


def sha_of(n):
    import hashlib
    return hashlib.sha256(f"doc-{n}".encode()).hexdigest()


def _write_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class StatusStagingTest(unittest.TestCase):
    def setUp(self):
        self.staging = Path(tempfile.mkdtemp(prefix="ocr-status-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.staging, ignore_errors=True)

    def _complete_bytes(self, sha, *, text="x", parse_status="parsed", pages=1):
        body = {"document_sha256": sha, "page_count": pages,
                "pages": [{"page_number": n, "text": text}
                          for n in range(1, pages + 1)],
                "parse_status": parse_status,
                "parser": "glm-ocr", "parser_version": "test"}
        return ocr.docs._json(body)

    def _checkpoint_dir(self, sha, done, total):
        progress = self.staging / sha
        progress.mkdir(parents=True, exist_ok=True)
        (progress / "metadata.json").write_bytes(ocr.docs._json(
            {"document_sha256": sha, "page_count": total,
             "parser": "glm-ocr", "parser_version": "test"}))
        for n in range(1, done + 1):
            (progress / f"{n}.json").write_bytes(
                ocr.docs._json({"page_number": n, "text": "x"}))

    def _snapshot_bytes(self):
        return {str(p.relative_to(self.staging)): p.read_bytes()
                for p in self.staging.rglob("*") if p.is_file()}

    def test_same_sha_in_ingested_and_root_counts_once(self):
        overlap_sha = sha_of(1)
        ingested = self.staging / "ingested"
        ingested.mkdir()
        _write_bytes(ingested / f"{overlap_sha}.json",
                     self._complete_bytes(overlap_sha))
        _write_bytes(self.staging / f"{overlap_sha}.json",
                     self._complete_bytes(overlap_sha))
        self._checkpoint_dir(sha_of(2), done=1, total=3)  # genuine incomplete
        report = ocr.status_staging(self.staging, now=1_700_000_000.0)
        self.assertEqual(report["ingested"], 1)
        self.assertEqual(report["staged_awaiting_ingest"], 0)
        self.assertEqual(report["staged_overlap_ingested"], [overlap_sha])
        self.assertEqual(len(report["incomplete_checkpoints"]), 1)

    def test_empty_and_corrupt_complete_not_staged(self):
        empty_sha, blank_sha, corrupt_sha = sha_of(3), sha_of(4), sha_of(5)
        # structurally valid but parse_status no_text: stage really writes these
        _write_bytes(self.staging / f"{empty_sha}.json",
                     self._complete_bytes(empty_sha, parse_status="no_text"))
        # parsed flag but every page blank: ingest skips it too
        _write_bytes(self.staging / f"{blank_sha}.json",
                     self._complete_bytes(blank_sha, text="  \n"))
        # truncated JSON
        _write_bytes(self.staging / f"{corrupt_sha}.json", b'{"document_sha')
        report = ocr.status_staging(self.staging, now=1_700_000_000.0)
        self.assertEqual(report["staged_awaiting_ingest"], 0)
        self.assertEqual(report["staged_empty"], 2)
        self.assertEqual(report["staged_invalid"], 1)

    def test_duplicate_and_corrupt_pages_not_done(self):
        open_sha = sha_of(6)
        progress = self.staging / open_sha
        progress.mkdir()
        (progress / "metadata.json").write_bytes(ocr.docs._json(
            {"document_sha256": open_sha, "page_count": 4,
             "parser": "glm-ocr", "parser_version": "test"}))
        (progress / "1.json").write_bytes(
            ocr.docs._json({"page_number": 1, "text": "x"}))
        # non-canonical duplicate of page 1: never counted
        (progress / "01.json").write_bytes(
            ocr.docs._json({"page_number": 1, "text": "dup"}))
        # corrupt JSON
        (progress / "2.json").write_text("{not json")
        # page_number mismatch
        (progress / "3.json").write_bytes(
            ocr.docs._json({"page_number": 7, "text": "x"}))
        report = ocr.status_staging(self.staging, now=1_700_000_000.0)
        entry = report["incomplete_checkpoints"][0]
        self.assertEqual(entry["pages_done"], 1)
        self.assertEqual(entry["pages_total"], 4)
        self.assertEqual(entry["invalid_page_files"],
                         ["2.json:unreadable", "3.json:invalid_page_checkpoint"])

    def test_residue_dirs_of_completed_documents_not_inflight(self):
        ingested_sha, staged_sha, open_sha = sha_of(7), sha_of(8), sha_of(9)
        ingested = self.staging / "ingested"
        ingested.mkdir()
        _write_bytes(ingested / f"{ingested_sha}.json",
                     self._complete_bytes(ingested_sha))
        self._checkpoint_dir(ingested_sha, done=3, total=5)   # residue
        _write_bytes(self.staging / f"{staged_sha}.json",
                     self._complete_bytes(staged_sha))
        self._checkpoint_dir(staged_sha, done=2, total=4)     # residue
        self._checkpoint_dir(open_sha, done=1, total=7)       # in-flight
        report = ocr.status_staging(self.staging, now=1_700_000_000.0)
        self.assertEqual(report["ingested"], 1)
        self.assertEqual(report["staged_awaiting_ingest"], 1)
        self.assertEqual([e["sha256"] for e in report["incomplete_checkpoints"]],
                         [open_sha])
        entry = report["incomplete_checkpoints"][0]
        self.assertEqual((entry["pages_done"], entry["pages_total"]), (1, 7))

    def test_metadata_missing_pages_discovered_and_validated(self):
        open_sha = sha_of(10)
        progress = self.staging / open_sha
        progress.mkdir()
        (progress / "2.json").write_bytes(
            ocr.docs._json({"page_number": 2, "text": "x"}))
        (progress / "bad.json").write_text("{}")  # non-numeric name: ignored
        report = ocr.status_staging(self.staging, now=1_700_000_000.0)
        entry = report["incomplete_checkpoints"][0]
        self.assertEqual((entry["pages_done"], entry["pages_total"]), (1, None))

    def test_strictly_read_only_bytes_unchanged(self):
        ingested_sha = sha_of(11)
        ingested = self.staging / "ingested"
        ingested.mkdir()
        _write_bytes(ingested / f"{ingested_sha}.json",
                     self._complete_bytes(ingested_sha, pages=2))
        self._checkpoint_dir(sha_of(12), done=1, total=2)
        before = self._snapshot_bytes()
        ocr.status_staging(self.staging, now=1_700_000_000.0)
        ocr.status_staging(self.staging / "does-not-exist")
        self.assertEqual(self._snapshot_bytes(), before)
        self.assertFalse((self.staging / "does-not-exist").exists())

    def test_recent_first_ordering(self):
        import os
        older, newer = sha_of(13), sha_of(14)
        self._checkpoint_dir(older, done=1, total=2)
        self._checkpoint_dir(newer, done=1, total=2)
        now = 1_700_000_000.0
        os.utime(self.staging / older / "1.json", (now - 500, now - 500))
        os.utime(self.staging / newer / "1.json", (now - 5, now - 5))
        report = ocr.status_staging(self.staging, now=now)
        self.assertEqual([e["sha256"] for e in report["incomplete_checkpoints"]],
                         [newer, older])
        self.assertEqual(report["incomplete_checkpoints"][0]
                         ["last_checkpoint_age_seconds"], 5.0)


    def test_valid_sha_sets_own_completion_despite_invalid_overlapping_artifacts(self):
        empty_root, invalid_root, invalid_ingested = (sha_of(n) for n in (20, 21, 22))
        ingested = self.staging / "ingested"
        for sha in (empty_root, invalid_root):
            _write_bytes(ingested / f"{sha}.json", self._complete_bytes(sha))
        _write_bytes(self.staging / f"{empty_root}.json",
                     self._complete_bytes(empty_root, text=" "))
        _write_bytes(self.staging / f"{invalid_root}.json", b"{broken")
        _write_bytes(ingested / f"{invalid_ingested}.json", b"{broken")
        _write_bytes(self.staging / f"{invalid_ingested}.json",
                     self._complete_bytes(invalid_ingested))
        report = ocr.status_staging(self.staging)
        self.assertEqual(report["ingested"], 2)
        self.assertEqual(report["staged_awaiting_ingest"], 1)
        self.assertEqual(report["ingested_invalid"], 1)
        self.assertEqual(report["staged_empty"], 1)
        self.assertEqual(report["staged_invalid"], 1)
        self.assertEqual(report["staged_overlap_ingested"], [])

    def test_metadata_missing_aliases_do_not_repeat_canonical_page_counts(self):
        progress = self.staging / sha_of(23)
        progress.mkdir()
        for name in ("1.json", "01.json"):
            _write_bytes(progress / name,
                         ocr.docs._json({"page_number": 1, "text": "done"}))
        for name in ("2.json", "02.json"):
            _write_bytes(progress / name, b"{broken")
        _write_bytes(progress / "03.json",
                     ocr.docs._json({"page_number": 3, "text": "alias only"}))
        entry, = ocr.status_staging(self.staging)["incomplete_checkpoints"]
        self.assertEqual((entry["pages_done"], entry["pages_total"]), (1, None))
        self.assertEqual(entry["invalid_page_files"], ["2.json:unreadable"])

    def test_non_object_complete_json_is_invalid_and_repeated_status_survives(self):
        payloads = [[], [1], None, "text", 7, True]
        for n, payload in enumerate(payloads, 30):
            sha = sha_of(n)
            for directory in (self.staging, self.staging / "ingested"):
                _write_bytes(directory / f"{sha}.json", ocr.docs._json(payload))
        before = self._snapshot_bytes()
        for _ in range(2):
            report = ocr.status_staging(self.staging)
            self.assertEqual(report["ingested"], 0)
            self.assertEqual(report["staged_awaiting_ingest"], 0)
            self.assertEqual(report["ingested_invalid"], len(payloads))
            self.assertEqual(report["staged_invalid"], len(payloads))
        self.assertEqual(self._snapshot_bytes(), before)


if __name__ == "__main__":
    unittest.main()
