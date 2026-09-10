"""Bounded document registration: real temp SQLite locks, no network or secrets."""

import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_documents as docs
from backend.shared import tushare_pipeline as module


class RegistrationBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)
        self.serial = 0
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
        ):
            g = patch(target, side_effect=AssertionError("offline"))
            g.start()
            self.addCleanup(g.stop)

    def seed(self, rows, api="anns_d"):
        self.serial += 1
        fields = list(rows[0]) if rows else ["url"]
        body = module.json_bytes(
            {
                "code": 0,
                "data": {
                    "fields": fields,
                    "items": [[r.get(f) for f in fields] for r in rows],
                },
            }
        )
        sha = hashlib.sha256(body).hexdigest()
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / "objects" / f"{sha}.json").write_bytes(body)
        observation = f"{self.serial:032x}.json"
        (self.root / "observations").mkdir(exist_ok=True)
        (self.root / "observations" / observation).write_bytes(
            module.json_bytes({"object_sha256": sha, "fixture": self.serial})
        )
        result = {
            "api_name": api,
            "status": "sample_ok",
            "object_sha256": sha,
            "observation": observation,
        }
        self.p.db.execute(
            "INSERT INTO attempts VALUES(?,?,?)",
            (str(self.serial), 1, json.dumps(result)),
        )
        rowid = self.p.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.p.db.commit()
        return rowid, result

    def state(self):
        return [
            tuple(r)
            for r in self.p.db.execute(
                "SELECT name,value FROM scheduler_state WHERE name LIKE 'document_%' ORDER BY name"
            )
        ]

    def inventory(self, root=None):
        db = docs._document_db(root or self.root)
        try:
            return {
                table: [
                    tuple(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY id")
                ]
                for table in ("documents", "document_refs")
            }
        finally:
            db.close()

    def reopen(self):
        self.p.close()
        self.p = module.Pipeline(self.root, {"entries": []})
        self.addCleanup(self.p.close)

    def test_1205_rows_resume_matches_exact_legacy_reference_inventory(self):
        rows = [
            {
                "url": f"https://example.com/{n}.pdf" if n % 3 else None,
                "title": f"来源{n}",
                "unknown": n,
            }
            for n in range(1205)
        ]
        rowid, result = self.seed(rows)
        body_path = self.root / "objects" / f"{result['object_sha256']}.json"
        before = body_path.read_bytes()
        for expected in (500, 1000):
            out = self.p.register_documents()
            self.assertEqual(out["processed_records"], 500)
            self.assertEqual(out["observations"], 0)
            self.assertEqual(out["cursor"], 0)
            self.assertEqual(out["record_offset"], expected)
            self.reopen()
        final = self.p.register_documents()
        self.assertEqual(final["processed_records"], 205)
        self.assertEqual(final["observations"], 1)
        self.assertEqual(final["cursor"], rowid)
        self.assertIsNone(final["partial_attempt"])
        original = subprocess.check_output(
            ["git", "show", "0c18fb2:backend/shared/tushare_documents.py"],
            cwd=Path(__file__).resolve().parents[1],
        ).decode()
        node = next(
            n
            for n in ast.parse(original).body
            if isinstance(n, ast.FunctionDef) and n.name == "enqueue_documents"
        )
        ns = {}
        exec(
            compile(
                ast.Module(body=[node], type_ignores=[]),
                "<baseline enqueue_documents>",
                "exec",
            ),
            docs.__dict__,
            ns,
        )
        with tempfile.TemporaryDirectory() as expected_root:
            ns["enqueue_documents"](
                expected_root, result["observation"], "anns_d", rows, ["url"]
            )
            self.assertEqual(self.inventory(), self.inventory(expected_root))
        self.assertEqual(body_path.read_bytes(), before)
        self.assertEqual(self.p.register_documents()["observations"], 0)

    def test_document_commit_before_pipeline_failure_replays_without_duplicate_refs(
        self,
    ):
        rows = [{"url": f"https://example.com/{n}"} for n in range(120)]
        self.seed(rows)
        self.p.db.execute(
            "CREATE TRIGGER fail_offset BEFORE INSERT ON scheduler_state WHEN NEW.name GLOB 'document_offset:*' BEGIN SELECT RAISE(ABORT,'fixture checkpoint crash'); END"
        )
        self.p.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.p.register_documents(max_records=100)
        self.assertEqual(self.state(), [])
        self.assertEqual(len(self.inventory()["document_refs"]), 100)
        self.reopen()
        self.p.db.execute("DROP TRIGGER fail_offset")
        self.p.db.commit()
        out = self.p.register_documents()
        self.assertEqual(out["observations"], 1)
        self.assertEqual(len(self.inventory()["document_refs"]), 120)
        self.assertEqual(len(self.inventory()["documents"]), 120)

    def test_pipeline_checkpoint_busy_after_document_commit_replays(self):
        self.seed([{"url": "https://example.com/a.pdf"}])
        database = self.p.db.execute("PRAGMA database_list").fetchone()[2]
        lock = sqlite3.connect(database, timeout=0.05)
        self.addCleanup(lock.close)
        original = docs.enqueue_documents

        def commit_then_lock(*args, **kwargs):
            receipt = original(*args, **kwargs)
            lock.execute("BEGIN IMMEDIATE")
            return receipt

        with patch.object(docs, "enqueue_documents", side_effect=commit_then_lock):
            result = self.p.register_documents(max_seconds=0.3)
        self.assertEqual(result["status"], "deferred_database_busy")
        self.assertTrue(result["checkpoint_pending"])
        self.assertEqual(result["cursor"], 0)
        self.assertEqual(result["processed_records"], 1)
        self.assertEqual(len(self.inventory()["document_refs"]), 1)
        lock.rollback()
        self.assertEqual(self.state(), [])
        self.reopen()
        self.assertEqual(self.p.register_documents()["observations"], 1)
        self.assertEqual(len(self.inventory()["document_refs"]), 1)

    def test_no_attachment_contracts_preserves_existing_checkpoint(self):
        self.seed([{"url": None}])
        with patch.object(module, "EXTENDED_CONTRACTS", {}):
            result = self.p.register_documents()
        self.assertEqual(result["observations"], 0)
        self.assertEqual(self.state(), [])

    def test_busy_writer_defers_in_under_one_second_and_restarts(self):
        rowid, _ = self.seed([{"url": "https://example.com/a.pdf"}])
        lock = docs._document_db(self.root)
        self.addCleanup(lock.close)
        lock.execute("BEGIN IMMEDIATE")
        self.p.db.execute("PRAGMA busy_timeout=1234")
        started = time.monotonic()
        result = self.p.register_documents(max_seconds=0.3)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(result["status"], "deferred_database_busy")
        self.assertEqual(result["observations"], 0)
        self.assertEqual(result["cursor"], 0)
        self.assertEqual(result["record_offset"], 0)
        self.assertEqual(self.p.db.execute("PRAGMA busy_timeout").fetchone()[0], 1234)
        lock.rollback()
        self.reopen()
        self.assertEqual(self.p.register_documents()["cursor"], rowid)
        self.assertEqual(len(self.inventory()["document_refs"]), 1)

    def test_busy_reader_at_document_commit_rolls_back_chunk(self):
        self.seed([{"url": "https://example.com/a.pdf"}])
        lock = docs._document_db(self.root)
        self.addCleanup(lock.close)
        lock.execute("BEGIN")
        lock.execute("SELECT count(*) FROM document_refs").fetchone()
        started = time.monotonic()
        result = self.p.register_documents(max_seconds=0.3)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(result["status"], "deferred_database_busy")
        self.assertEqual(result["processed_records"], 0)
        self.assertEqual(result["cursor"], 0)
        lock.rollback()
        self.assertEqual(self.inventory()["document_refs"], [])
        self.assertEqual(self.p.register_documents()["observations"], 1)

    def test_mid_chunk_deadline_commits_only_completed_records_not_fake_empty(self):
        rows = [{"url": f"https://example.com/{n}"} for n in range(20)]
        now = [0.0]
        original = docs._reference_hash

        def costly_hash(value):
            now[0] += 0.01
            return original(value)

        with (
            patch.object(docs.time, "monotonic", side_effect=lambda: now[0]),
            patch.object(docs, "_reference_hash", side_effect=costly_hash),
        ):
            result = docs.enqueue_documents(
                self.root, "obs", "anns_d", rows, ["url"], deadline=0.035
            )
        self.assertFalse(result["complete"])
        self.assertGreater(result["processed_records"], 0)
        self.assertLess(result["processed_records"], len(rows))
        self.assertEqual(
            len(self.inventory()["document_refs"]), result["processed_records"]
        )
        with patch.object(docs.time, "monotonic", return_value=1):
            expired = docs.enqueue_documents(
                self.root, "not-empty", "anns_d", rows, ["url"], deadline=0
            )
        self.assertEqual(expired["processed_records"], 0)
        self.assertEqual(
            len(self.inventory()["document_refs"]), result["processed_records"]
        )

    def test_expensive_single_sql_interrupts_without_advancing_offset(self):
        self.seed([{"url": "https://example.com/a.pdf"}])
        db = docs._document_db(self.root)
        db.execute(
            "CREATE TRIGGER slow_reference BEFORE INSERT ON document_refs BEGIN SELECT sum(n) FROM (WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x WHERE n<100000000) SELECT n FROM x); END"
        )
        db.commit()
        db.close()
        started = time.monotonic()
        result = self.p.register_documents(max_seconds=0.1)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(result["status"], "deferred_budget")
        self.assertEqual(result["processed_records"], 0)
        self.assertEqual(result["cursor"], 0)
        self.assertEqual(self.inventory()["document_refs"], [])
        db = docs._document_db(self.root)
        db.execute("DROP TRIGGER slow_reference")
        db.commit()
        db.close()
        self.assertEqual(self.p.register_documents()["observations"], 1)

    def test_partial_source_change_or_missing_attempt_is_not_skipped(self):
        rowid, result = self.seed(
            [{"url": f"https://example.com/{n}"} for n in range(2)]
        )
        self.p.register_documents(max_records=1)
        before = self.state()
        changed = {**result, "observation": "changed.json"}
        self.p.db.execute(
            "UPDATE attempts SET result=? WHERE rowid=?", (json.dumps(changed), rowid)
        )
        self.p.db.commit()
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.p.register_documents()
        self.assertEqual(self.state(), before)
        self.p.db.execute("DELETE FROM attempts")
        self.p.db.commit()
        with self.assertRaisesRegex(ValueError, "attempt is missing"):
            self.p.register_documents()
        self.assertEqual(self.state(), before)

    def test_unrelated_attempt_tail_scans_1000_once_and_reaches_document(self):
        self.p.db.executemany(
            "INSERT INTO attempts VALUES(?,?,?)",
            [(f"other{n}", 1, json.dumps({"api_name": "daily"})) for n in range(1500)],
        )
        self.p.db.commit()
        rowid, _ = self.seed([{"url": None}])
        first = self.p.register_documents()
        self.assertEqual(first["scanned_attempts"], 1000)
        self.assertEqual(first["cursor"], 1000)
        self.assertEqual(first["observations"], 0)
        second = self.p.register_documents()
        self.assertEqual(second["cursor"], rowid)
        self.assertEqual(second["observations"], 1)
        self.assertEqual(len(self.inventory()["document_refs"]), 1)

    def test_empty_and_duplicate_observations_preserve_explicit_refs_and_reuse(self):
        _, first = self.seed([])
        self.seed([{"url": "https://example.com/a.pdf"}])
        self.seed([{"url": "https://example.com/a.pdf"}])
        result = self.p.register_documents()
        self.assertEqual(result["observations"], 3)
        inv = self.inventory()
        self.assertEqual(len(inv["document_refs"]), 3)
        self.assertEqual(len(inv["documents"]), 1)
        self.assertIn("no_records", {r[-1] for r in inv["document_refs"]})
        self.assertIn("reused_pending", {r[-1] for r in inv["document_refs"]})
        self.assertEqual(self.p.db.execute("PRAGMA user_version").fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
