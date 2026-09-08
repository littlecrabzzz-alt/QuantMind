"""Immutable manifest aliases and versioned state shards, temporary fixtures only."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_archive as archive
from backend.shared import tushare_documents as docs
import test_tushare_document_index as index_tests
from test_tushare_document_index import api, sha


class StateBuckets(unittest.TestCase):
    setUp = index_tests.DocumentIndex.setUp
    tearDown = index_tests.DocumentIndex.tearDown
    refs = index_tests.DocumentIndex.refs
    index = index_tests.DocumentIndex.index
    publish = index_tests.DocumentIndex.publish
    manifest = index_tests.DocumentIndex.manifest
    page = index_tests.DocumentIndex.page

    def legacy(self):
        """Construct the exact old two-prefix cache/trigger shape and fixed index."""
        saved, index = self.index()
        old = json.loads(json.dumps(index))
        old.pop("state_prefix_chars")
        old["states"] = {}
        files = list(saved["files"])
        grouped = {}
        for row in self.db.execute("SELECT * FROM documents ORDER BY id"):
            item = dict(row)
            item["result"] = json.loads(item["result"])
            grouped.setdefault(item["id"][:2], []).append(item)
        with self.db:
            for op in ("insert", "update", "delete"):
                self.db.execute(f"DROP TRIGGER document_index_states_{op}")
            self.db.execute("DROP INDEX document_index_state_bucket")
            self.db.execute("DELETE FROM document_index_cache WHERE kind='states'")
            for bucket, items in grouped.items():
                part = docs._save(
                    self.root,
                    "documents",
                    ".json",
                    docs._json(
                        {
                            "schema_version": 2,
                            "kind": "states",
                            "bucket": bucket,
                            "items": items,
                        }
                    ),
                    "application/json",
                )
                descriptor = {**part, "bucket": bucket, "count": len(items)}
                files.append(part)
                old["states"][bucket] = descriptor
                self.db.execute(
                    "INSERT INTO document_index_cache VALUES('states',?,?)",
                    (bucket, json.dumps(descriptor)),
                )
            for op, rows in (
                ("INSERT", ("NEW",)),
                ("UPDATE", ("OLD", "NEW")),
                ("DELETE", ("OLD",)),
            ):
                statements = ";".join(
                    "INSERT OR IGNORE INTO document_index_dirty VALUES('states',substr("
                    + r
                    + ".id,1,2))"
                    for r in rows
                )
                self.db.execute(
                    f"CREATE TRIGGER document_index_states_{op.lower()} AFTER {op} ON documents BEGIN {statements}; END"
                )
            self.db.execute(
                "CREATE INDEX document_index_state_bucket ON documents(substr(id,1,2))"
            )
            self.db.execute("UPDATE document_index_meta SET version=1")
        part = docs._save(
            self.root, "documents", ".json", docs._json(old), "application/json"
        )
        files.append(part)
        return {**part, "files": files}, old

    def test_old_fixed_index_new_prefix_and_current_only_fresh_mac(self):
        self.refs(0, 1003)
        saved, old = self.legacy()
        old_release = self.publish(saved)
        first = self.page(old_release, offset=999, limit=3).json()
        self.assertEqual(len(first["items"]), 3)
        modern, index = self.index()
        new_release = self.publish(modern)
        self.assertEqual(index["state_prefix_chars"], 3)
        self.assertEqual(index["mappings"], old["mappings"])
        self.assertEqual(index["attempts"], old["attempts"])
        self.assertEqual(
            first["items"], self.page(new_release, offset=999, limit=3).json()["items"]
        )
        archive.retain_release(self.root, old_release)
        content = json.loads(
            (self.root / f"releases/{new_release}/manifest.json").read_bytes()
        )
        for item in saved["files"]:
            content["files"][item["path"]] = {k: item[k] for k in ("sha256", "bytes")}
        old_archive = f"archives/{old_release[5:]}.json"
        content["files"][old_archive] = {
            "sha256": old_release[5:],
            "bytes": (self.root / old_archive).stat().st_size,
        }
        current = self.manifest(content)
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp).resolve()
            for relative in list(content["files"]) + [
                f"releases/{current}/manifest.json"
            ]:
                target = fresh / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / relative, target)
            (fresh / "CURRENT.json").write_text(
                json.dumps({"release_id": current, "manifest_sha256": current[5:]})
            )
            with patch.object(api, "ROOT", fresh):
                self.assertEqual(self.page(old_release, limit=1).status_code, 200)
                self.assertEqual(self.page(current, limit=1).status_code, 200)
                response = self.client.get(
                    "/api/v1/tushare-data/documents/text",
                    params={"release_id": old_release, "path": self.original["path"]},
                )
                self.assertEqual(response.status_code, 200)
        self.assertTrue((self.root / saved["path"]).exists())

    def test_migration_and_dirty_shard_interruptions_resume(self):
        self.refs(0, 1)
        saved, _ = self.legacy()
        with patch.object(
            docs, "_state_index_triggers", side_effect=RuntimeError("migration crash")
        ):
            with self.assertRaises(RuntimeError):
                self.index()
        self.assertEqual(
            self.db.execute("SELECT version FROM document_index_meta").fetchone()[0], 1
        )
        self.assertTrue(
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='document_index_states_insert'"
            ).fetchone()
        )
        with patch.object(docs, "_save", side_effect=OSError("shard crash")):
            with self.assertRaises(OSError):
                self.index()
        recovered, index = self.index()
        self.assertEqual(index["state_prefix_chars"], 3)
        self.assertGreater(recovered["rebuilt_shards"], 0)
        self.assertEqual(self.index()[0]["rebuilt_shards"], 0)
        self.assertTrue((self.root / saved["path"]).exists())

    def test_large_append_and_single_update_bound_rewrites(self):
        def insert(start, stop):
            self.db.executemany(
                "INSERT INTO documents(id,observation,url) VALUES(?,?,?)",
                (
                    (sha(str(i)), str(i), f"https://example.com/{i}")
                    for i in range(start, stop)
                ),
            )
            self.db.commit()

        insert(0, 20000)
        _, old = self.index()
        insert(20000, 21000)
        saved, new = self.index()
        changed = {
            b for b, item in new["states"].items() if old["states"].get(b) != item
        }
        expected = {sha(str(i))[:3] for i in range(20000, 21000)}
        self.assertEqual(changed, expected)
        self.assertEqual(saved["rebuilt_shards"], len(expected))
        changed_rows = sum(new["states"][b]["count"] for b in changed)
        self.assertLess(changed_rows, 7000)
        self.db.execute("UPDATE documents SET download_tries=1 WHERE id=?", (sha("1"),))
        self.db.commit()
        updated, latest = self.index()
        self.assertEqual(updated["rebuilt_shards"], 1)
        self.assertEqual(
            {
                b
                for b in latest["states"]
                if latest["states"][b] != new["states"].get(b)
            },
            {sha("1")[:3]},
        )
        self.assertEqual(self.index()[0]["rebuilt_shards"], 0)


if __name__ == "__main__":
    unittest.main()
