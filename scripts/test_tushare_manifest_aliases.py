"""Immutable manifest aliases and versioned state shards, temporary fixtures only."""

import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.shared import tushare_archive as archive
from backend.shared.tushare_pipeline import manifest_at
from scripts import tushare_mirror as mirror_module
from test_tushare_archive import manifest


class ManifestAliases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.release, self.raw = manifest(self.root, {"files": {}, "datasets": []})
        self.source = f"releases/{self.release}/manifest.json"
        self.target = f"archives/{self.release[5:]}.json"
        self.expected = {"sha256": self.release[5:], "bytes": len(self.raw)}
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline"))
            guard.start()
            self.addCleanup(guard.stop)

    def link(self):
        return archive.link_manifest_alias(
            self.root, self.source, self.target, self.expected
        )

    def test_new_retention_links_exact_bytes_and_idempotence(self):
        first = archive.retain_release(self.root, self.release)
        self.assertTrue(
            os.path.samefile(self.root / self.source, self.root / self.target)
        )
        again = archive.retain_release(self.root, self.release)
        self.assertEqual(first, again)
        self.assertEqual((self.root / self.target).read_bytes(), self.raw)
        self.assertEqual(manifest_at(self.root, self.release)["files"], {})
        release, raw = manifest(self.root, {"files": []}, probe=True)
        archive.retain_release(self.root, release)
        self.assertTrue(
            os.path.samefile(
                self.root / f"releases/{release}/manifest.json",
                self.root / f"archives/{hashlib.sha256(raw).hexdigest()}.json",
            )
        )

    def test_cross_device_fallback_copies_without_changing_source(self):
        real_link = os.link

        def cross_device(source, target, **kwargs):
            if source == "manifest.json":
                raise OSError(errno.EXDEV, "synthetic cross-device")
            return real_link(source, target, **kwargs)

        with patch.object(archive.os, "link", side_effect=cross_device):
            self.assertTrue(self.link())
        self.assertFalse(
            os.path.samefile(self.root / self.source, self.root / self.target)
        )
        self.assertEqual((self.root / self.target).read_bytes(), self.raw)

    def test_matching_local_archive_can_supply_missing_release(self):
        self.link()
        (self.root / self.source).unlink()
        self.assertTrue(
            archive.link_manifest_alias(
                self.root, self.target, self.source, self.expected
            )
        )
        self.assertTrue(
            os.path.samefile(self.root / self.source, self.root / self.target)
        )

    def test_mismatch_arbitrary_paths_symlinks_and_source_swap_rejected(self):
        with self.assertRaises(ValueError):
            archive.link_manifest_alias(
                self.root, "arbitrary.json", self.target, self.expected
            )
        (self.root / self.source).write_bytes(b"x" * len(self.raw))
        with self.assertRaises(ValueError):
            self.link()
        (self.root / self.source).write_bytes(self.raw)
        real_link = os.link

        def replace_source(source, target, **kwargs):
            if source == "manifest.json":
                path = self.root / self.source
                path.unlink()
                path.symlink_to(self.root / "untrusted")
            return real_link(source, target, **kwargs)

        (self.root / "untrusted").write_bytes(self.raw)
        with patch.object(archive.os, "link", side_effect=replace_source):
            with self.assertRaises((OSError, ValueError)):
                self.link()
        self.assertFalse((self.root / self.target).exists())
        self.assertFalse(list((self.root / "archives").glob(".archive-alias-*")))
        with self.assertRaises((OSError, ValueError)):
            self.link()

    def test_existing_corrupt_target_never_overwritten_and_interruption_resumes(self):
        (self.root / "archives").mkdir()
        bad = b"x" * len(self.raw)
        (self.root / self.target).write_bytes(bad)
        with self.assertRaises(ValueError):
            self.link()
        self.assertEqual((self.root / self.target).read_bytes(), bad)
        (self.root / self.target).unlink()
        real_link = os.link

        def interrupt(source, target, **kwargs):
            if target.endswith(".json"):
                raise OSError("interrupted publication")
            return real_link(source, target, **kwargs)

        with patch.object(archive.os, "link", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.link()
        self.assertFalse((self.root / self.target).exists())
        self.assertTrue(self.link())
        self.assertEqual((self.root / self.source).read_bytes(), self.raw)

    def test_mirror_reuses_both_alias_directions_and_keeps_final_verification(self):
        original_release = self.release
        content = {
            "files": {self.target: self.expected},
            "datasets": [],
            "coverage": {},
        }
        current, raw = manifest(self.root, content)
        pointer = json.dumps(
            {"release_id": current, "manifest_sha256": current[5:]}
        ).encode()
        # The client previously fetched this release but has not seen its archive alias.
        (self.root / f"releases/{current}/manifest.json").unlink()
        project = self.root / "fixture-project"
        (project / "deploy").mkdir(parents=True)
        (project / "deploy/dual-node.env").write_text(
            "QM_SSH_TARGET=fixture\nQM_REMOTE_PROJECT=/fixture\n"
        )

        def transfer_manifest(cmd, **kwargs):
            listing = next(
                v.split("=", 1)[1] for v in cmd if v.startswith("--files-from=")
            )
            names = Path(listing).read_text().splitlines()
            self.assertEqual(names, [f"releases/{current}/manifest.json"])
            incoming = Path(cmd[-1]) / names[0]
            incoming.parent.mkdir(parents=True, exist_ok=True)
            incoming.write_bytes(raw)

        with (
            patch.object(mirror_module, "PROJECT", project),
            patch.object(
                mirror_module.subprocess,
                "check_output",
                side_effect=lambda cmd, **kwargs: (
                    pointer if "CURRENT.json" in cmd[-1] else raw
                ),
            ),
            patch.object(
                mirror_module.subprocess,
                "run",
                side_effect=transfer_manifest,
            ),
        ):
            first = mirror_module.mirror(self.root)
            self.assertEqual(first["downloaded_files"], 0)
            self.assertTrue(
                os.path.samefile(self.root / self.source, self.root / self.target)
            )
            # A known archived CURRENT supplies the absent releases alias locally.
            archive.retain_release(self.root, current)
            (self.root / f"releases/{current}/manifest.json").unlink()
            second = mirror_module.mirror(self.root)
            self.assertEqual(second["downloaded_files"], 0)
            self.assertTrue(
                os.path.samefile(
                    self.root / f"releases/{current}/manifest.json",
                    self.root / f"archives/{current[5:]}.json",
                )
            )
            self.assertEqual(manifest_at(self.root, original_release)["files"], {})
            (self.root / self.target).write_bytes(b"x" * len(self.raw))
            with self.assertRaises((ValueError, AssertionError)):
                mirror_module.mirror(self.root)


if __name__ == "__main__":
    unittest.main()
