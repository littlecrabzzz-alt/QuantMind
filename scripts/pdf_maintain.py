#!/usr/bin/env python3
"""One OCR/archive maintenance pass following docs/tushare-mac-source.md
`安全升级与暂停`: move ENABLED away to pause new dispatch, wait for the
pipeline/documents write locks to drain naturally, and only then pause the
original archive worker at that idle point; hold -> ingest staged OCR ->
retire by the original rules; the finally block restores exactly the states
this pass changed (worker start/stop state and ENABLED bytes). Any deferral
(exit 75) or failure restores those states; in-flight source work is never
force-stopped. A recently touched status file is NOT treated as busy/idle:
the real non-blocking lock probes are the only deferral signal.
"""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Repo layout keeps this in scripts/; the installed copy lives under
# ~/Library/Application Support/QuantMind and resolves the shared backend from
# the tushare-client install tree instead, with no Documents dependency.
for _candidate in (Path(__file__).resolve().parents[1],
                   Path.home() / "Library/Application Support/QuantMind"
                   "/tushare-client"):
    if (_candidate / "backend/shared/tushare_document_ocr.py").is_file():
        sys.path.insert(0, str(_candidate))
        break
else:
    raise SystemExit("backend.shared modules not found in repo or install tree")

from backend.shared.tushare_document_ocr import ingest_staged  # noqa: E402
from backend.shared.tushare_attachment_retirement import (  # noqa: E402
    apply_plan, build_plan, hold_attachments)

DEFAULT_AGENT = "com.quantmind.tushare-archive"


def _utcnow_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class MaintenanceBusy(Exception):
    """Locks did not drain; the pass defers without touching the worker."""


