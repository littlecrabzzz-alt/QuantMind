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
        self.assertEqual(
            self.query("SELECT download_tries,parse_tries FROM documents"),
            [(1, 1), (1, 1)],
        )
        self.assertEqual(self.query("SELECT count(*) FROM document_claims")[0][0], 0)
        self.assertEqual(self.query("SELECT count(*) FROM document_attempts")[0][0], 4)

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
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(
            db.execute("SELECT version FROM document_claim_meta").fetchone()[0], 1
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
                self.root, max_documents=3, max_seconds=0.09, download_workers=2
            )
        self.assertLess(time.monotonic() - start, 0.25)
        self.assertLessEqual(result["processed"], 3)
        self.assertEqual(peak, 2)
        for value in (0, 3, True, 2.0):
            with self.assertRaises(ValueError):
                docs.run_documents(self.root, download_workers=value)

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
        with patch.object(docs.subprocess, "run", return_value=worker):
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
