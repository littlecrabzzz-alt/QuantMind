#!/usr/bin/env python3
"""Offline recovery fixtures: no credentials, upstream calls or production files."""

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend.shared.tushare_archive as archive  # noqa: E402


def hashed(root, directory, raw, suffix="json"):
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"{directory}/{digest}.{suffix}"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return relative, {"sha256": digest, "bytes": len(raw)}


def observed(root, n):
    obj, meta = hashed(root, "objects", json.dumps({"rows": [n]}).encode())
    raw = json.dumps(
        {
            "object_sha256": meta["sha256"],
            "request": {"api_name": "daily"},
            "fetched_at": "2026-01-01T00:00:00Z",
        }
    ).encode()
    relative = f"observations/{n:032x}.json"
    (root / "observations").mkdir(exist_ok=True)
    (root / relative).write_bytes(raw)
    result = {
        "api_name": "daily",
        "observation": Path(relative).name,
        "observation_sha256": hashlib.sha256(raw).hexdigest(),
        "object_sha256": meta["sha256"],
        "status": "sample_ok",
    }
    return obj, relative, result


def manifest(root, body, probe=False):
    # Pretty raw bytes deliberately differ from canonical publisher JSON.
    raw = json.dumps(body, indent=3, ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    release = "probe-" + "a" * 32 if probe else "data-" + digest
    path = root / "releases" / release / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return release, raw


def finish(root, budget=3):
    for _ in range(500):
        progress = archive.recover_archive(root, max_items=budget, max_seconds=2)
        if progress["status"] != "recovering":
            return archive.archive_inventory(root)
    raise AssertionError("Recovery did not terminate")


class ArchiveRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network in recovery"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_probe_twenty_files_resume_and_exact_manifest_bytes(self):
        results, expected = [], set()
        for n in range(1, 11):
            obj, obs, result = observed(self.root, n)
            expected.update((obj, obs))
            results.append(result)
        release, raw = manifest(self.root, {"results": results}, probe=True)
        initial = archive.recover_archive(self.root, max_items=1)
        self.assertEqual(initial["processed"], 1)
        self.assertEqual(initial["status"], "recovering")
        inventory = finish(self.root)
        self.assertLessEqual(expected, set(inventory["files"]))
        self.assertEqual(len(inventory["files"]), 21)
        self.assertEqual(inventory["datasets"], [])
        archived = inventory["recovery"]["archived_releases"]
        self.assertEqual(archived[0]["release_id"], release)
        self.assertEqual((self.root / archived[0]["path"]).read_bytes(), raw)
        self.assertFalse(inventory["recovery"]["historical_complete"])
        before = json.dumps(inventory, sort_keys=True)
        # Completion must not read or enumerate old manifests/files again.
        with (
            patch.object(
                Path, "iterdir", side_effect=AssertionError("Unexpected rescan")
            ),
            patch.object(
                Path, "read_bytes", side_effect=AssertionError("Unexpected reread")
            ),
        ):
            progress = archive.recover_archive(self.root)
            self.assertEqual(progress["processed"], 0)
            self.assertEqual(
                json.dumps(archive.archive_inventory(self.root), sort_keys=True), before
            )

    def test_old_release_versions_and_orphan_evidence_survive(self):
        known = set()
        for n in (1, 2):
            path, meta = hashed(
                self.root, "parquet", f"PAR1fixture-{n}".encode(), "parquet"
            )
            known.add(path)
            manifest(
                self.root,
                {
                    "files": {path: meta},
                    "datasets": [
                        {
                            "api_name": "daily",
                            "path": path,
                            "quality_state": "sample_ok",
                            **meta,
                        }
                    ],
                },
            )
        orphan, _ = hashed(self.root, "parquet", b"PAR1no-release-reference", "parquet")
        obj, obs, _ = observed(
            self.root, 9
        )  # Captured before a jobs commit, no release.
        attachment, _ = hashed(self.root, "attachments", b"%PDF-evidence", "pdf")
        extraction, _ = hashed(self.root, "extracted", b'{"text":"saved original"}')
        inventory = finish(self.root)
        self.assertEqual({d["path"] for d in inventory["datasets"]}, known)
        self.assertLessEqual(
            {orphan, obj, obs, attachment, extraction}, set(inventory["files"])
        )
        self.assertNotIn(orphan, {d["path"] for d in inventory["datasets"]})
        self.assertEqual(len(inventory["recovery"]["archived_releases"]), 2)
        self.assertFalse(inventory["gaps"])

    def test_bad_references_missing_files_escape_and_corruption_are_persistent(self):
        good, meta = hashed(self.root, "parquet", b"PAR1good", "parquet")
        corrupt = "objects/" + "c" * 64 + ".json"
        (self.root / "objects").mkdir(exist_ok=True)
        (self.root / corrupt).write_bytes(b"wrong content")
        missing = "objects/" + "d" * 64 + ".json"
        manifest(
            self.root,
            {
                "files": {
                    good: {**meta, "sha256": "e" * 64},
                    "../outside.json": {"sha256": "0" * 64, "bytes": 10},
                    missing: {"sha256": "d" * 64, "bytes": 10},
                },
                "datasets": [],
            },
        )
        inventory = finish(self.root)
        reasons = {g["reason"] for g in inventory["gaps"]}
        self.assertLessEqual(
            {
                "referenced_file_mismatch",
                "invalid_immutable_path",
                "FileNotFoundError",
                "filename_checksum_mismatch",
            },
            reasons,
        )
        self.assertEqual(inventory["recovery"]["status"], "complete_with_gaps")
        self.assertNotIn(corrupt, inventory["files"])
        self.assertNotIn(missing, inventory["files"])
        self.assertNotIn("../outside.json", inventory["files"])
        self.assertIn(
            good, inventory["files"]
        )  # Independently verified loose evidence.
        self.assertEqual(archive.archive_inventory(self.root), inventory)

    def test_interruption_rolls_back_current_task_and_explicit_rescan_finds_new_files(
        self,
    ):
        for n in range(3):
            hashed(self.root, "attachments", f"saved{n}".encode(), "html")
        real = archive._file
        calls = 0

        def interrupted(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return real(*args)

        with patch.object(archive, "_file", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                archive.recover_archive(self.root)
        progress = archive.archive_inventory(self.root)["recovery"]
        self.assertEqual(progress["files"], 1)
        self.assertEqual(progress["remaining"], 2)
        self.assertEqual(len(finish(self.root)["files"]), 3)
        later, _ = hashed(
            self.root, "attachments", b"captured after frozen snapshot", "html"
        )
        self.assertEqual(archive.recover_archive(self.root)["processed"], 0)
        self.assertNotIn(later, archive.archive_inventory(self.root)["files"])
        archive.recover_archive(self.root, max_items=1, rescan=True)
        inventory = finish(self.root)
        self.assertIn(later, inventory["files"])
        self.assertEqual(inventory["recovery"]["scan_count"], 2)

    def test_shared_artifacts_hash_once_per_scan_and_bad_manifest_is_not_trusted(self):
        path, metadata = hashed(self.root, "attachments", b"shared evidence", "html")
        for n in range(10):
            manifest(
                self.root, {"files": {path: metadata}, "datasets": [], "revision": n}
            )
        broken, _ = manifest(
            self.root, {"files": {}, "datasets": [], "revision": "broken"}
        )
        (self.root / "releases" / broken / "manifest.json").write_bytes(
            b"modified behind immutable release id"
        )
        calls = []
        original = archive._fingerprint

        def counted(target, deadline):
            calls.append(str(target.relative_to(self.root)))
            return original(target, deadline)

        with patch.object(archive, "_fingerprint", side_effect=counted):
            inventory = finish(self.root)
        self.assertEqual(calls.count(path), 1)
        self.assertEqual(len(inventory["recovery"]["archived_releases"]), 10)
        self.assertIn(
            "manifest_checksum_mismatch", {g["reason"] for g in inventory["gaps"]}
        )
        self.assertNotIn(
            broken,
            {r["release_id"] for r in inventory["recovery"]["archived_releases"]},
        )
        # Schema and snapshot creation are separate durable steps; inventory is
        # still readable if initialization was interrupted before freezing inputs.
        with tempfile.TemporaryDirectory() as unstarted:
            db = archive._db(Path(unstarted))
            db.close()
            self.assertEqual(
                archive.archive_inventory(unstarted)["recovery"]["status"],
                "not_started",
            )

    def test_symlinks_are_not_followed_and_rescan_resolves_missing_reference(self):
        external = self.root / "outside"
        external.write_bytes(b"do not read through link")
        directory = self.root / "attachments"
        directory.mkdir()
        link = directory / (hashlib.sha256(external.read_bytes()).hexdigest() + ".html")
        link.symlink_to(external)
        raw = b"arrives later"
        sha = hashlib.sha256(raw).hexdigest()
        path = f"attachments/{sha}.html"
        manifest(
            self.root,
            {"files": {path: {"sha256": sha, "bytes": len(raw)}}, "datasets": []},
        )
        inventory = finish(self.root)
        self.assertIn("symlink", {g["reason"] for g in inventory["gaps"]})
        self.assertNotIn("attachments/" + link.name, inventory["files"])
        (self.root / path).write_bytes(raw)
        archive.recover_archive(self.root, rescan=True)
        inventory = finish(self.root)
        self.assertIn(path, inventory["files"])
        self.assertFalse(any(g["path"] == path for g in inventory["gaps"]))
        with sqlite3.connect(self.root / "archive.sqlite") as db:
            self.assertGreater(
                db.execute("SELECT COUNT(*) FROM gaps WHERE resolved=1").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
