"""Pause/restore protocol regressions for the OCR archive maintenance pass,
per docs/tushare-mac-source.md 安全升级与暂停: ENABLED moves away to pause new
dispatch, real non-blocking lock probes decide deferral (never mtime guesses),
the worker is paused only after the locks drain, and every deferral or failure
path restores exactly what this pass changed. Fixture roots only; no real
archive, agent, or plan directories are touched."""

import fcntl
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import pdf_maintain as pm  # noqa: E402


class FakeWorker:
    label = "fake-worker"

    def __init__(self, running=True):
        self.calls = []
        self._running = running

    def running(self):
        self.calls.append("running")
        return self._running

    def state(self):
        return "running" if self._running else "stopped"

    def pause(self):
        self.calls.append("pause")
        self._running = False
        return True

    def resume(self):
        self.calls.append("resume")
        self._running = True
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
        self.assertEqual(worker.calls, ["pause", "resume"])
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())

    def test_happy_path_pauses_at_idle_and_restores(self):
        worker = FakeWorker(running=True)
        result = pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                             self.holds, worker, body=self.body(),
                             **self.pass_kwargs())
        self.assertEqual(result, {"retired": 0})
        self.assertEqual(worker.calls, ["pause", "resume"])
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

    def test_unowned_backup_defers_and_is_never_auto_restored(self):
        # A backup without a journal proof could be a deliberately stopped
        # archive; re-enabling it is an operator decision, never a guess.
        (self.root / ".ENABLED.maintain-backup").write_bytes(b"manual-stop\n")
        (self.root / "ENABLED").unlink()
        worker = FakeWorker(running=True)
        with self.assertRaises(pm.MaintenanceBusy):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual((self.root / ".ENABLED.maintain-backup").read_bytes(),
                         b"manual-stop\n")
        self.assertFalse((self.root / "ENABLED").exists())
        self.assertEqual(worker.calls, [])

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
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(),
                        **self.pass_kwargs())
        # ENABLED is restored unconditionally first; the failure propagates so
        # the caller can never record success with the worker left stopped.
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".ENABLED.maintain-backup").exists())
        self.assertTrue((self.root / ".maintenance-pause-journal.json").exists())

    def test_pause_failure_aborts_and_restores_without_resume(self):
        class PauseFails(FakeWorker):
            def pause(self):
                self.calls.append("pause")
                return False

        worker = PauseFails(running=True)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        # The resume intent is journalled before the pause attempt, so a pause
        # failure still restores the worker via the finally path.
        self.assertEqual(worker.calls, ["pause", "resume"])
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".maintenance-pause-journal.json").exists())
        self.assertNotIn("body", self.events)

    def test_legacy_journal_without_state_is_kept_not_guessed(self):
        (self.root / ".maintenance-pause-journal.json").write_text(
            '{"agent": "fake-worker"}')
        worker = FakeWorker(running=True)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertTrue((self.root / ".maintenance-pause-journal.json").exists())
        self.assertEqual(worker.calls, [])

    def test_both_enabled_and_backup_present_is_a_kept_conflict(self):
        (self.root / ".ENABLED.maintain-backup").write_bytes(b"older\n")
        (self.root / "ENABLED").write_bytes(b"archive-owner\n")
        worker = FakeWorker(running=True)
        with self.assertRaises(pm.MaintenanceBusy):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertEqual((self.root / ".ENABLED.maintain-backup").read_bytes(),
                         b"older\n")
        self.assertEqual(worker.calls, [])

    def test_foreign_enabled_bytes_with_journal_backup_missing_is_kept(self):
        import hashlib as _h
        (self.root / "ENABLED").write_bytes(b"someone-elses\n")
        (self.root / ".maintenance-pause-journal.json").write_text(json.dumps({
            "agent": "fake-worker",
            "enabled_sha256": _h.sha256(b"archive-owner\n").hexdigest(),
            "worker_state_before": "stopped"}))
        worker = FakeWorker(running=False)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"someone-elses\n")
        self.assertTrue((self.root / ".maintenance-pause-journal.json").exists())

    def test_foreign_label_journal_is_never_consumed(self):
        (self.root / ".maintenance-pause-journal.json").write_text(
            '{"agent": "gui/501/some.other.agent"}')
        worker = FakeWorker(running=True)
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, worker, body=self.body(), **self.pass_kwargs())
        self.assertEqual(
            (self.root / ".maintenance-pause-journal.json").read_text(),
            '{"agent": "gui/501/some.other.agent"}')
        self.assertEqual(worker.calls, [])

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



LAUNCHCTL_STUB = """#!/bin/sh
echo "$1 $2" >> "$STUB_STATE/calls"
if [ "$1" = "print" ]; then
  if [ -f "$STUB_STATE/unknown" ]; then echo "launchctl blew up" >&2; exit 71; fi
  if [ -f "$STUB_STATE/blank" ]; then echo "some unrelated output"; exit 0; fi
  if [ -f "$STUB_STATE/not_running" ]; then printf '  state = not running\n'; exit 0; fi
  if [ -f "$STUB_STATE/stopped" ]; then
    echo "Could not find service specified" >&2; exit 1
  fi
  printf '  state = running\\n'; exit 0
fi
if [ "$1" = "bootout" ]; then touch "$STUB_STATE/stopped"; exit 0; fi
if [ "$1" = "bootstrap" ]; then
  if [ -f "$STUB_STATE/resume_fails" ]; then exit 0; fi
  rm -f "$STUB_STATE/stopped"; exit 0
fi
exit 0
"""


