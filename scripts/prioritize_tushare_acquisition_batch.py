#!/usr/bin/env python3
"""Verify one prepared acquisition batch and prioritize only its pending jobs."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from scripts import import_tushare_rrg_acquisition_shard as importer  # noqa: E402

MAX_BATCH_JOBS = 5000


def _schema6(root):
    database = root / "pipeline.sqlite"
    if database.is_symlink() or not database.is_file():
        raise ValueError("Authority pipeline database must be a regular file")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Authority pipeline schema must already be version 6")


def _execute(root, verified, target_priority, max_jobs):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    records = [
        row
        for shard in sorted(verified["records_by_path"])
        for row in verified["records_by_path"][shard]
    ]
    if not 1 <= len(records) <= max_jobs <= MAX_BATCH_JOBS:
        raise ValueError("Verified batch exceeds the explicit bounded priority limit")
    lock_path = root / "pipeline.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe pipeline lock")
    descriptor = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    changed = Counter()
    preserved = Counter()
    before_rows = {}
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _schema6(root)
        database = root / "pipeline.sqlite"
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            for expected in records:
                saved = db.execute("SELECT rowid,* FROM jobs WHERE id=?", (expected["task_id"],)).fetchone()
                if saved is None:
                    raise ValueError("Verified batch task is missing from authority")
                identity = {
                    "task_id": saved["id"],
                    "logical_key": saved["logical_key"],
                    "epoch": saved["epoch"],
                    "group_name": saved["group_name"],
                    "job": json.loads(saved["job"]),
                }
                if identity != {key: expected[key] for key in identity}:
                    raise ValueError("Authority task identity does not match verified batch")
                before_rows[saved["id"]] = tuple(saved)
                api = expected["api_name"]
                if saved["state"] == "pending" and saved["priority"] > target_priority:
                    db.execute("UPDATE jobs SET priority=? WHERE id=?", (target_priority, saved["id"]))
                    changed[api] += 1
                else:
                    preserved[(api, saved["state"])] += 1
            db.commit()
        except BaseException:
            db.rollback()
            raise
        try:
            for task_id, before in before_rows.items():
                after = db.execute("SELECT rowid,* FROM jobs WHERE id=?", (task_id,)).fetchone()
                if after is None:
                    raise RuntimeError("Prioritized task disappeared")
                before_map = dict(zip(after.keys(), before, strict=True))
                for key in after.keys():
                    if key == "priority":
                        expected_priority = (
                            target_priority
                            if before_map["state"] == "pending"
                            and before_map["priority"] > target_priority
                            else before_map["priority"]
                        )
                        if after[key] != expected_priority:
                            raise RuntimeError("Priority postcondition mismatch")
                    elif after[key] != before_map[key]:
                        raise RuntimeError("Non-priority task state changed")
        finally:
            db.close()
    receipt = {
        "schema_version": 1,
        "status": "pending_batch_prioritized",
        "batch_manifest_sha256": verified["manifest_sha256"],
        "all_task_ids_sha256": verified["all_task_ids_sha256"],
        "target_priority": target_priority,
        "jobs": len(records),
        "changed": dict(sorted(changed.items())),
        "changed_jobs": sum(changed.values()),
        "preserved": [
            {"api_name": api, "state": state, "jobs": count}
            for (api, state), count in sorted(preserved.items())
        ],
        "transaction_committed": True,
        "task_identity_preserved": True,
        "group_state_attempt_result_and_gates_preserved": True,
        "credentials_accessed": False,
        "upstream_calls": 0,
        "worker_run": False,
        "release_published": False,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def prioritize_batch(
    batch_manifest,
    manifest_sha256,
    audit_report,
    *,
    target_priority=24,
    max_jobs=2000,
    root=None,
    execute=False,
):
    if type(target_priority) is not int or not 1 <= target_priority <= 99:
        raise ValueError("Target priority must be an integer from 1 to 99")
    if type(max_jobs) is not int or not 1 <= max_jobs <= MAX_BATCH_JOBS:
        raise ValueError("Invalid explicit batch job bound")
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline batch prioritization"))
            )
        verified = importer.verify_batch(
            batch_manifest, manifest_sha256, audit_report, shard=None
        )
        jobs = sum(len(rows) for rows in verified["records_by_path"].values())
        if jobs > max_jobs:
            raise ValueError("Verified batch exceeds the explicit bounded priority limit")
        if not execute:
            return {
                "schema_version": 1,
                "status": "plan_only",
                "batch_manifest_sha256": verified["manifest_sha256"],
                "all_task_ids_sha256": verified["all_task_ids_sha256"],
                "verified_jobs": jobs,
                "target_priority": target_priority,
                "would_mutate": False,
                "credentials_accessed": False,
                "upstream_calls": 0,
            }
        if root is None:
            raise ValueError("Execute requires authority root")
        return _execute(root, verified, target_priority, max_jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--target-priority", type=int, default=24)
    parser.add_argument("--max-jobs", type=int, default=2000)
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            prioritize_batch(
                args.batch_manifest,
                args.manifest_sha256,
                args.audit_report,
                target_priority=args.target_priority,
                max_jobs=args.max_jobs,
                root=args.root,
                execute=args.execute,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
