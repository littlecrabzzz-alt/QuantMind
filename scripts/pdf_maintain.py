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
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_document_ocr import ingest_staged  # noqa: E402
from backend.shared.tushare_attachment_retirement import (  # noqa: E402
    apply_plan, build_plan, hold_attachments)

DEFAULT_AGENT = "com.quantmind.tushare-archive"


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
    def __init__(self, uid, agent, plist):
        self.label = f"gui/{uid}/{agent}"
        self.plist = plist

    def running(self):
        out = subprocess.run(["launchctl", "print", self.label],
                             capture_output=True, text=True).stdout
        return "state = running" in out

    def pause(self):
        subprocess.run(["launchctl", "bootout", self.label])

    def resume(self):
        subprocess.run(["launchctl", "bootstrap",
                        self.label.rsplit("/", 1)[0], str(self.plist)])


def run_pass(root, staging, plans_dir, holds_file, worker, *,
             body=None, drain_timeout=600.0, poll_seconds=5.0,
             sleep=time.sleep, monotonic=time.monotonic):
    """Run one maintenance pass; returns the body's return value.

    ``body`` executes the hold/ingest/retire work once the system is paused at
    an idle point; tests inject a stub to verify the pause/restore protocol.
    """
    enabled = root / "ENABLED"
    backup = root / ".ENABLED.maintain-backup"
    saved_enabled = enabled.read_bytes() if enabled.exists() else None
    if saved_enabled is not None:
        os.replace(enabled, backup)
    paused_worker = False
    try:
        deadline = monotonic() + drain_timeout
        while not all(lock_free(p) for p in (root / "pipeline.lock",
                                             root / "documents.lock")):
            if monotonic() >= deadline:
                raise MaintenanceBusy(
                    "pipeline/documents locks still held after drain timeout")
            sleep(poll_seconds)
        was_running = worker.running()
        if was_running:
            worker.pause()
            paused_worker = True
            sleep(5.0)
        if body is None:
            body = lambda: _default_body(root, staging, plans_dir, holds_file)  # noqa: E731
        return body()
    finally:
        if paused_worker:
            worker.resume()
            print("worker restored to running", time.strftime("%F %T"), flush=True)
        else:
            print("worker was not paused this pass", time.strftime("%F %T"), flush=True)
        if saved_enabled is not None:
            if enabled.exists():
                enabled.unlink()
            os.replace(backup, enabled)
            print("ENABLED restored", time.strftime("%F %T"), flush=True)
        elif backup.exists():
            backup.unlink()
            print("ENABLED absent before pass; kept absent", flush=True)


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