class RealLaunchctlWorkerProtocol(unittest.TestCase):
    """Exercises the real LaunchctlWorker code through a scripted launchctl
    stub (real subprocess + real state machine), not boolean mocks."""

    def setUp(self):
        base = Path(tempfile.mkdtemp(prefix="qm realworker test "))
        self.addCleanup(lambda: __import__("shutil").rmtree(base, ignore_errors=True))
        self.root = base / "archive"
        self.root.mkdir()
        (self.root / "ENABLED").write_bytes(b"archive-owner\n")
        for name in ("pipeline.lock", "documents.lock", ".archive.lock",
                     ".migration.lock"):
            (self.root / name).write_bytes(b"")
        self.holds = base / "holds.txt"
        self.holds.write_text("")
        self.state = base / "stub-state"
        self.state.mkdir()
        stub = base / "fake-launchctl"
        stub.write_text(LAUNCHCTL_STUB)
        stub.chmod(0o755)
        self.worker = pm.LaunchctlWorker(
            "501", "com.quantmind.tushare-archive", base / "agent.plist",
            launchctl=str(stub), settle_seconds=0)
        os.environ["STUB_STATE"] = str(self.state)
        self.addCleanup(os.environ.pop, "STUB_STATE", None)
        self.kwargs = {"drain_timeout": 0.3, "poll_seconds": 0.05,
                       "sleep": lambda s: None,
                       "monotonic": _counter()}

    def body(self, events):
        def run():
            events.append(
                f"journal_during={(self.root / '.maintenance-pause-journal.json').exists()}"
+                f" enabled_present={(self.root / 'ENABLED').exists()}")
            return {"retired": 0}
        return run

    def test_real_worker_pauses_and_resumes_with_journal(self):
        events = []
        result = pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                             self.holds, self.worker,
                             body=self.body(events), **self.kwargs)
        self.assertEqual(result, {"retired": 0})
        self.assertIn("journal_during=True enabled_present=False", events)
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertFalse((self.root / ".maintenance-pause-journal.json").exists())
        calls = (self.state / "calls").read_text().splitlines()
        self.assertIn("print gui/501/com.quantmind.tushare-archive", calls)
        self.assertTrue(any(c.startswith("bootout") for c in calls))
        self.assertTrue(any(c.startswith("bootstrap") for c in calls))

    def test_real_worker_resume_failure_restores_enabled_and_keeps_journal(self):
        (self.state / "resume_fails").write_text("")
        events = []
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, self.worker,
                        body=self.body(events), **self.kwargs)
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertTrue((self.root / ".maintenance-pause-journal.json").exists())

    def test_journal_from_crashed_pass_is_recovered_on_next_pass(self):
        import hashlib as _h
        (self.state / "stopped").write_text("")
        (self.root / "ENABLED").unlink()
        (self.root / ".ENABLED.maintain-backup").write_bytes(b"archive-owner\n")
        (self.root / ".maintenance-pause-journal.json").write_text(json.dumps({
            "agent": "gui/501/com.quantmind.tushare-archive",
            "enabled_sha256": _h.sha256(b"archive-owner\n").hexdigest(),
            "worker_state_before": "running"}))
        events = []
        pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                    self.holds, self.worker, body=self.body(events),
                    **self.kwargs)
        self.assertFalse((self.root / ".maintenance-pause-journal.json").exists())
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")
        self.assertTrue((self.state / "calls").read_text().count("bootstrap") >= 1)

    def test_blank_print_output_is_unknown_not_stopped(self):
        (self.state / "blank").write_text("")
        self.assertEqual(self.worker.state(), "unknown")
        events = []
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, self.worker,
                        body=self.body(events), **self.kwargs)
        calls = (self.state / "calls").read_text().splitlines()
        self.assertFalse(any(c.startswith("bootout") for c in calls))
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")

    def test_not_running_state_line_parses_as_stopped(self):
        (self.state / "not_running").write_text("")
        self.assertEqual(self.worker.state(), "stopped")

    def test_unknown_worker_state_aborts_without_pausing(self):
        (self.state / "unknown").write_text("")
        events = []
        with self.assertRaises(RuntimeError):
            pm.run_pass(self.root, self.root / "staging", self.root / "plans",
                        self.holds, self.worker,
                        body=self.body(events), **self.kwargs)
        calls = (self.state / "calls").read_text().splitlines()
        self.assertFalse(any(c.startswith("bootout") for c in calls))
        self.assertEqual((self.root / "ENABLED").read_bytes(), b"archive-owner\n")


class _counter:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.01
        return self.now


if __name__ == "__main__":
    unittest.main()
