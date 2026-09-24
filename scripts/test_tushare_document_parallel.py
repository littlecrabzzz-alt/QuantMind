"""Temp-only bounded transfer overlap, durable claims and child self-deadlines."""

import fcntl
import hashlib
import json
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs  # noqa: E402


class ParallelDocuments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tushare-parallel-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(patch.stopall)
        self.no_network = patch.object(
            socket.socket, "connect", side_effect=AssertionError("No network")
        ).start()
        self.no_dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("No DNS")
        ).start()
        self.original = docs._save(
            self.root, "attachments", ".pdf", b"%PDF-fixture\n%%EOF", "application/pdf"
        )
        self.stamp = "2026-09-08T10:00:00+00:00"

    def test_large_transfer_budget_and_claim_match_in_all_modes(self):
        for workers, overlap in [(1, False), (2, False), (2, True)]:
            with self.subTest(workers=workers, overlap=overlap):
                self.seed(1)
                def fetch(url, root, timeout, **kwargs):
                    self.assertGreater(timeout, 80)
                    self.assertLessEqual(timeout, 90)
                    lease = self.query("SELECT lease_until FROM document_claims")[0][0]
                    self.assertGreater(lease, time.time() + timeout)
                    return self.download()
                with patch.object(docs, "_download_job", side_effect=fetch) as call:
                    report = docs.run_documents(
                        self.root, max_documents=1, max_seconds=90,
                        download_workers=workers, overlap_parse_download=overlap,
                        max_bytes=docs.MAX_DOCUMENT_MAX_BYTES,
                    )
                self.assertEqual(call.call_count, 1)
                self.assertEqual(report["phase_counts"]["download"], 1)
                with sqlite3.connect(self.root / "documents.sqlite") as db:
                    db.execute("DELETE FROM documents")

    def tearDown(self):
        self.no_network.assert_not_called()
        self.no_dns.assert_not_called()

    def seed(self, count):
        db = docs._document_db(self.root)
        for i in range(count):
            ident = hashlib.sha256(str(i).encode()).hexdigest()
            db.execute(
                "INSERT INTO documents(id,observation,url,expected_mime) VALUES(?,?,?,?)",
                (
                    ident,
                    f"observation-{i}",
                    f"https://example.com/{i}",
                    "application/pdf",
                ),
            )
        db.commit()
        db.close()

    def download(self, parse="parse_pending"):
        return {
            "status": "downloaded",
            "mime": "application/pdf",
            "parse_status": parse,
            "fetched_at": self.stamp,
            "files": [self.original],
        }

    def query(self, sql):
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            return db.execute(sql).fetchall()

    def release_later(self, db, delay=0.03):
        def release():
            time.sleep(delay)
            db.rollback()

        thread = threading.Thread(target=release)
        thread.start()
        return thread

    def test_two_transfers_overlap_but_parsing_waits_for_durable_raw(self):
        self.seed(2)
        active, peak = 0, 0
        lock = threading.Lock()
        barrier = threading.Barrier(2)
        called = []

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active, peak
            self.assertTrue(download_only)
            self.assertLessEqual(timeout, 20)
            self.assertEqual(len(self.query("SELECT * FROM document_claims")), 2)
            with lock:
                active += 1
                peak = max(peak, active)
                called.append(url)
            barrier.wait(timeout=2)
            time.sleep(0.02)
            with lock:
                active -= 1
            return self.download()

        def parse(root, previous, timeout):
            self.assertEqual(active, 0)
            self.assertEqual(
                self.query(
                    "SELECT count(*) FROM documents WHERE download_status='downloaded'"
                )[0][0],
                2,
            )
            self.assertEqual(previous["fetched_at"], self.stamp)
            self.assertTrue((self.root / previous["files"][0]["path"]).is_file())
            return {**previous, "parse_status": "parsed"}

        with (
            patch.object(docs, "_download_job", side_effect=fetch),
            patch.object(docs, "_parse_saved", side_effect=parse),
        ):
            report = docs.run_documents(
                self.root, max_documents=4, max_seconds=2, download_workers=2
            )
        self.assertEqual(peak, 2)
        self.assertEqual(len(set(called)), 2)
        self.assertEqual(report["phase_counts"], {"download": 2, "parse": 2})
        timing = report["timing"]
        self.assertEqual(
            (
                timing["setup_db_calls"],
                timing["finish_db_calls"],
                timing["download_jobs"],
                timing["parse_jobs"],
            ),
            (1, 4, 2, 2),
        )
        self.assertGreaterEqual(timing["download_job_seconds"], 0.03)
        for phase in ("setup", "claim", "finish"):
            self.assertGreaterEqual(timing[f"{phase}_db_wait_seconds"], 0)
            self.assertGreaterEqual(
                timing[f"{phase}_db_total_seconds"],
                timing[f"{phase}_db_wait_seconds"],
            )
        self.assertEqual(
            self.query("SELECT download_tries,parse_tries FROM documents"),
            [(1, 1), (1, 1)],
        )
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 4)

    def test_enabled_parser_overlaps_transfers_with_single_parse_and_main_db_writes(self):
        self.seed(3)
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            first = db.execute("SELECT id FROM documents ORDER BY id LIMIT 1").fetchone()[0]
            db.execute(
                "UPDATE documents SET download_status='downloaded',"
                "parse_status='parse_pending',result=? WHERE id=?",
                (json.dumps(self.download()), first),
            )
            db.commit()
        active_downloads = 0
        active_parses = 0
        peak_downloads = 0
        peak_parses = 0
        overlapped = threading.Event()
        barrier = threading.Barrier(3)
        lock = threading.Lock()

        def observe():
            if active_downloads and active_parses:
                overlapped.set()

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active_downloads, peak_downloads
            self.assertTrue(download_only)
            with lock:
                active_downloads += 1
                peak_downloads = max(peak_downloads, active_downloads)
                observe()
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_downloads -= 1
            return self.download()

        def parse(root, previous, timeout):
            nonlocal active_parses, peak_parses
            self.assertEqual(previous["fetched_at"], self.stamp)
            with lock:
                active_parses += 1
                peak_parses = max(peak_parses, active_parses)
                observe()
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_parses -= 1
            return {**previous, "parse_status": "parsed"}

        with (
            patch.object(docs, "_download_job", side_effect=fetch),
            patch.object(docs, "_parse_saved", side_effect=parse),
        ):
            report = docs.run_documents(
                self.root,
                max_documents=3,
                max_seconds=2,
                download_workers=2,
                overlap_parse_download=True,
            )
        self.assertTrue(overlapped.is_set())
        self.assertEqual((peak_downloads, peak_parses), (2, 1))
        self.assertEqual(report["phase_counts"], {"download": 2, "parse": 1})
        self.assertTrue(report["overlap_parse_download"])
        self.assertGreater(report["timing"]["parse_download_overlap_seconds"], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 3)

    def test_two_parsers_overlap_bounded_transfers_without_db_writes_in_threads(self):
        self.seed(4)
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM documents ORDER BY id LIMIT 2"
                ).fetchall()
            ]
            db.executemany(
                "UPDATE documents SET download_status='downloaded',"
                "parse_status='parse_pending',result=? WHERE id=?",
                [(json.dumps(self.download()), ident) for ident in ids],
            )
            db.commit()
        active_downloads = 0
        active_parses = 0
        peak_downloads = 0
        peak_parses = 0
        barrier = threading.Barrier(4)
        lock = threading.Lock()

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active_downloads, peak_downloads
            self.assertTrue(download_only)
            with lock:
                active_downloads += 1
                peak_downloads = max(peak_downloads, active_downloads)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_downloads -= 1
            return self.download()

        def parse(root, previous, timeout):
            nonlocal active_parses, peak_parses
            with lock:
                active_parses += 1
                peak_parses = max(peak_parses, active_parses)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_parses -= 1
            return {**previous, "parse_status": "parsed"}

        with (
            patch.object(docs, "_download_job", side_effect=fetch),
            patch.object(docs, "_parse_saved", side_effect=parse),
        ):
            report = docs.run_documents(
                self.root,
                max_documents=4,
                max_seconds=2,
                download_workers=2,
                overlap_parse_download=True,
                parse_workers=2,
            )
        self.assertEqual((peak_downloads, peak_parses), (2, 2))
        self.assertEqual(report["phase_counts"], {"download": 2, "parse": 2})
        self.assertEqual(report["parse_workers"], 2)
        self.assertEqual(report["processed"], report["timing"]["finish_db_calls"])
        self.assertGreater(report["timing"]["parse_active_seconds"], 0)
        self.assertGreaterEqual(
            report["timing"]["parse_slot_capacity_seconds"],
            report["timing"]["parse_job_seconds"],
        )
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 4)

    def test_three_parsers_and_transfers_remain_bounded(self):
        self.seed(6)
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM documents ORDER BY id LIMIT 3"
                ).fetchall()
            ]
            db.executemany(
                "UPDATE documents SET download_status='downloaded',"
                "parse_status='parse_pending',result=? WHERE id=?",
                [(json.dumps(self.download()), ident) for ident in ids],
            )
            db.commit()
        active_downloads = 0
        active_parses = 0
        peak_downloads = 0
        peak_parses = 0
        barrier = threading.Barrier(6)
        lock = threading.Lock()

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active_downloads, peak_downloads
            self.assertTrue(download_only)
            with lock:
                active_downloads += 1
                peak_downloads = max(peak_downloads, active_downloads)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_downloads -= 1
            return self.download()

        def parse(root, previous, timeout):
            nonlocal active_parses, peak_parses
            with lock:
                active_parses += 1
                peak_parses = max(peak_parses, active_parses)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_parses -= 1
            return {**previous, "parse_status": "parsed"}

        with (
            patch.object(docs, "_download_job", side_effect=fetch),
            patch.object(docs, "_parse_saved", side_effect=parse),
        ):
            report = docs.run_documents(
                self.root,
                max_documents=6,
                max_seconds=2,
                download_workers=3,
                overlap_parse_download=True,
                parse_workers=3,
            )
        self.assertEqual((peak_downloads, peak_parses), (3, 3))
        self.assertEqual(report["phase_counts"], {"download": 3, "parse": 3})
        self.assertEqual(report["parse_workers"], 3)
        self.assertEqual(report["processed"], report["timing"]["finish_db_calls"])
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 6)

    def test_four_parsers_and_transfers_remain_bounded(self):
        self.seed(8)
        with sqlite3.connect(self.root / "documents.sqlite") as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM documents ORDER BY id LIMIT 4"
                ).fetchall()
            ]
            db.executemany(
                "UPDATE documents SET download_status='downloaded',"
                "parse_status='parse_pending',result=? WHERE id=?",
                [(json.dumps(self.download()), ident) for ident in ids],
            )
            db.commit()
        active_downloads = 0
        active_parses = 0
        peak_downloads = 0
        peak_parses = 0
        barrier = threading.Barrier(8)
        lock = threading.Lock()

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active_downloads, peak_downloads
            self.assertTrue(download_only)
            with lock:
                active_downloads += 1
                peak_downloads = max(peak_downloads, active_downloads)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_downloads -= 1
            return self.download()

        def parse(root, previous, timeout):
            nonlocal active_parses, peak_parses
            with lock:
                active_parses += 1
                peak_parses = max(peak_parses, active_parses)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active_parses -= 1
            return {**previous, "parse_status": "parsed"}

        with (
            patch.object(docs, "_download_job", side_effect=fetch),
            patch.object(docs, "_parse_saved", side_effect=parse),
        ):
            report = docs.run_documents(
                self.root,
                max_documents=8,
                max_seconds=2,
                download_workers=4,
                overlap_parse_download=True,
                parse_workers=4,
            )
        self.assertEqual((peak_downloads, peak_parses), (4, 4))
        self.assertEqual(report["phase_counts"], {"download": 4, "parse": 4})
        self.assertEqual(report["parse_workers"], 4)
        self.assertEqual(report["processed"], report["timing"]["finish_db_calls"])
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 8)

    def test_four_transfers_overlap_with_the_same_durable_fences(self):
        self.seed(4)
        active, peak = 0, 0
        lock = threading.Lock()
        barrier = threading.Barrier(4)

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active, peak
            self.assertTrue(download_only)
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=2)
            time.sleep(0.02)
            with lock:
                active -= 1
            return self.download()

        with patch.object(docs, "_download_job", side_effect=fetch):
            report = docs.run_documents(
                self.root, max_documents=4, max_seconds=2, download_workers=4
            )
        self.assertEqual(peak, 4)
        self.assertEqual(report["phase_counts"], {"download": 4, "parse": 0})
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 4)

    def test_sixteen_transfers_respect_the_expanded_bounded_limit(self):
        self.seed(16)
        active, peak = 0, 0
        lock = threading.Lock()
        barrier = threading.Barrier(16)

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal active, peak
            self.assertTrue(download_only)
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=2)
            time.sleep(0.02)
            with lock:
                active -= 1
            return self.download()

        with patch.object(docs, "_download_job", side_effect=fetch):
            report = docs.run_documents(
                self.root, max_documents=16, max_seconds=2, download_workers=16
            )
        self.assertEqual(peak, 16)
        self.assertEqual(report["phase_counts"], {"download": 16, "parse": 0})
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 16)

    def test_fast_result_commits_while_peer_waits_then_peer_retries(self):
        self.seed(2)
        barrier = threading.Barrier(2)

        def fetch(url, root, timeout, *, download_only=False):
            barrier.wait(timeout=2)
            if url.endswith("/0"):
                return self.download()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if self.query("SELECT count(*) FROM document_attempts")[0][0] == 1:
                    break
                time.sleep(0.005)
            else:
                raise AssertionError("fast result waited for slow peer")
            return {"status": "download_timeout", "files": []}

        with patch.object(docs, "_download_job", side_effect=fetch):
            result = docs.run_documents(self.root, 2, 2, download_workers=2)
        self.assertEqual(result["phase_counts"], {"download": 2, "parse": 0})
        retry_result = self.query(
            "SELECT result FROM documents WHERE download_status='retry'"
        )[0][0]
        self.assertEqual(json.loads(retry_result)["status"], "download_timeout")
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM documents WHERE download_status='downloaded'"
            )[0][0],
            1,
        )
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM documents WHERE download_status='retry' AND retry_after>strftime('%s','now')"
            )[0][0],
            1,
        )

    def test_fast_slot_refills_before_slow_peer_finishes(self):
        self.seed(5)
        initial = threading.Barrier(2)
        refill_started = threading.Event()
        call_lock = threading.Lock()
        calls = 0

        def fetch(url, root, timeout, *, download_only=False):
            nonlocal calls
            with call_lock:
                calls += 1
                call_number = calls
            if call_number <= 2:
                initial.wait(timeout=2)
            if call_number == 1:
                self.assertTrue(refill_started.wait(timeout=2))
            elif call_number >= 3:
                refill_started.set()
            return self.download(parse="not_applicable")

        with patch.object(docs, "_download_job", side_effect=fetch):
            report = docs.run_documents(
                self.root, max_documents=5, max_seconds=2, download_workers=2
            )
        self.assertEqual(report["phase_counts"], {"download": 5, "parse": 0})
        self.assertEqual(report["timing"]["download_refills"], 3)
        self.assertEqual(report["timing"]["download_waves"], 1)
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 5)

    def test_download_wave_timing_exposes_idle_slot(self):
        self.seed(2)
        barrier = threading.Barrier(2)

        def fetch(url, root, timeout, *, download_only=False):
            barrier.wait(timeout=2)
            time.sleep(0.01 if url.endswith("/0") else 0.08)
            return {
                "status": "download_timeout",
                "parse_status": "not_attempted",
                "files": [],
            }

        with patch.object(docs, "_download_job", side_effect=fetch):
            report = docs.run_documents(
                self.root, max_documents=2, max_seconds=2, download_workers=2
            )
        timing = report["timing"]
        self.assertEqual(timing["download_waves"], 1)
        self.assertGreaterEqual(timing["download_wave_seconds"], 0.07)
        self.assertGreaterEqual(timing["download_slot_idle_seconds"], 0.04)
        self.assertAlmostEqual(
            timing["download_slot_capacity_seconds"],
            2 * timing["download_wave_seconds"],
            places=5,
        )
        self.assertAlmostEqual(
            timing["download_slot_idle_seconds"],
            timing["download_slot_capacity_seconds"]
            - timing["download_job_seconds"],
            places=5,
        )

    def test_defaults_rollback_mode_can_parse_saved_pending_without_download(self):
        self.seed(1)
        with patch.object(docs, "_download_job", return_value=self.download()) as fetch:
            first = docs.run_documents(self.root, max_documents=1, download_workers=2)
        self.assertEqual(first["phase_counts"], {"download": 1, "parse": 0})
        self.assertEqual(self.query("SELECT parse_tries FROM documents")[0][0], 0)
        with (
            patch.object(
                docs, "_download_job", side_effect=AssertionError("raw must be reused")
            ),
            patch.object(
                docs,
                "_parse_saved",
                side_effect=lambda root, result, timeout: {
                    **result,
                    "parse_status": "parse_timeout",
                },
            ),
        ):
            second = docs.run_documents(self.root, max_documents=5)
        self.assertEqual(second["download_workers"], 1)
        self.assertEqual(second["processed"], 1)
        result, dtries, ptries, retry = self.query(
            "SELECT result,download_tries,parse_tries,parse_retry_after FROM documents"
        )[0]
        self.assertEqual(json.loads(result)["fetched_at"], self.stamp)
        self.assertEqual((dtries, ptries), (1, 1))
        self.assertGreater(retry, time.time())
        fetch.assert_called_once()

    def test_live_owner_keeps_expired_claim_during_refill(self):
        self.seed(2)
        db = docs._document_db(self.root)
        self.addCleanup(db.close)
        docs._claims_setup(db)
        with patch.object(docs.time, "time", return_value=1000):
            first = docs._claim_documents(db, "live-owner", "download", 1, 20)[0]
        # A wake/clock jump must not reclaim the running owner's other slot.
        with patch.object(docs.time, "time", return_value=2000):
            second = docs._claim_documents(db, "live-owner", "download", 1, 20)[0]
            self.assertNotEqual(first["id"], second["id"])
            docs._finish_document(db, "live-owner", first, self.download(), "download")
            docs._finish_document(db, "live-owner", second, self.download(), "download")
        self.assertEqual(db.execute("SELECT count(*) FROM document_attempts").fetchone()[0], 2)
        self.assertEqual(db.execute("SELECT count(*) FROM document_claims").fetchone()[0], 0)

    def test_claim_expiry_and_stale_result_fence(self):
        self.seed(1)
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        start = time.time()
        jobs = docs._claim_documents(db, "old-owner", "download", 1, 20)
        self.assertGreaterEqual(
            db.execute("SELECT lease_until FROM document_claims").fetchone()[0],
            start + 20 + docs.CLAIM_GRACE_SECONDS,
        )
        with patch.object(
            docs,
            "_download_job",
            side_effect=AssertionError("live claim must not repeat"),
        ):
            self.assertEqual(
                docs.run_documents(self.root, max_documents=1, download_workers=2)[
                    "processed"
                ],
                0,
            )
        db.execute("UPDATE document_claims SET lease_until=?", (time.time() - 1,))
        db.commit()
        with patch.object(docs, "_download_job", return_value=self.download()):
            self.assertEqual(
                docs.run_documents(self.root, max_documents=1, download_workers=2)[
                    "processed"
                ],
                1,
            )
        with self.assertRaisesRegex(docs.DocumentError, "stale_document_claim"):
            docs._finish_document(db, "old-owner", jobs[0], self.download(), "download")
        self.assertEqual(
            db.execute("SELECT count(*) FROM document_attempts").fetchone()[0], 1
        )
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        db.close()

    def test_ordered_claim_preserves_future_retry_claim_and_phase_semantics(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        now = time.time()

        def row(number, download, parse="not_attempted", retry=0, parse_retry=0):
            ident = f"{number:064x}"
            db.execute(
                "INSERT INTO documents(id,observation,url,download_status,"
                "parse_status,retry_after,parse_retry_after) VALUES(?,?,?,?,?,?,?)",
                (
                    ident,
                    "edge",
                    f"https://example.com/{number}",
                    download,
                    parse,
                    retry,
                    parse_retry,
                ),
            )
            return ident

        future_pending = row(0, "pending", retry=now + 3600)
        future_retry = row(1, "retry", retry=now + 3600)
        claimed_pending = row(2, "pending")
        due_retry = row(3, "retry", retry=now - 1)
        due_parse = row(4, "downloaded", "parse_pending", parse_retry=now - 1)
        due_pending = row(5, "pending")
        due_parse_retry = row(
            6, "downloaded", "parse_failed", parse_retry=now - 1
        )
        db.execute(
            "INSERT INTO document_claims VALUES(?,?,?,?,?)",
            (claimed_pending, "other", "download", now, now + 3600),
        )
        db.commit()

        jobs = docs._claim_documents(db, "mixed", None, 2, 20)
        self.assertEqual(
            [job["id"] for job in jobs], [due_retry, due_parse_retry]
        )
        with db:
            db.execute("DELETE FROM document_claims WHERE owner='mixed'")
        jobs = docs._claim_documents(db, "download", "download", 2, 20)
        self.assertEqual([job["id"] for job in jobs], [due_retry, due_pending])
        with db:
            db.execute("DELETE FROM document_claims WHERE owner='download'")
        jobs = docs._claim_documents(db, "parse", "parse", 1, 20)
        self.assertEqual([job["id"] for job in jobs], [due_parse_retry])
        selected = {job["id"] for job in jobs}
        self.assertNotIn(due_parse, selected)
        self.assertFalse(
            selected & {future_pending, future_retry, claimed_pending}
        )
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM documents INDEXED BY "
            "document_pending_claim_order WHERE download_status='pending' "
            "AND retry_after<=? AND NOT EXISTS(SELECT 1 FROM document_claims c "
            "WHERE c.document_id=documents.id) ORDER BY id LIMIT ?",
            (now, 2),
        ).fetchall()
        detail = [item[3] for item in plan]
        self.assertTrue(any("document_pending_claim_order" in item for item in detail))
        self.assertFalse(any("TEMP B-TREE" in item for item in detail))
        parse_plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM documents INDEXED BY "
            "document_parse_pending_claim_order WHERE download_status='downloaded' "
            "AND parse_status='parse_pending' AND parse_tries<5 "
            "AND parse_retry_after<=? AND NOT EXISTS(SELECT 1 FROM "
            "document_claims c WHERE c.document_id=documents.id) "
            "ORDER BY id LIMIT ?",
            (now, 2),
        ).fetchall()
        parse_detail = [item[3] for item in parse_plan]
        self.assertTrue(
            any("document_parse_pending_claim_order" in item for item in parse_detail)
        )
        self.assertFalse(any("TEMP B-TREE" in item for item in parse_detail))
        retry_plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM documents INDEXED BY "
            "document_parse_retry_claim_order WHERE download_status='downloaded' "
            "AND parse_status IN ('parse_unavailable','parse_failed',"
            "'parse_timeout') AND parse_tries<5 AND parse_retry_after<=? "
            "AND NOT EXISTS(SELECT 1 FROM document_claims c WHERE "
            "c.document_id=documents.id) ORDER BY id LIMIT ?",
            (now, 2),
        ).fetchall()
        retry_detail = [item[3] for item in retry_plan]
        self.assertTrue(
            any("document_parse_retry_claim_order" in item for item in retry_detail)
        )
        self.assertFalse(any("TEMP B-TREE" in item for item in retry_detail))
        db.close()

    def test_claim_v1_migration_is_transactional_and_observable(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        with db:
            db.execute("DROP INDEX document_pending_claim_order")
            db.execute("DROP INDEX document_parse_claim_order")
            db.execute("DROP INDEX document_parse_retry_claim_order")
            db.execute("DROP INDEX document_parse_pending_claim_order")
            db.execute("UPDATE document_claim_meta SET version=1")
        db.set_authorizer(
            lambda action, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_CREATE_INDEX
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            docs._claims_setup(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 1
        )
        self.assertFalse(
            db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='document_pending_claim_order'"
            ).fetchone()
        )
        timing = {}
        docs._claims_setup(db, timing)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='document_pending_claim_order'"
            ).fetchone()
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='document_parse_claim_order'"
            ).fetchone()
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='document_parse_retry_claim_order'"
            ).fetchone()
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='document_parse_pending_claim_order'"
            ).fetchone()
        )
        self.assertEqual(timing["setup_db_calls"], 1)
        self.assertGreaterEqual(
            timing["setup_db_total_seconds"], timing["setup_db_wait_seconds"]
        )
        db.close()

    def test_claim_v2_migration_adds_parse_order_atomically(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        with db:
            db.execute("DROP INDEX document_parse_claim_order")
            db.execute("DROP INDEX document_parse_retry_claim_order")
            db.execute("DROP INDEX document_parse_pending_claim_order")
            db.execute("UPDATE document_claim_meta SET version=2")
        db.set_authorizer(
            lambda action, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_CREATE_INDEX
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            docs._claims_setup(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 2
        )
        self.assertFalse(
            db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='document_parse_claim_order'"
            ).fetchone()
        )
        docs._claims_setup(db)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='document_parse_claim_order'"
            ).fetchone()
        )
        db.close()

    def test_claim_v3_requeues_only_darwin_resource_limit_failures(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        cases = (
            (0, "parse_unavailable", "resource_limits_unavailable", 5, 0),
            (1, "parse_unavailable", "resource_limits_unavailable", 2, 0),
            (2, "parse_unavailable", "pypdf_not_installed", 5, 5),
            (3, "parse_failed", "resource_limits_unavailable", 5, 5),
        )
        with db:
            db.execute("DROP INDEX document_parse_retry_claim_order")
            db.execute("DROP INDEX document_parse_pending_claim_order")
            for number, status, reason, tries, _ in cases:
                db.execute(
                    "INSERT INTO documents(id,observation,url,download_status,"
                    "parse_status,parse_tries,parse_retry_after,result) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        f"{number:064x}",
                        "migration",
                        f"https://example.com/{number}.pdf",
                        "downloaded",
                        status,
                        tries,
                        time.time() + 3600,
                        json.dumps({"parse_detail": {"reason": reason}}),
                    ),
                )
            db.execute("UPDATE document_claim_meta SET version=3")

        db.set_authorizer(
            lambda action, table, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE and table == "documents"
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            docs._claims_setup(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 3
        )
        self.assertEqual(
            [
                tuple(row)
                for row in db.execute(
                    "SELECT parse_tries FROM documents ORDER BY id"
                ).fetchall()
            ],
            [(case[3],) for case in cases],
        )

        docs._claims_setup(db)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        self.assertEqual(
            [
                tuple(row)
                for row in db.execute(
                    "SELECT parse_tries FROM documents ORDER BY id"
                ).fetchall()
            ],
            [(case[4],) for case in cases],
        )
        self.assertEqual(
            db.execute(
                "SELECT count(*) FROM documents WHERE parse_retry_after=0"
            ).fetchone()[0],
            2,
        )
        db.close()

    def test_claim_v4_requeues_only_cpu_limited_parser_failures(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        cases = (
            (0, "parse_failed", "parser_process_failed", 5, 0),
            (1, "parse_failed", "parser_process_error", 5, 5),
            (2, "parse_timeout", "parser_process_failed", 5, 5),
            (3, "parse_unavailable", "parser_process_failed", 5, 5),
        )
        with db:
            db.execute("DROP INDEX document_parse_retry_claim_order")
            db.execute("DROP INDEX document_parse_pending_claim_order")
            for number, status, reason, tries, _ in cases:
                db.execute(
                    "INSERT INTO documents(id,observation,url,download_status,"
                    "parse_status,parse_tries,parse_retry_after,result) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        f"{number:064x}",
                        "migration",
                        f"https://example.com/{number}.pdf",
                        "downloaded",
                        status,
                        tries,
                        time.time() + 3600,
                        json.dumps({"parse_detail": {"reason": reason}}),
                    ),
                )
            db.execute("UPDATE document_claim_meta SET version=4")

        db.set_authorizer(
            lambda action, table, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE and table == "documents"
                else sqlite3.SQLITE_OK
            )
        )
        with self.assertRaises(sqlite3.DatabaseError):
            docs._claims_setup(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 4
        )
        self.assertEqual(
            [row[0] for row in db.execute("SELECT parse_tries FROM documents ORDER BY id")],
            [case[3] for case in cases],
        )

        docs._claims_setup(db)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        self.assertEqual(
            [row[0] for row in db.execute("SELECT parse_tries FROM documents ORDER BY id")],
            [case[4] for case in cases],
        )
        self.assertEqual(
            db.execute(
                "SELECT count(*) FROM documents WHERE parse_retry_after=0"
            ).fetchone()[0],
            1,
        )
        db.close()

    def test_claim_v5_adds_retry_order_without_replaying_cpu_recovery(self):
        db = docs._document_db(self.root)
        docs._claims_setup(db)
        with db:
            db.execute("DROP INDEX document_parse_retry_claim_order")
            db.execute("DROP INDEX document_parse_pending_claim_order")
            db.execute(
                "INSERT INTO documents(id,observation,url,download_status,"
                "parse_status,parse_tries,parse_retry_after,result) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    "f" * 64,
                    "migration",
                    "https://example.com/retry.pdf",
                    "downloaded",
                    "parse_failed",
                    3,
                    time.time() + 3600,
                    json.dumps(
                        {"parse_detail": {"reason": "parser_process_failed"}}
                    ),
                ),
            )
            db.execute("UPDATE document_claim_meta SET version=5")

        docs._claims_setup(db)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 7
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='document_parse_retry_claim_order'"
            ).fetchone()
        )
        self.assertTrue(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='document_parse_pending_claim_order'"
            ).fetchone()
        )
        self.assertEqual(
            db.execute(
                "SELECT parse_tries FROM documents WHERE id=?", ("f" * 64,)
            ).fetchone()[0],
            3,
        )
        db.close()

    def test_wal_reader_does_not_delay_claim_writer(self):
        self.seed(1)
        db = docs._document_db(self.root, timeout=0.2)
        docs._claims_setup(db)
        reader = sqlite3.connect(
            self.root / "documents.sqlite", check_same_thread=False
        )
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM documents").fetchone()
        timing = {}
        jobs = docs._claim_documents(db, "owner", "download", 1, 20, timing)
        self.assertEqual(len(jobs), 1)
        self.assertLess(timing["claim_db_wait_seconds"], 0.01)
        self.assertEqual(
            db.execute(
                "SELECT count(*) FROM document_claims WHERE owner='owner'"
            ).fetchone()[0],
            1,
        )
        db.close()
        reader.close()

    def test_document_counts_use_covering_status_index(self):
        self.seed(4)
        db = docs._document_db(self.root)
        ids = [row[0] for row in db.execute("SELECT id FROM documents ORDER BY id")]
        db.execute(
            "UPDATE documents SET download_status='downloaded',parse_status='parsed' "
            "WHERE id=?",
            (ids[0],),
        )
        db.execute(
            "UPDATE documents SET download_status='downloaded',parse_status='no_text' "
            "WHERE id=?",
            (ids[1],),
        )
        db.commit()
        self.assertEqual(
            docs._document_counts(db),
            [
                {"download_status": "downloaded", "parse_status": "no_text", "documents": 1},
                {"download_status": "downloaded", "parse_status": "parsed", "documents": 1},
                {"download_status": "pending", "parse_status": "not_attempted", "documents": 2},
            ],
        )
        self.assertTrue(
            any(
                "USING COVERING INDEX document_status_counts" in row[3]
                for row in db.execute(
                    "EXPLAIN QUERY PLAN SELECT download_status,parse_status,count(*) "
                    "FROM documents GROUP BY download_status,parse_status"
                )
            )
        )
        db.close()

    def test_claim_commit_lock_rolls_back_and_next_run_recovers(self):
        self.seed(1)
        db = docs._document_db(self.root, timeout=0.02)
        docs._claims_setup(db)
        reader = sqlite3.connect(self.root / "documents.sqlite")
        reader.execute("BEGIN IMMEDIATE")
        timing = {}
        with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
            docs._claim_documents(db, "owner", "download", 1, 20, timing)
        self.assertFalse(db.in_transaction)
        self.assertEqual(
            db.execute(
                "SELECT count(*) FROM document_claims WHERE owner='owner'"
            ).fetchone()[0],
            0,
        )
        self.assertGreaterEqual(timing["claim_db_total_seconds"], 0.01)
        reader.rollback()
        reader.close()
        self.assertEqual(
            len(docs._claim_documents(db, "recovered", "download", 1, 20)), 1
        )
        db.close()

    def test_short_writer_collision_waits_at_claim_begin(self):
        self.seed(1)
        db = docs._document_db(self.root, timeout=0.2)
        docs._claims_setup(db)
        holder = sqlite3.connect(
            self.root / "documents.sqlite", check_same_thread=False
        )
        holder.execute("BEGIN IMMEDIATE")
        release = self.release_later(holder)
        timing = {}
        jobs = docs._claim_documents(db, "owner", "download", 1, 20, timing)
        release.join()
        self.assertEqual(len(jobs), 1)
        self.assertGreaterEqual(timing["claim_db_wait_seconds"], 0.01)
        db.close()
        holder.close()

    def test_finish_commit_lock_rolls_back_attempt_state_and_claim(self):
        self.seed(1)
        db = docs._document_db(self.root, timeout=0.02)
        docs._claims_setup(db)
        job = docs._claim_documents(db, "owner", "download", 1, 20)[0]
        reader = sqlite3.connect(self.root / "documents.sqlite")
        reader.execute("BEGIN IMMEDIATE")
        result = {
            "status": "downloaded",
            "mime": "application/pdf",
            "parse_status": "parse_pending",
            "files": [self.original],
        }
        with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
            docs._finish_document(db, "owner", job, result.copy(), "download")
        self.assertFalse(db.in_transaction)
        self.assertEqual(
            tuple(
                db.execute(
                    "SELECT download_status,download_tries FROM documents"
                ).fetchone()
            ),
            ("pending", 0),
        )
        self.assertEqual(
            db.execute("SELECT count(*) FROM document_attempts").fetchone()[0], 0
        )
        self.assertEqual(
            db.execute("SELECT count(*) FROM document_claims").fetchone()[0], 1
        )
        reader.rollback()
        reader.close()
        docs._finish_document(db, "owner", job, result.copy(), "download")
        self.assertEqual(
            tuple(
                db.execute(
                    "SELECT download_status,download_tries FROM documents"
                ).fetchone()
            ),
            ("downloaded", 1),
        )
        self.assertEqual(
            db.execute("SELECT count(*) FROM document_attempts").fetchone()[0], 1
        )
        self.assertEqual(
            db.execute("SELECT count(*) FROM document_claims").fetchone()[0], 0
        )
        db.close()

    def test_total_budget_request_bound_and_global_lock(self):
        self.seed(8)
        with (self.root / "documents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(
                docs.run_documents(self.root, download_workers=2)["status"],
                "already_running",
            )
        active, peak = 0, 0
        guard = threading.Lock()

        def slow(url, root, timeout, *, download_only=False):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(min(0.06, timeout))
            with guard:
                active -= 1
            return {
                "status": "download_timeout",
                "parse_status": "not_attempted",
                "files": [],
            }

        start = time.monotonic()
        with patch.object(docs, "_download_job", side_effect=slow):
            result = docs.run_documents(
                self.root,
                max_documents=3,
                max_seconds=0.09,
                download_workers=2,
                overlap_parse_download=True,
            )
        self.assertLess(time.monotonic() - start, 0.25)
        self.assertLessEqual(result["processed"], 3)
        self.assertEqual(result["processed"], result["timing"]["finish_db_calls"])
        self.assertEqual(peak, 2)
        for value in (0, 17, True, 2.0):
            with self.assertRaises(ValueError):
                docs.run_documents(self.root, download_workers=value)
        for value in (0, 1, "true", None):
            with self.assertRaises(ValueError):
                docs.run_documents(self.root, overlap_parse_download=value)
        for value in (0, 5, True, 1.5):
            with self.assertRaises(ValueError):
                docs.run_documents(self.root, parse_workers=value)
        with self.assertRaises(ValueError):
            docs.run_documents(self.root, parse_workers=2)
        with self.assertRaises(ValueError):
            docs.run_documents(
                self.root,
                download_workers=1,
                overlap_parse_download=True,
                parse_workers=2,
            )

    def test_child_absolute_deadline_is_self_enforced_without_parent_timeout(self):
        # A real isolated local child dies from its own timer; no network involved.
        code = "import time; from backend.shared.tushare_documents import _arm_document_deadline; _arm_document_deadline(time.time()+0.1); time.sleep(10)"
        start = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            timeout=3,
        )
        self.assertEqual(result.returncode, -signal.SIGALRM)
        self.assertLess(time.monotonic() - start, 2)
        worker = Mock(returncode=0)
        worker.communicate.return_value = (json.dumps(self.download()).encode(), b"")
        worker.poll.return_value = 0
        with patch.object(docs.subprocess, "Popen", return_value=worker):
            result = docs._download_job(
                "https://example.com/1", self.root, 2, download_only=True
            )
        payload = json.loads(worker.communicate.call_args.args[0])
        self.assertTrue(payload["download_only"])
        self.assertLessEqual(payload["deadline_at"], time.time() + 2)
        self.assertEqual(result["fetched_at"], self.stamp)
        worker.returncode = -signal.SIGALRM
        with patch.object(docs.subprocess, "Popen", return_value=worker):
            self.assertEqual(
                docs._download_job("https://example.com/1", self.root, 2)["status"],
                "download_timeout",
            )
        with (
            patch.object(docs.sys, "platform", "linux"),
            patch.object(docs.subprocess, "run", return_value=worker),
        ):
            self.assertEqual(
                docs._parse_pdf(self.root / "unused.pdf", 2)["parse_status"],
                "parse_timeout",
            )

    def test_download_only_does_not_start_pdf_parser(self):
        # Use only existing deterministic response fixtures; DNS/HTTP are mocked.
        from scripts.test_tushare_documents import Response, resolution

        response = Response(b"%PDF-fixture\n%%EOF", Content_Type="application/pdf")
        connection = Mock()
        connection.getresponse.return_value = response
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=connection),
            patch.object(
                docs, "_parse_pdf", side_effect=AssertionError("no parser in transfer")
            ),
        ):
            result = docs.fetch_document(
                "https://example.com/1.pdf", self.root, download_only=True
            )
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["parse_status"], "parse_pending")
        self.assertEqual(result["files"][0]["mime"], "application/pdf")


if __name__ == "__main__":
    unittest.main()
