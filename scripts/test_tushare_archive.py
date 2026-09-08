#!/usr/bin/env python3
"""Offline recovery fixtures: no credentials, upstream calls or production files."""

from contextlib import closing
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

    def test_incremental_release_closure_reaches_fresh_mirror(self):
        import shutil

        data, metadata = hashed(
            self.root, "attachments", b"original binary error body", "bin"
        )
        seed, seed_raw = manifest(
            self.root, {"files": [{"path": data, **metadata}]}, probe=True
        )
        finish(self.root)
        retained_seed = archive.retain_release(self.root, seed)
        first, first_raw = manifest(
            self.root, {"files": retained_seed["files"], "datasets": [], "revision": 1}
        )
        # First frozen scan cannot discover the later releases. Explicit retain
        # does not enumerate any directory or hash their inherited object files.
        with (
            patch.object(Path, "iterdir", side_effect=AssertionError("tree scan")),
            patch.object(
                archive, "_fingerprint", side_effect=AssertionError("object rehash")
            ),
        ):
            retained_first = archive.retain_release(self.root, first)
            second, second_raw = manifest(
                self.root,
                {"files": retained_first["files"], "datasets": [], "revision": 2},
            )
            retained_second = archive.retain_release(self.root, second)
        current, current_raw = manifest(
            self.root,
            {
                "files": retained_second["files"],
                "datasets": [],
                "archive": {
                    "recovery": {
                        "archived_releases": retained_second["archived_releases"]
                    }
                },
            },
        )
        self.assertEqual(
            {r["release_id"] for r in retained_second["archived_releases"]},
            {seed, first, second},
        )
        with tempfile.TemporaryDirectory() as target:
            mirror = Path(target)
            dest = mirror / "releases" / current / "manifest.json"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(current_raw)
            # Exactly the CURRENT manifest file list is available on a new Mac.
            for name, expected in json.loads(current_raw)["files"].items():
                source = self.root / name
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(), expected["sha256"]
                )
                (mirror / name).parent.mkdir(exist_ok=True)
                shutil.copyfile(source, mirror / name)
            for release, raw in (
                (seed, seed_raw),
                (first, first_raw),
                (second, second_raw),
            ):
                mapping = next(
                    r
                    for r in retained_second["archived_releases"]
                    if r["release_id"] == release
                )
                archived = (mirror / mapping["path"]).read_bytes()
                self.assertEqual(archived, raw)
                self.assertEqual(
                    hashlib.sha256(archived).hexdigest(), mapping["sha256"]
                )
                if release.startswith("data-"):
                    self.assertEqual(
                        mapping["path"], "archives/" + release[5:] + ".json"
                    )
            self.assertFalse((mirror / "archive.sqlite").exists())

    def test_legacy_frozen_scan_gets_only_one_release_directory_catchup(self):
        finish(self.root)
        with closing(sqlite3.connect(self.root / "archive.sqlite")) as db, db:
            db.execute("DELETE FROM meta WHERE key='release_catchup'")
        late, _ = manifest(self.root, {"files": {}, "datasets": [], "later": True})
        original = Path.iterdir
        seen = []

        def only_releases(path):
            seen.append(path.name)
            self.assertEqual(path, self.root / "releases")
            return original(path)

        with patch.object(Path, "iterdir", only_releases):
            inventory = finish(self.root)
            finish(self.root)
        self.assertEqual(seen, ["releases"])
        self.assertIn(
            late, {r["release_id"] for r in inventory["recovery"]["archived_releases"]}
        )
        later, _ = manifest(self.root, {"files": {}, "datasets": [], "later": 2})
        with patch.object(Path, "iterdir", only_releases):
            archive.recover_archive(self.root, max_items=1, rescan_releases=True)
            inventory = finish(self.root)
        self.assertIn(
            later, {r["release_id"] for r in inventory["recovery"]["archived_releases"]}
        )
        self.assertEqual(inventory["recovery"]["scan_count"], 1)

    def test_release_directory_catchup_interruption_restarts_membership_atomically(
        self,
    ):
        finish(self.root)
        with closing(sqlite3.connect(self.root / "archive.sqlite")) as db, db:
            db.execute("DELETE FROM meta WHERE key='release_catchup'")
        expected = {
            manifest(self.root, {"files": {}, "datasets": [], "n": n})[0]
            for n in range(3)
        }
        original = archive._task
        calls = 0

        def interrupted(*args, **kwargs):
            nonlocal calls
            original(*args, **kwargs)
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt

        with patch.object(archive, "_task", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                archive.recover_archive(self.root)
        with closing(sqlite3.connect(self.root / "archive.sqlite")) as db:
            self.assertIsNone(
                db.execute(
                    "SELECT value FROM meta WHERE key='release_catchup'"
                ).fetchone()
            )
        inventory = finish(self.root, budget=1)
        self.assertEqual(
            {r["release_id"] for r in inventory["recovery"]["archived_releases"]},
            expected,
        )

    def test_retention_interrupt_after_copy_resumes_without_losing_original(self):
        release, raw = manifest(self.root, {"files": {}, "datasets": []})
        real = archive._register
        with patch.object(archive, "_register", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                archive.retain_release(self.root, release)
        expected = self.root / "archives" / (hashlib.sha256(raw).hexdigest() + ".json")
        self.assertEqual(expected.read_bytes(), raw)
        with patch.object(archive, "_register", wraps=real):
            first = archive.retain_release(self.root, release)
        self.assertEqual(first, archive.retain_release(self.root, release))
        self.assertEqual(len(first["archived_releases"]), 1)
        self.assertEqual(
            (self.root / "releases" / release / "manifest.json").read_bytes(), raw
        )

    def test_missing_and_same_size_tamper_are_not_claimed_verified(self):
        path, metadata = hashed(self.root, "attachments", b"original", "bin")
        release, raw = manifest(self.root, {"files": {path: metadata}, "datasets": []})
        (self.root / path).unlink()
        retained = archive.retain_release(self.root, release)
        self.assertEqual(
            retained["verification"], "manifest_verified_references_expected"
        )
        self.assertNotIn(path, archive.archive_inventory(self.root)["files"])
        missing = finish(self.root)
        self.assertIn("FileNotFoundError", {g["reason"] for g in missing["gaps"]})
        (self.root / path).write_bytes(b"tampered")
        archive.recover_archive(self.root, rescan=True)
        damaged = finish(self.root)
        self.assertIn(
            "filename_checksum_mismatch", {g["reason"] for g in damaged["gaps"]}
        )
        self.assertNotIn(path, damaged["files"])
        (self.root / "releases" / release / "manifest.json").write_bytes(
            raw.replace(b"files", b"fakes")
        )
        with self.assertRaisesRegex(archive.ArchiveError, "manifest_checksum_mismatch"):
            archive.retain_release(self.root, release)

    def test_legacy_identity_conflicts_and_unknown_file_metadata_remain_explicit(self):
        path, _ = hashed(self.root, "attachments", b"legacy bytes", "bin")
        seed, _ = manifest(self.root, {"files": [path]}, probe=True)
        first = archive.retain_release(self.root, seed)
        inventory = finish(self.root)
        self.assertIn(
            "legacy_file_metadata_observed_without_manifest_anchor",
            {g["reason"] for g in inventory["gaps"]},
        )
        self.assertIn(path, inventory["files"])
        manifest(self.root, {"files": [path], "changed": True}, probe=True)
        with self.assertRaisesRegex(archive.ArchiveError, "immutable_release_conflict"):
            archive.retain_release(self.root, seed)
        self.assertEqual(
            first["archived_releases"],
            archive.archive_inventory(self.root)["recovery"]["archived_releases"],
        )

    def test_retention_rejects_symlinks_bad_metadata_and_non_attachment_bin(self):
        for badpath in (
            "../escape.json",
            "objects/" + "a" * 64 + ".bin",
            "extracted/" + "a" * 64 + ".bin",
        ):
            release, _ = manifest(
                self.root,
                {"files": {badpath: {"sha256": "a" * 64, "bytes": 0}}, "datasets": []},
            )
            with self.assertRaisesRegex(archive.ArchiveError, "invalid_immutable_path"):
                archive.retain_release(self.root, release)
        release, _ = manifest(self.root, {"files": {}, "datasets": []})
        path = self.root / "releases" / release / "manifest.json"
        original = self.root / "original.json"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaisesRegex(archive.ArchiveError, "symlink"):
            archive.retain_release(self.root, release)

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
        with closing(sqlite3.connect(self.root / "archive.sqlite")) as db, db:
            self.assertGreater(
                db.execute("SELECT COUNT(*) FROM gaps WHERE resolved=1").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