def lock_free(path):
    """True when an exclusive flock can be taken right now (non-blocking)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


class LaunchctlWorker:
    """Three-state launchctl view: running / stopped / unknown.

    A failed or unreadable launchctl answer is NEVER treated as stopped; only
    the explicit "service not found in domain" result counts as stopped. The
    ``launchctl`` executable path is injectable so tests exercise this real
    code path through a scripted launchctl stub instead of boolean echoes.
    """

    def __init__(self, uid, agent, plist, launchctl="launchctl",
                 settle_seconds=10):
        self.label = f"gui/{uid}/{agent}"
        self.plist = plist
        self.launchctl = launchctl
        self.settle_seconds = settle_seconds

    def state(self):
        proc = subprocess.run([self.launchctl, "print", self.label],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("state ="):
                    value = stripped.split("=", 1)[1].strip()
                    # Exact right-hand match: launchctl reports e.g.
                    # "state = not running", which a substring test would
                    # misjudge as running.
                    return "running" if value == "running" else "stopped"
            return "unknown"  # rc 0 without a parsable state line
        combined = proc.stdout + proc.stderr
        if "Could not find service" in combined or "No such process" in combined:
            return "stopped"
        return "unknown"

    def running(self):
        return self.state() == "running"

    def pause(self):
        subprocess.run([self.launchctl, "bootout", self.label], check=False)
        for _ in range(self.settle_seconds):
            if self.state() == "stopped":
                return True
            time.sleep(1)
        return self.state() == "stopped"

    def resume(self):
        subprocess.run([self.launchctl, "bootstrap",
                        self.label.rsplit("/", 1)[0], str(self.plist)],
                       check=False)
        for _ in range(self.settle_seconds):
            if self.state() == "running":
                return True
            time.sleep(1)
        return self.state() == "running"


def _acquire_locks(root, names):
    """Non-blocking all-or-nothing acquisition of the drain locks."""
    held = []
    for name in names:
        fd = os.open(root / name, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            for open_fd in held:
                os.close(open_fd)
            return None
        held.append(fd)
    return held


def run_pass(root, staging, plans_dir, holds_file, worker, *,
             body=None, drain_timeout=600.0, poll_seconds=5.0,
             sleep=time.sleep, monotonic=time.monotonic):
    """Run one maintenance pass; returns the body's return value.

    A coordinator-exclusive non-blocking lock covers the whole pass, so two
    passes never race over the ENABLED backup. A leftover backup from a
    crashed pass is recovered or reported as a conflict, never overwritten or
    deleted; only the ENABLED this pass actually moved is restored. The
    finally block restores the marker and the worker independently: a resume
    failure is reported but never skips the ENABLED restore.
    ``body`` executes the hold/ingest/retire work at the idle point; tests
    inject a stub to verify the pause/restore protocol.
    """
    coordinator = root / ".maintenance-coordinator.lock"
    fd = os.open(coordinator, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MaintenanceBusy(
                "another maintenance pass holds the coordinator lock") from exc
        return _locked_pass(root, staging, plans_dir, holds_file, worker,
                            body=body, drain_timeout=drain_timeout,
                            poll_seconds=poll_seconds, sleep=sleep,
                            monotonic=monotonic)
    finally:
        os.close(fd)


def _locked_pass(root, staging, plans_dir, holds_file, worker, *,
                 body, drain_timeout, poll_seconds, sleep, monotonic):
    enabled = root / "ENABLED"
    backup = root / ".ENABLED.maintain-backup"
    journal = root / ".maintenance-pause-journal.json"

    # One journal carries the whole recovery intent for a pass in flight:
    # which agent was paused, the exact ENABLED bytes it moved, and the worker
    # state before the pause. A leftover backup WITHOUT this proof is never
    # auto-restored -- re-enabling a deliberately stopped archive is an
    # operator decision, not a maintenance guess.
    if journal.exists():
        _recover_journal(root, journal, backup, enabled, worker)
    elif backup.exists():
        raise MaintenanceBusy(
            "unowned .ENABLED.maintain-backup present without a pause journal; "
            "operator verification required, nothing was touched")

    paused_worker = False
    journaled = False
    held_locks = []
    try:
        state = worker.state()
        if state == "unknown":
            raise RuntimeError(
                "archive worker state unreadable; refusing to pause, pass "
                "aborted without touching the worker")
        # Persist the full intent atomically BEFORE moving anything: the
        # ENABLED hash proves backup ownership, worker_state_before drives the
        # resume decision, and a crash at any later point stays recoverable.
        _write_journal(journal, worker.label, enabled, state)
        journaled = True
        moved_enabled = enabled.exists()
        if moved_enabled:
            os.replace(enabled, backup)
        deadline = monotonic() + drain_timeout
        locks = ("pipeline.lock", "documents.lock", ".archive.lock",
                 ".migration.lock")
        # Hold ALL drain locks before pausing: readers re-check ENABLED only
        # before taking these locks, so a worker that already passed the flag
        # check must be holding (or about to take) one of them; all-four
        # acquisition closes that window instead of probing and releasing.
        while True:
            acquired = _acquire_locks(root, locks)
            if acquired is not None:
                held_locks = acquired
                break
            if monotonic() >= deadline:
                raise MaintenanceBusy(
                    "pipeline/documents/archive/migration locks still held "
                    "after drain timeout")
            sleep(poll_seconds)
        if state == "running":
            paused_worker = True
            if not worker.pause():
                raise RuntimeError(
                    "archive worker did not stop; pass aborted with the "
                    "resume intent journalled")
            sleep(5.0)
        for fd in held_locks:
            os.close(fd)
        held_locks = []
        if body is None:
            body = lambda: _default_body(root, staging, plans_dir, holds_file)  # noqa: E731
        return body()
    finally:
        for fd in held_locks:
            os.close(fd)
        # Unconditional marker restore first; a worker restore failure must
        # propagate as failure so the caller never records a successful pass
        # while the archive worker may still be stopped.
        restore_conflict = None
        if journaled and enabled.exists() and backup.exists():
            restore_conflict = (
                "both ENABLED and its backup exist after the pass; the "
                "operator must decide, nothing was overwritten")
        elif journaled and enabled.exists() is False and backup.exists():
            os.replace(backup, enabled)
            print("ENABLED restored", time.strftime("%F %T"), flush=True)
        resume_failure = None
        if paused_worker:
            try:
                if not worker.resume():
                    resume_failure = "resume command failed or state unverified"
                else:
                    print("worker restored to running",
                          time.strftime("%F %T"), flush=True)
            except Exception as exc:
                resume_failure = f"resume raised {type(exc).__name__}"
        elif journaled:
            print("worker was not paused this pass",
                  time.strftime("%F %T"), flush=True)
        if journaled and not resume_failure and not restore_conflict:
            journal.unlink(missing_ok=True)
        if restore_conflict:
            print(f"ENABLED RESTORE CONFLICT: {restore_conflict}; pause "
                  f"journal kept", flush=True)
            raise RuntimeError(f"ENABLED restore conflict: {restore_conflict}")
        if resume_failure:
            print(f"WORKER RESUME FAILED: {resume_failure}; ENABLED restored, "
                  f"pause journal kept for recovery", flush=True)
            raise RuntimeError(f"archive worker resume failed: {resume_failure}")


def _journal_intent(journal):
    try:
        return json.loads(journal.read_bytes())
    except ValueError:
        return {}


def _file_sha(path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _recover_journal(root, journal, backup, enabled, worker):
    """Recover a crashed pass strictly per its journalled intent.

    Unknown, legacy or corrupted journals (missing worker_state_before or a
    malformed enabled_sha256) are kept in place and fail non-zero: silently
    deleting one can lose the only recovery intent. A backup never overwrites
    an ENABLED whose bytes differ from the journal proof -- that is a
    conflict for the operator, not a restore."""
    recorded = _journal_intent(journal)
    if not recorded or recorded.get("agent") != worker.label:
        raise RuntimeError(
            f"pause journal belongs to {recorded.get('agent')!r}, not "
            f"{worker.label!r}; left in place for its own recovery")
    state_before = recorded.get("worker_state_before")
    if state_before not in ("running", "stopped"):
        raise RuntimeError(
            "pause journal lacks a valid worker_state_before; kept in place "
            "rather than guessing the recovery intent")
    backup_sha = recorded.get("enabled_sha256")
    if backup_sha is not None and (not isinstance(backup_sha, str)
                                   or not _is_sha256(backup_sha)):
        raise RuntimeError(
            "pause journal carries a malformed enabled_sha256; kept in place")
    if backup_sha is None:
        if backup.exists() or enabled.exists():
            raise RuntimeError(
                "pause journal records no ENABLED move but flag files exist; "
                "manual inspection required, nothing was touched")
    elif backup.exists() and enabled.exists():
        raise RuntimeError(
            "both ENABLED and its maintenance backup exist; the operator "
            "must decide, nothing was overwritten")
    elif backup.exists():
        if _file_sha(backup) != backup_sha:
            raise RuntimeError(
                "ENABLED backup bytes do not match the pause journal proof; "
                "manual inspection required, nothing was touched")
        os.replace(backup, enabled)
        print("recovered ENABLED backup proven by the pause journal",
              flush=True)
    elif enabled.exists():
        if _file_sha(enabled) != backup_sha:
            raise RuntimeError(
                "pause journal owns an ENABLED backup that is missing and "
                "the present ENABLED differs from the proof; manual "
                "inspection required")
        # flag already restored; only the worker may remain paused
    else:
        raise RuntimeError(
            "pause journal owns an ENABLED backup that is missing; manual "
            "inspection required")
    if state_before == "running":
        print("recovering unfinished worker resume from a crashed pass",
              flush=True)
        if not worker.resume():
            raise RuntimeError(
                "crashed pass left the archive worker stopped and resume "
                "failed; manual restoration required")
    journal.unlink()


def _is_sha256(value):
    import re
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _write_journal(journal, label, enabled, worker_state):
    temporary = journal.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "agent": label,
        "paused_at": _utcnow_iso(),
        "enabled_sha256": _file_sha(enabled),
        "worker_state_before": worker_state,
        "intent": "restore this ENABLED (hash-proven) and resume the agent "
                  "only if worker_state_before is running",
    }))
    temporary.replace(journal)


def _default_body(root, staging, plans_dir, holds_file):
    plans_dir.mkdir(parents=True, exist_ok=True)
    if holds_file.exists():
        held = hold_attachments(root, holds_file.read_text().split(),
                                reason="periodic_report_double_check")
        print("hold", json.dumps(held), flush=True)
    print("ingest", json.dumps(ingest_staged(root, staging)), flush=True)
    after, total, nbytes, n = None, 0, 0, 0
    while True:
        n += 1
        plan = plans_dir / f"plan-{n:04d}.json"
        summary = build_plan(root, plan, max_items=10000, after=after)
        if summary["candidate_count"]:
            while apply_plan(root, plan, confirm_sha=summary["plan_sha256"],
                             max_items=1000)["status"] != "complete":
                pass
            total += summary["candidate_count"]
            nbytes += summary["candidate_bytes"]
        after = summary.get("next_after")
        if not after:
            break
    print("retired", total, "pdfs", round(nbytes / 1e9, 1), "GB", flush=True)
    return {"retired": total}


def main(argv=None):
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",
                        default=str(home / "Library/Application Support/QuantMind/tushare"))
    parser.add_argument("--staging",
                        default=str(home / "Library/Application Support/QuantMind"
                                    "/maintenance/ocr-staging"))
    parser.add_argument("--plans", default=None,
                        help="defaults to pdf-text-driver/plans/<timestamp>")
    parser.add_argument("--holds",
                        default=str(home / "Library/Application Support/QuantMind"
                                    "/maintenance/periodic-hold-shas.txt"))
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    args = parser.parse_args(argv)
    root, staging = Path(args.root), Path(args.staging)
    holds = Path(args.holds)
    plans = Path(args.plans) if args.plans else (
        home / "Library/Application Support/QuantMind/maintenance/pdf-text-driver/plans"
        / time.strftime("%Y%m%d-%H%M"))
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    worker = LaunchctlWorker(uid, args.agent,
                             home / "Library/LaunchAgents" / f"{args.agent}.plist")
    try:
        run_pass(root, staging, plans, holds, worker)
    except MaintenanceBusy as exc:
        print(f"defer: {exc}", flush=True)
        return 75
    return 0


if __name__ == "__main__":
    sys.exit(main())
