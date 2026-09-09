"""Pinned manifest transport failures never publish an incomplete local release."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tushare_mirror as mirror


class ManifestTransfer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "client"
        self.root.mkdir()
        self.project = self.base / "project"
        (self.project / "deploy").mkdir(parents=True)
        (self.project / "deploy/dual-node.env").write_text(
            "QM_SSH_TARGET=fixture\nQM_REMOTE_PROJECT=/source\n"
        )
        self.body = b"all retained object and attachment bytes"
        self.object = "objects/" + hashlib.sha256(self.body).hexdigest() + ".json"
        self.attachment = (
            "attachments/" + hashlib.sha256(self.body).hexdigest() + ".pdf"
        )
        self.raw = json.dumps(
            {
                "files": {
                    p: {
                        "sha256": hashlib.sha256(self.body).hexdigest(),
                        "bytes": len(self.body),
                    }
                    for p in (self.object, self.attachment)
                },
                "datasets": [],
                "coverage": {},
            }
        ).encode()
        sha = hashlib.sha256(self.raw).hexdigest()
        self.release = "data-" + sha
        self.relative = "releases/" + self.release + "/manifest.json"
        self.pointer = {"release_id": self.release, "manifest_sha256": sha}
        self.before = b'{"release_id":"previous-fixed-version"}'
        (self.root / "CURRENT.json").write_bytes(self.before)
        self.calls = []
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline fixture"))
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(mirror, "PROJECT", self.project)
        guard.start()
        self.addCleanup(guard.stop)

    def pointer_fetch(self, cmd, **kwargs):
        self.assertEqual(kwargs["timeout"], 30)
        self.assertTrue(cmd[-1].endswith("CURRENT.json"))
        return json.dumps(self.pointer).encode()

    def transfer(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        self.assertIn("-az", cmd)
        self.assertIn("--compress-level=3", cmd)
        self.assertIn("--timeout=45", cmd)
        listing = next(v.split("=", 1)[1] for v in cmd if v.startswith("--files-from="))
        names = Path(listing).read_text().splitlines()
        if names == [self.relative]:
            self.assertEqual(kwargs["timeout"], 180)
            self.assertTrue(kwargs["capture_output"])
        for name in names:
            target = Path(cmd[-1]) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.raw if name == self.relative else self.body)

    def run_mirror(self, transfer=None):
        with (
            patch.object(
                mirror.subprocess, "check_output", side_effect=self.pointer_fetch
            ),
            patch.object(
                mirror.subprocess, "run", side_effect=transfer or self.transfer
            ),
        ):
            return mirror.mirror(self.root)

    def test_compressed_fixed_manifest_then_complete_objects_and_noop(self):
        result = self.run_mirror()
        self.assertEqual(result["downloaded_files"], 2)
        self.assertEqual(
            json.loads((self.root / "CURRENT.json").read_bytes()), self.pointer
        )
        self.assertEqual((self.root / self.object).read_bytes(), self.body)
        self.assertEqual((self.root / self.attachment).read_bytes(), self.body)
        self.assertEqual(len(self.calls), 2)
        inode = (self.root / self.relative).stat().st_ino
        again = self.run_mirror()
        self.assertEqual(again["downloaded_files"], 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual((self.root / self.relative).stat().st_ino, inode)
        self.assertEqual(list(self.root.glob(".manifest-*")), [])

    def test_partial_timeout_stage_keeps_current_and_retry_recovers(self):
        def fail(cmd, **kwargs):
            incoming = Path(cmd[-1]) / self.relative
            incoming.parent.mkdir(parents=True)
            incoming.write_bytes(self.raw[:12])
            raise subprocess.TimeoutExpired(
                ["secret-host", "secret-token"], 180, output=b"secret", stderr=b"secret"
            )

        with self.assertRaises(subprocess.TimeoutExpired) as error:
            self.run_mirror(fail)
        report = mirror.failure_report(error.exception)
        self.assertEqual(report["stage"], "manifest_transfer")
        self.assertEqual(report["timeout_seconds"], 180)
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.before)
        self.assertFalse((self.root / self.relative).exists())
        self.assertEqual(list(self.root.glob(".manifest-*")), [])
        self.assertEqual(self.run_mirror()["status"], "verified")

    def test_wrong_sha_and_symlink_never_install_or_advance(self):
        for attack in ("wrong_sha", "symlink"):

            def corrupt(cmd, attack=attack, **kwargs):
                incoming = Path(cmd[-1]) / self.relative
                incoming.parent.mkdir(parents=True)
                if attack == "wrong_sha":
                    incoming.write_bytes(b"wrong")
                else:
                    outside = self.base / "external"
                    outside.write_bytes(self.raw)
                    incoming.symlink_to(outside)

            with self.assertRaises(ValueError):
                self.run_mirror(corrupt)
            self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.before)
            self.assertFalse((self.root / self.relative).exists())

    def test_archive_reuse_and_existing_manifest_checksum_are_mandatory(self):
        archive = self.root / "archives" / f"{self.release[5:]}.json"
        archive.parent.mkdir()
        archive.write_bytes(self.raw)
        result = self.run_mirror()
        self.assertEqual(result["downloaded_files"], 2)
        self.assertEqual(len(self.calls), 1)  # only object and attachment transfer
        self.assertEqual(
            archive.stat().st_ino, (self.root / self.relative).stat().st_ino
        )
        current = (self.root / "CURRENT.json").read_bytes()
        archive.write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            self.run_mirror()
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), current)

    def test_object_failure_retains_fixed_manifest_but_not_current(self):
        def fail_objects(cmd, **kwargs):
            if kwargs.get("timeout") == 180:
                return self.transfer(cmd, **kwargs)
            raise subprocess.CalledProcessError(
                23, ["secret-command"], stderr=b"secret"
            )

        with self.assertRaises(subprocess.CalledProcessError) as error:
            self.run_mirror(fail_objects)
        self.assertEqual(
            mirror.failure_report(error.exception)["stage"], "objects_transfer"
        )
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.before)
        self.assertEqual((self.root / self.relative).read_bytes(), self.raw)
        self.assertEqual(self.run_mirror()["status"], "verified")

    def test_pointer_timeout_is_distinguished_and_invalid_identity_rejected(self):
        with patch.object(
            mirror.subprocess,
            "check_output",
            side_effect=subprocess.TimeoutExpired(["secret"], 30),
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as error:
                mirror.mirror(self.root)
        self.assertEqual(
            mirror.failure_report(error.exception)["stage"], "pointer_fetch"
        )
        for release, sha in (("../escape", "0" * 64), (self.release, "0" * 64)):
            self.pointer = {"release_id": release, "manifest_sha256": sha}
            with self.assertRaises(ValueError):
                self.run_mirror()
        self.assertFalse(self.calls)
        self.assertEqual((self.root / "CURRENT.json").read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
