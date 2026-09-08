"""Versioned document shards: temporary fixtures, no upstream or credentials."""

import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from backend.shared import tushare_documents as docs  # noqa: E402
from backend.services.engine.routers import tushare_data as api  # noqa: E402
from backend.services.engine.auth_context import get_authenticated_identity  # noqa: E402


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class DocumentIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tushare-index-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(api, "ROOT", self.root).start()
        self.connect = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ).start()
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        ).start()
        self.db = docs._document_db(self.root)
        self.addCleanup(self.db.close)
        self.doc = sha("document")
        self.original = docs._save(
            self.root, "attachments", ".html", b"<p>original</p>", "text/html"
        )
        self.result = {
            "status": "downloaded",
            "parse_status": "parse_failed",
            "files": [self.original],
            "fetched_at": "2026-09-08T01:02:03Z",
        }
        self.db.execute(
            "INSERT INTO documents(id,observation,url,download_status,parse_status,result) VALUES(?,?,?,?,?,?)",
            (
                self.doc,
                "original-observation",
                "https://example.com/1",
                "downloaded",
                "parse_failed",
                json.dumps(self.result),
            ),
        )
        self.db.commit()
        app = FastAPI()
        app.dependency_overrides[get_authenticated_identity] = lambda: (
            "fixture-reader",
            "test",
        )
        app.include_router(api.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def tearDown(self):
        self.connect.assert_not_called()
        self.dns.assert_not_called()

    def refs(self, start, count):
        self.db.executemany(
            "INSERT INTO document_refs VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    sha("ref" + str(i)),
                    f"observation-{i}",
                    "anns_d",
                    sha("record" + str(i)),
                    "url",
                    "https://example.com/1",
                    self.doc,
                    "reused",
                )
                for i in range(start, start + count)
            ],
        )
        self.db.commit()

    def attempt(self, phase, result, at):
        self.db.execute(
            "INSERT INTO document_attempts(document_id,phase,result,created_at) VALUES(?,?,?,?)",
            (self.doc, phase, json.dumps(result), at),
        )
        self.db.commit()

    def index(self):
        saved = docs.document_index(self.root)
        return saved, json.loads((self.root / saved["path"]).read_bytes())

    def publish(self, saved):
        files = {
            item["path"]: {key: item[key] for key in ("sha256", "bytes")}
            for item in saved["files"]
        }
        content = {"files": files, "datasets": [], "documents": {"path": saved["path"]}}
        return self.manifest(content)

    def manifest(self, content):
        raw = json.dumps(content, sort_keys=True).encode()
        release = "data-" + hashlib.sha256(raw).hexdigest()
        path = self.root / "releases" / release / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return release

    def page(self, release, **params):
        return self.client.get(
            "/api/v1/tushare-data/documents", params={"release_id": release, **params}
        )

    def test_large_history_small_page_only_reads_needed_shards(self):
        self.refs(0, 12035)
        saved, index = self.index()
        self.assertEqual(index["totals"]["mappings"], 12035)
        self.assertEqual(len(index["mappings"]), 13)
        release = self.publish(saved)
        with patch.object(api, "_artifact", wraps=api._artifact) as reads:
            response = self.page(release, offset=11998, limit=5)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            [r["observation"] for r in body["items"]],
            [f"observation-{i}" for i in range(11998, 12003)],
        )
        self.assertEqual(body["total"], 12035)
        self.assertEqual(body["next_offset"], 12003)
        # Index + two reference shards + descriptor block + state leaf.
        self.assertEqual(reads.call_count, 5)
        self.assertEqual(
            body["items"][0]["latest_result"]["fetched_at"], self.result["fetched_at"]
        )
        with patch.object(api, "_artifact", wraps=api._artifact) as reads:
            self.assertEqual(self.page(release, offset=13000).json()["items"], [])
        self.assertEqual(reads.call_count, 1)

    def test_incremental_reuses_full_ranges_and_unchanged_state(self):
        self.refs(0, 2002)
        first, a = self.index()
        again, same = self.index()
        self.assertEqual(first["path"], again["path"])
        self.assertEqual(again["rebuilt_shards"], 0)
        self.assertEqual(a, same)
        self.refs(2002, 1)
        second, b = self.index()
        self.assertEqual(second["rebuilt_shards"], 1)
        self.assertEqual(a["mappings"][:2], b["mappings"][:2])
        self.assertNotEqual(a["mappings"][-1]["path"], b["mappings"][-1]["path"])
        self.assertEqual(a["states"], b["states"])
        new_paths = {f["path"] for f in second["files"]} - {
            f["path"] for f in first["files"]
        }
        self.assertEqual(len(new_paths), 2)  # Only tail shard and compact index.
        for item in first["files"]:
            self.assertTrue((self.root / item["path"]).is_file())

    def test_state_retry_changes_only_bucket_and_attempt_tail(self):
        other = sha("unrelated-document")
        self.assertNotEqual(other[:2], self.doc[:2])
        self.db.execute(
            "INSERT INTO documents(id,observation,url) VALUES(?,?,?)",
            (other, "other-observation", "https://example.com/2"),
        )
        self.db.commit()
        self.refs(0, 1002)
        self.attempt("download", self.result, 101.5)
        old, old_index = self.index()
        old_release = self.publish(old)
        updated = {**self.result, "parse_status": "parsed"}
        self.db.execute(
            "UPDATE documents SET parse_status='parsed',parse_tries=2,result=? WHERE id=?",
            (json.dumps(updated), self.doc),
        )
        self.db.commit()
        self.attempt("parse", updated, 202.5)
        latest, current = self.index()
        self.assertEqual(latest["rebuilt_shards"], 2)
        self.assertEqual(old_index["mappings"], current["mappings"])
        self.assertEqual(
            old_index["states"][other[:1]],
            current["states"][other[:1]],
        )
        self.assertNotEqual(
            old_index["states"][self.doc[:1]]["path"],
            current["states"][self.doc[:1]]["path"],
        )
        release = self.publish(latest)
        row = self.page(release, limit=1).json()["items"][0]
        self.assertEqual(row["parse_status"], "parsed")
        self.assertEqual(row["parse_tries"], 2)
        self.assertEqual(row["validation_observation"], "original-observation")
        self.assertEqual(row["latest_result"]["fetched_at"], self.result["fetched_at"])
        attempts = self.page(release, view="attempts").json()["items"]
        self.assertEqual([r["created_at"] for r in attempts], [101.5, 202.5])
        self.assertEqual([r["phase"] for r in attempts], ["download", "parse"])
        self.assertEqual(
            self.page(old_release, limit=1).json()["items"][0]["parse_status"],
            "parse_failed",
        )

    def test_old_v1_inventory_stays_readable_and_queue_schema_compatible(self):
        self.refs(0, 3)
        old = docs.document_inventory(self.root)
        saved = docs._save(
            self.root, "documents", ".json", docs._json(old), "application/json"
        )
        release = self.publish({**saved, "files": [*old["files"], saved]})
        page = self.page(release, offset=1, limit=1).json()
        self.assertEqual(page["items"], old["mappings"][1:2])
        self.assertEqual(page["next_offset"], 2)
        self.index()
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(
            docs.document_inventory(self.root)["mappings"], old["mappings"]
        )
        # Existing writer connections use the triggers without loading new Python.
        self.refs(3, 1)
        self.assertEqual(self.index()[0]["rebuilt_shards"], 1)

    def test_shard_hash_path_membership_and_symlinks_are_rejected(self):
        self.refs(0, 2)
        saved, index = self.index()
        release = self.publish(saved)
        shard = self.root / index["mappings"][0]["path"]
        raw = shard.read_bytes()
        shard.write_bytes(b"x" * len(raw))
        self.assertEqual(self.page(release).status_code, 409)
        shard.unlink()
        outside = self.root / "outside.json"
        outside.write_bytes(raw)
        shard.symlink_to(outside)
        self.assertEqual(self.page(release).status_code, 409)
        shard.unlink()
        shard.write_bytes(raw)
        for bad_path in (
            "../outside.json",
            "attachments/" + "0" * 64 + ".html",
            "documents/" + "0" * 64 + ".json",
        ):
            changed = json.loads(json.dumps(index))
            changed["mappings"][0]["path"] = bad_path
            item = docs._save(
                self.root, "documents", ".json", docs._json(changed), "application/json"
            )
            bad_release = self.publish({**item, "files": [*saved["files"], item]})
            self.assertEqual(self.page(bad_release).status_code, 409)

    def test_interruption_keeps_dirty_work_and_orphan_originals(self):
        self.refs(0, 1002)
        saved, _ = self.index()
        self.refs(1002, 1)
        orphan = docs._save(
            self.root,
            "extracted",
            ".json",
            b'{"parse_status":"no_text","pages":[]}',
            "application/json",
        )
        with patch.object(docs, "_save", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                self.index()
        recovered, index = self.index()
        self.assertEqual(index["totals"]["mappings"], 1003)
        self.assertIn(orphan["path"], [r["path"] for r in recovered["files"]])
        release = self.publish(recovered)
        self.assertEqual(self.page(release, view="files").json()["total"], 2)
        self.assertTrue((self.root / saved["path"]).is_file())
        self.db.execute("UPDATE document_refs SET status='updated' WHERE rowid=1")
        self.db.commit()
        self.assertEqual(self.index()[0]["rebuilt_shards"], 1)


if __name__ == "__main__":
    unittest.main()
