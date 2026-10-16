"""Pause/restore protocol regressions for the OCR archive maintenance pass,
per docs/tushare-mac-source.md 安全升级与暂停: ENABLED moves away to pause new
dispatch, real non-blocking lock probes decide deferral (never mtime guesses),
the worker is paused only after the locks drain, and every deferral or failure
path restores exactly what this pass changed. Fixture roots only; no real
archive, agent, or plan directories are touched."""

import fcntl
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import pdf_maintain as pm  # noqa: E402


class FakeWorker:
    def __init__(self, running=True):
        self.calls = []
        self._running = running

    def running(self):
        self.calls.append("running")
        return self._running

    def pause(self):
        self.calls.append("pause")
        return True

    def resume(self):
        self.calls.append("resume")
        return True


class MaintainProtocol(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="qm maintain test "))
        self.addCleanup(lambda: __import__("shutil").rmtree(base, ignore_errors=True))
        self.root = base / "archive"
        self.root.mkdir()
        (self.root / "ENABLED").write_bytes(b"archive-owner\n")
        for name in ("pipeline.lock", "documents.lock"):
            (self.root / name).write_bytes(b"")
        self.holds = base / "holds.txt"
        self.holds.write_text("")
        self.events = []

    def body(self, raise_exc=None):
        def run():
            self.events.append("body")
            self.events.append(f"enabled_moved={(self.root / '.ENABLED.maintain-backup').exists()}")
            self.events.append(
                f"enabled_present={(self.root / 'ENABLED').exists()}")
            if raise_exc:
                raise raise_exc
            return {"retired": 0}
        return run

    def pass_kwargs(self):
        return {"drain_timeout": 0.2, "poll_seconds": 0.05,
                "sleep": lambda s: self.events.append(f"sleep{int(s)}"),
                "monotonic": monotonic_counter()}

    def test_busy_locks_defer_without_pausing_worker(self):
        held = os.open(self.root / "pipeline.lock", os.O_RDONLY)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX)
        worker = FakeWorker(running=True)
        with self.assertRaises(pm.MaintenanceBusy):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(),
                        **self.pass_kwargs())
        self.assertNotIn("pause", worker.calls)
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())
        self.assertNotIn("body", self.events)

    def test_body_failure_restores_worker_and_enabled(self):
        worker = FakeWorker(running=True)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker,
                        body=self.body(raise_exc=RuntimeError("retire boom")),
                        **self.pass_kwargs())
        self.assertEqual(worker.calls, ["running", "pause", "resume"])
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())

    def test_happy_path_pauses_at_idle_and_restores(self):
        worker = FakeWorker(running=True)
        result = pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                             self.holds, worker, body=self.body(),
                             **self.pass_kwargs())
        self.assertEqual(result, {"retired": 0})
        self.assertEqual(worker.calls, ["running", "pause", "resume"])
        self.assertIn("enabled_moved=True", self.events)
        self.assertIn("enabled_present=False", self.events)
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")

    def test_worker_already_stopped_is_not_bootstrapped(self):
        worker = FakeWorker(running=False)
        pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                    self.holds, worker, body=self.body(), **self.pass_kwargs())

    def test_second_pass_defers_while_coordinator_lock_held(self):
        coordinator = os.open(self.root / ".maintenance-coordinator.lock",
                              os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, coordinator)
        fcntl.flock(coordinator, fcntl.LOCK_EX)
        worker = FakeWorker(running=True)
        with self.assertRaises(pm.MaintenanceBusy):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual(worker.calls, [])
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")

    def test_stale_backup_is_recovered_not_deleted(self):
        (self.root / ".ENABLED.maintain-backup").write_bytes(b"archive-owner\n")
        (self.root / "ENABLED").unlink()
        worker = FakeWorker(running=False)
        pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                    self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())

    def test_stale_backup_conflict_defers_without_touching_anything(self):
        (self.root / ".ENABLED.maintain-backup").write_bytes(b"stranger\n")
        worker = FakeWorker(running=True)
        with self.assertRaises(pm.MaintenanceBusy):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertEqual((self.root / ".ENABLED.maintain-backup").read_bytes(),
                         b"stranger\n")
        self.assertEqual(worker.calls, [])

    def test_resume_failure_still_restores_enabled(self):
        class ResumeFails(FakeWorker):
            def resume(self):
                self.calls.append("resume")
                raise RuntimeError("bootstrap exploded")

        worker = ResumeFails(running=True)
        result = pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                             self.holds, worker, body=self.body(),
                             **self.pass_kwargs())
        self.assertEqual(result, {"retired": 0})
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())

    def test_pause_failure_aborts_and_restores_without_resume(self):
        class PauseFails(FakeWorker):
            def pause(self):
                self.calls.append("pause")
                return False

        worker = PauseFails(running=True)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual(worker.calls, ["running", "pause"])
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertNotIn("body", self.events)

    def test_enabled_absent_before_pass_stays_absent(self):
        (self.root / "ENABLED").unlink()
        worker = FakeWorker(running=False)
        pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                    self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertFalse((self.root / "ENABLED").exists())
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())


class monotonic_counter:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.01
        return self.now


if __name__ == "__main__":
    unittest.main()
