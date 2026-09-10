"""Mocked Mac schedule installation: no launchctl, environment installs or network."""

import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tushare_mirror as mirror  # noqa: E402


class MirrorInstall(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.runtime = (
            self.home / "Library/Application Support/QuantMind/tushare-client"
        )
        self.plist = (
            self.home / "Library/LaunchAgents/com.quantmind.tushare-mirror.plist"
        )
        self.old = b"old schedule bytes"
        self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(self.old)
        self.calls = []
        self.installed = True
        self.fail = None
        self.bad_base = False
        for target, value in (
            ("scripts.tushare_mirror.Path.home", lambda: self.home),
            ("scripts.tushare_mirror.sys.platform", "darwin"),
            (
                "scripts.tushare_mirror.sys.executable",
                "/Users/fixture/.cache/uv/builds-v0/.tmp-gone/bin/python",
            ),
            ("scripts.tushare_mirror.shutil.which", lambda name: "/usr/local/bin/uv"),
        ):
            guard = patch(target, value)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch(
            "scripts.tushare_mirror.subprocess.run", side_effect=self.run_command
        )
        guard.start()
        self.addCleanup(guard.stop)
        for target in ("socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("No network"))
            guard.start()
            self.addCleanup(guard.stop)

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if "venv" in args:
            if self.fail == "venv":
                raise subprocess.CalledProcessError(1, args)
            executable = Path(args[-1]) / "bin/python"
            executable.parent.mkdir(parents=True)
            executable.write_text("fixture")
        elif "pip" in args:
            if self.fail == "pip":
                raise subprocess.CalledProcessError(1, args)
        elif "-c" in args:
            if self.fail == "health":
                raise subprocess.CalledProcessError(1, args)
            base = (
                "/Users/fixture/.cache/uv/builds-v0/.tmpdead/bin/python"
                if self.bad_base
                else "/Users/fixture/.local/share/uv/python/cpython-3.12/bin/python3.12"
            )
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"prefix": str(Path(args[0]).parent.parent), "base": base}),
            )
        elif "--help" in args:
            if self.fail == "entry":
                raise subprocess.CalledProcessError(1, args)
        elif args[0] == "launchctl":
            if args[1] == "print":
                return subprocess.CompletedProcess(args, 0 if self.installed else 1)
            if args[1] == "bootout":
                self.installed = False
            elif args[1] == "bootstrap":
                self.installed = True
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, "")

    def existing_environment(self):
        python = self.runtime / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("fixture")
        return python

    def test_new_install_uses_persistent_python_not_callers_uv_build(self):
        result = mirror.install_schedule(self.home / "unused-root")
        definition = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(result["status"], "installed")
        self.assertEqual(
            definition["ProgramArguments"][:2],
            [str(self.runtime / ".venv/bin/python"), "-I"],
        )
        self.assertNotIn(".cache/uv", json.dumps(definition))
        self.assertNotIn(".venv-install-", json.dumps(definition))
        creation = next(c for c in self.calls if "venv" in c)
        self.assertIn("--managed-python", creation)
        self.assertIn("--relocatable", creation)
        self.assertIn("--no-project", creation)
        install = next(c for c in self.calls if "pip" in c)
        self.assertEqual(install[-3:], list(mirror.CLIENT_PACKAGES))
        self.assertEqual(install[install.index("--link-mode") + 1], "copy")
        bootout = next(
            i for i, c in enumerate(self.calls) if c[:2] == ["launchctl", "bootout"]
        )
        self.assertLess(
            next(i for i, c in enumerate(self.calls) if "--help" in c), bootout
        )
        self.assertFalse(list(self.runtime.glob(".venv-install-*")))
        self.assertTrue((self.runtime / ".venv/bin/python").is_file())
        self.assertTrue(
            (
                self.runtime / "backend/shared/tushare_futures_extra_contracts.py"
            ).is_file()
        )
        self.assertTrue(
            (self.runtime / "backend/shared/tushare_rrg_contracts.py").is_file()
        )
        self.assertTrue(
            (
                self.runtime
                / "backend/shared/tushare_legacy_connect_contracts.py"
            ).is_file()
        )

    def test_existing_healthy_environment_is_offline_and_install_is_idempotent(self):
        self.existing_environment()
        with patch(
            "scripts.tushare_mirror.shutil.which",
            side_effect=AssertionError("Existing environment needs no uv"),
        ):
            mirror.install_schedule(self.home / "unused-root")
            raw = self.plist.read_bytes()
            self.calls.clear()
            result = mirror.install_schedule(self.home / "unused-root")
        self.assertEqual(result["status"], "already_installed")
        self.assertEqual(self.plist.read_bytes(), raw)
        self.assertFalse(any("venv" in c or "pip" in c for c in self.calls))
        self.assertFalse(
            any(
                c[:2] in (["launchctl", "bootout"], ["launchctl", "bootstrap"])
                for c in self.calls
            )
        )
        self.assertTrue(any("--help" in c for c in self.calls))

    def test_environment_failures_never_touch_old_schedule(self):
        for failure in ("venv", "pip", "health"):
            with self.subTest(failure=failure):
                self.fail = failure
                self.calls.clear()
                with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                    mirror.install_schedule(self.home / "unused-root")
                self.assertEqual(self.plist.read_bytes(), self.old)
                self.assertFalse(any(c[0] == "launchctl" for c in self.calls))
                self.assertFalse((self.runtime / ".venv").exists())
                self.assertFalse(list(self.runtime.glob(".venv-install-*")))

    def test_broken_existing_environment_survives_failed_rebuild(self):
        python = self.existing_environment()
        self.bad_base = True
        self.fail = "pip"
        with self.assertRaises(subprocess.CalledProcessError):
            mirror.install_schedule(self.home / "unused-root")
        self.assertEqual(python.read_text(), "fixture")
        self.assertEqual(self.plist.read_bytes(), self.old)
        self.assertFalse(any(c[0] == "launchctl" for c in self.calls))

    def test_transient_base_or_missing_uv_does_not_install(self):
        python = self.existing_environment()
        self.bad_base = True
        self.assertFalse(mirror.client_python_ready(python))
        with (
            patch("scripts.tushare_mirror.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "schedule unchanged"),
        ):
            mirror.install_schedule(self.home / "unused-root")
        self.assertEqual(self.plist.read_bytes(), self.old)
        self.assertFalse(any(c[0] == "launchctl" for c in self.calls))

    def test_entry_import_failure_does_not_bootout_old_job(self):
        self.existing_environment()
        self.fail = "entry"
        with self.assertRaises(subprocess.CalledProcessError):
            mirror.install_schedule(self.home / "unused-root")
        self.assertEqual(self.plist.read_bytes(), self.old)
        self.assertFalse(any(c[0] == "launchctl" for c in self.calls))

    def test_non_mac_rejects_without_running_commands(self):
        with (
            patch("scripts.tushare_mirror.sys.platform", "linux"),
            self.assertRaises(ValueError),
        ):
            mirror.install_schedule(self.home / "unused-root")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
