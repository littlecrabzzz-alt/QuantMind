import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.shared import tushare_documents as docs
from scripts.test_tushare_documents import Response, connection, resolution


class TerminalDocumentRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qm-document-terminal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = docs._document_db(self.root)
        docs._claims_setup(self.db)

    def tearDown(self):
        self.db.close()

    def seed(self, number, status, *, url=None, retry_after=0, extra=None):
        ident = f"{number:064x}"
        result = {
            "status": status,
            "parse_status": "not_attempted",
            "files": [],
            **(extra or {}),
        }
        raw = json.dumps(result)
        self.db.execute(
            "INSERT INTO documents(id,observation,url,expected_mime,download_status,"
            "parse_status,download_tries,parse_tries,retry_after,parse_retry_after,"
            "result) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "fixture",
                url or f"https://example.com/{number}.pdf",
                "application/pdf",
                "blocked",
                "not_attempted",
                5,
                0,
                retry_after,
                0,
                raw,
            ),
        )
        self.db.execute(
            "INSERT INTO document_attempts(document_id,phase,result,created_at) "
            "VALUES(?,?,?,?)",
            (ident, "download", raw, retry_after - 1),
        )
        self.db.commit()
        return ident, raw

    def test_bounded_fair_retry_preserves_attempts_and_results(self):
        now = 2_000_000_000
        old = now - 86401
        fixtures = [
            self.seed(1, "invalid_url", url="https://example.com/a.pdf ", retry_after=old),
            self.seed(
                2,
                "size_limit",
                retry_after=old,
                extra={"response_headers": {"content-length": str(40 * 1024**2)}},
            ),
            self.seed(3, "source_challenge", retry_after=old),
            self.seed(4, "pdf_content_mismatch", retry_after=old),
            self.seed(5, "download_timeout", retry_after=old),
        ]
        recent, _ = self.seed(6, "source_challenge", retry_after=now)
        too_large, _ = self.seed(
            7,
            "size_limit",
            retry_after=old,
            extra={"response_headers": {"content-length": str(300 * 1024**2)}},
        )
        unsafe, _ = self.seed(
            8, "invalid_url", url="https://example.com/a.pdf\n", retry_after=old
        )

        report = docs._schedule_terminal_retries(
            self.db,
            now=now,
            interval_seconds=86400,
            max_documents=5,
            max_bytes=256 * 1024**2,
        )
        self.assertEqual(report["status"], "scheduled")
        self.assertEqual(
            [item["category"] for item in report["scheduled"]],
            [
                "normalized_url",
                "larger_size_limit",
                "source_challenge",
                "content_recheck",
                "transient_failure",
            ],
        )
        self.assertEqual(report["preserved_attempts"], 5)
        for ident, raw in fixtures:
            row = self.db.execute(
                "SELECT download_status,download_tries,result FROM documents WHERE id=?",
                (ident,),
            ).fetchone()
            self.assertEqual(tuple(row), ("retry", 5, raw))
            self.assertEqual(
                self.db.execute(
                    "SELECT count(*) FROM document_attempts WHERE document_id=?", (ident,)
                ).fetchone()[0],
                1,
            )
        for ident in (recent, too_large, unsafe):
            self.assertEqual(
                self.db.execute(
                    "SELECT download_status FROM documents WHERE id=?", (ident,)
                ).fetchone()[0],
                "blocked",
            )
        self.assertEqual(
            docs._schedule_terminal_retries(
                self.db,
                now=now,
                interval_seconds=86400,
                max_documents=5,
                max_bytes=256 * 1024**2,
            )["status"],
            "no_action",
        )

    def test_increased_size_limit_retries_immediately_without_reopening_other_failures(self):
        now = 2_000_000_000
        self.seed(1, "size_limit", retry_after=now, extra={
            "max_bytes": 256 * 1024**2,
            "response_headers": {"content-length": "297216747"},
        })
        self.seed(2, "download_timeout", retry_after=now)
        self.seed(3, "size_limit", retry_after=now, extra={
            "max_bytes": docs.MAX_DOCUMENT_MAX_BYTES,
            "response_headers": {"content-length": "297216747"},
        })
        self.seed(4, "size_limit", retry_after=now - 86401, extra={
            "max_bytes": 256 * 1024**2,
            "response_headers": {"content-length": str(400 * 1024**2)},
        })
        report = docs._schedule_terminal_retries(
            self.db, now=now, interval_seconds=86400, max_documents=4,
            max_bytes=docs.MAX_DOCUMENT_MAX_BYTES,
        )
        self.assertEqual(len(report["scheduled"]), 1)
        self.assertEqual(report["scheduled"][0]["category"], "larger_size_limit")
        states = [row[0] for row in self.db.execute("SELECT download_status FROM documents ORDER BY id")]
        self.assertEqual(states, ["retry", "blocked", "blocked", "blocked"])
        self.assertEqual(docs._schedule_terminal_retries(
            self.db, now=now, interval_seconds=86400, max_documents=4,
            max_bytes=docs.MAX_DOCUMENT_MAX_BYTES,
        )["status"], "no_action")

    def test_due_retry_is_not_starved_by_lower_pending_ids(self):
        now = 2_000_000_000
        pending, _ = self.seed(1, "download_error")
        retry, _ = self.seed(100, "download_error")
        self.db.execute("UPDATE documents SET download_status='pending' WHERE id=?", (pending,))
        self.db.execute("UPDATE documents SET download_status='retry',retry_after=? WHERE id=?", (now, retry))
        self.db.commit()
        self.assertEqual(docs._eligible_documents(self.db, "download", now, 1)[0]["id"], retry)
        self.db.execute("UPDATE documents SET retry_after=? WHERE id=?", (now + 60, retry))
        self.db.commit()
        self.assertEqual(docs._eligible_documents(self.db, "download", now, 1)[0]["id"], pending)

    def test_source_challenge_cools_down_after_a_repeat(self):
        now = 2_000_000_000
        ident, raw = self.seed(
            1, "source_challenge", retry_after=now - 86401
        )
        docs._schedule_terminal_retries(
            self.db,
            now=now,
            interval_seconds=86400,
            max_documents=1,
            max_bytes=docs.DEFAULT_DOCUMENT_MAX_BYTES,
        )
        self.db.execute(
            "UPDATE documents SET download_status='blocked',download_tries=6,"
            "retry_after=?,result=? WHERE id=?",
            (now + 120, raw, ident),
        )
        self.db.commit()
        self.assertEqual(
            docs._schedule_terminal_retries(
                self.db,
                now=now + 86400,
                interval_seconds=86400,
                max_documents=1,
                max_bytes=docs.DEFAULT_DOCUMENT_MAX_BYTES,
            )["status"],
            "no_action",
        )
        self.assertEqual(
            docs._schedule_terminal_retries(
                self.db,
                now=now + 86400 + 121,
                interval_seconds=86400,
                max_documents=1,
                max_bytes=docs.DEFAULT_DOCUMENT_MAX_BYTES,
            )["status"],
            "scheduled",
        )

    def test_nondefault_size_cap_reaches_download_child(self):
        docs.enqueue_documents(
            self.root,
            "fixture",
            "anns_d",
            [{"url": "https://example.com/a.pdf"}],
            ["url"],
        )
        downloaded = {
            "status": "downloaded",
            "mime": "text/html",
            "parse_status": "not_applicable",
            "files": [],
        }
        with patch.object(docs, "_download_job", return_value=downloaded) as child:
            report = docs.run_documents(
                self.root,
                max_documents=1,
                max_seconds=2,
                download_workers=2,
                max_bytes=256 * 1024**2,
            )
        self.assertEqual(report["processed"], 1)
        child.assert_called_once_with(
            "https://example.com/a.pdf",
            self.root.resolve(),
            unittest.mock.ANY,
            download_only=True,
            max_bytes=256 * 1024**2,
        )

    def test_trailing_ascii_space_is_recorded_and_normalized(self):
        body = b"%PDF-1.7\n%%EOF"
        conn = connection(
            Response(body, Content_Type="application/pdf", Content_Length=str(len(body)))
        )
        with (
            patch.object(docs.socket, "getaddrinfo", return_value=resolution()),
            patch.object(docs, "_connection", return_value=conn),
        ):
            result = docs.fetch_document(
                "https://example.com/report.pdf ", self.root, download_only=True
            )
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(
            result["normalized_source_url"], "https://example.com/report.pdf"
        )
        self.assertEqual(result["source_url_normalization"], "trim_ascii_space")
        self.assertEqual(conn.request.call_args.args[1], "/report.pdf")


if __name__ == "__main__":
    unittest.main()
