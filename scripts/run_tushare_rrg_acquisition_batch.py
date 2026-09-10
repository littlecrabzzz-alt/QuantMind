#!/usr/bin/env python3
"""Plan or execute one hash-pinned, exact RRG acquisition batch."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import shutil
import sqlite3
import sys
import threading
from unittest.mock import patch

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from scripts import import_tushare_rrg_acquisition_shard as importer  # noqa: E402

MAX_BATCH_JOBS = 2000
MAX_UPSTREAM_REQUESTS = 360
MAX_SECONDS = 90
ALLOWED_APIS = {"etf_limit", "fund_div"}


def sha(path):
    return digest(Path(path).read_bytes())


def helper_sha256():
    return sha(Path(__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Authority {label} must be a regular file")
    return path


def _schema6(root):
    database = _regular(Path(root) / "pipeline.sqlite", "pipeline database")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Authority pipeline schema must already be version 6")
    finally:
        db.close()


def _records(verified):
    rows = [
        row
        for shard in sorted(verified["records_by_path"])
        for row in verified["records_by_path"][shard]
    ]
    if not 1 <= len(rows) <= MAX_BATCH_JOBS:
        raise ValueError("Verified batch exceeds the explicit job limit")
    if {row["api_name"] for row in rows} - ALLOWED_APIS:
        raise ValueError(
            "Verified batch contains an API outside the RRG acquisition scope"
        )
    expected_groups = {"fund_div": "market", "etf_limit": "cross_asset_extra"}
    if any(row["group_name"] != expected_groups[row["api_name"]] for row in rows):
        raise ValueError("Verified batch contains an unexpected Pipeline group")
    return rows


def _state_counts(pipeline):
    return [
        {"api_name": api, "state": state, "jobs": jobs}
        for api, state, jobs in pipeline.db.execute(
            "SELECT json_extract(j.job,'$.api_name'),j.state,COUNT(*) "
            "FROM exact_task_scope s CROSS JOIN jobs j ON j.id=s.task_id "
            "GROUP BY 1,2 ORDER BY 1,2"
        )
    ]


def _attempt_counts(pipeline):
    return Counter(
        dict(
            pipeline.db.execute(
                "SELECT json_extract(j.job,'$.api_name'),COUNT(a.attempt) "
                "FROM exact_task_scope s CROSS JOIN jobs j ON j.id=s.task_id "
                "LEFT JOIN attempts a ON a.job_id=j.id GROUP BY 1"
            )
        )
    )


def _verify_authority_jobs(pipeline, records):
    priorities = Counter()
    for expected in records:
        saved = pipeline.db.execute(
            "SELECT id,logical_key,epoch,job,priority,state,group_name "
            "FROM jobs WHERE id=?",
            (expected["task_id"],),
        ).fetchone()
        if saved is None:
            raise ValueError("Verified batch task is missing from authority")
        actual = {
            "task_id": saved["id"],
            "logical_key": saved["logical_key"],
            "epoch": saved["epoch"],
            "group_name": saved["group_name"],
            "job": json.loads(saved["job"]),
        }
        if actual != {key: expected[key] for key in actual}:
            raise ValueError("Authority task identity does not match verified batch")
        priorities[saved["priority"]] += 1
    return priorities


@contextmanager
def _hard_deadline(seconds):
    if threading.current_thread() is not threading.main_thread() or not hasattr(
        signal, "setitimer"
    ):
        yield
        return
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError("Exact batch wall-clock deadline reached")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _execute(
    root,
    batch_manifest,
    manifest_sha256,
    audit_report,
    expected_task_ids_sha256,
    expected_config_sha256,
    max_requests,
    max_seconds,
):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    _regular(root / "ENABLED", "enable marker")
    lock_path = root / "pipeline.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe pipeline lock")
    descriptor = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _schema6(root)
        verified = importer.verify_batch(
            batch_manifest, manifest_sha256, audit_report, shard=None
        )
        records = _records(verified)
        if verified["all_task_ids_sha256"] != expected_task_ids_sha256:
            raise ValueError("Explicit task ID inventory hash mismatch")
        config_path = _regular(root / "pipeline-config.json", "pipeline config")
        config_bytes = config_path.read_bytes()
        if digest(config_bytes) != expected_config_sha256:
            raise ValueError("Explicit authority config hash mismatch")
        config = json.loads(config_bytes)
        pipeline = pipeline_module.Pipeline(root, verified["catalog"])
        try:
            priorities = _verify_authority_jobs(pipeline, records)
            task_ids = [row["task_id"] for row in records]
            pipeline._install_exact_task_scope(task_ids)
            before_states = _state_counts(pipeline)
            before_attempts = _attempt_counts(pipeline)
            pointer = root / "CURRENT.json"
            pointer_before = (
                sha(_regular(pointer, "current pointer")) if pointer.exists() else None
            )
            if shutil.disk_usage(root).free < 100 * 2**30:
                return {
                    "schema_version": 1,
                    "status": "blocked_disk_reserve",
                    "batch_manifest_sha256": verified["manifest_sha256"],
                    "all_task_ids_sha256": verified["all_task_ids_sha256"],
                    "authority_config_sha256": expected_config_sha256,
                    "helper_sha256": helper_sha256(),
                    "upstream_calls": 0,
                    "release_published": False,
                }
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {
                    "schema_version": 1,
                    "status": "blocked_missing_token",
                    "batch_manifest_sha256": verified["manifest_sha256"],
                    "all_task_ids_sha256": verified["all_task_ids_sha256"],
                    "authority_config_sha256": expected_config_sha256,
                    "helper_sha256": helper_sha256(),
                    "upstream_calls": 0,
                    "release_published": False,
                }
            with (
                _hard_deadline(max_seconds),
                httpx.Client(
                    trust_env=False,
                    timeout=min(30, max_seconds),
                    follow_redirects=False,
                ) as client,
            ):
                run = pipeline.run(
                    client,
                    token,
                    config,
                    max_requests=max_requests,
                    max_seconds=max_seconds,
                    pause=0,
                    task_ids=task_ids,
                )
            after_attempts = _attempt_counts(pipeline)
            after_states = _state_counts(pipeline)
            attempted = {
                api: after_attempts[api] - before_attempts[api]
                for api in sorted(after_attempts | before_attempts)
                if after_attempts[api] != before_attempts[api]
            }
            pointer_after = (
                sha(_regular(pointer, "current pointer")) if pointer.exists() else None
            )
            if _regular(config_path, "pipeline config").read_bytes() != config_bytes:
                raise RuntimeError("Authority config changed while lock was held")
            if pointer_after != pointer_before:
                raise RuntimeError("Current release pointer changed during exact batch")
        finally:
            pipeline.close()
    receipt = {
        "schema_version": 1,
        "status": "exact_batch_executed",
        "batch_manifest_sha256": verified["manifest_sha256"],
        "all_task_ids_sha256": verified["all_task_ids_sha256"],
        "authority_config_sha256": expected_config_sha256,
        "helper_sha256": helper_sha256(),
        "verified_jobs": len(records),
        "priority_counts": dict(sorted(priorities.items())),
        "before_states": before_states,
        "after_states": after_states,
        "attempted_by_api": attempted,
        "upstream_calls": run["requests"],
        "max_upstream_calls": max_requests,
        "max_seconds": max_seconds,
        "elapsed_seconds": run["elapsed_seconds"],
        "exact_task_scope": run["exact_task_scope"],
        "scoped_jobs": run["scoped_jobs"],
        "task_identity_preserved": True,
        "pipeline_normalization_attempt_retry_and_split_reused": True,
        "account_api_and_daily_quota_gates_reused": True,
        "global_permission_denial_propagation_preserved": True,
        "release_published": False,
        "current_release_switched": False,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def run_batch(
    batch_manifest,
    manifest_sha256,
    audit_report,
    *,
    expected_task_ids_sha256=None,
    expected_config_sha256=None,
    expected_helper_sha256=None,
    root=None,
    max_requests=360,
    max_seconds=90,
    execute=False,
):
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_UPSTREAM_REQUESTS:
        raise ValueError("Upstream request limit must be an integer from 1 to 360")
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError(
            "Wall-clock limit must be greater than 0 and at most 90 seconds"
        )
    current_helper_sha256 = helper_sha256()
    if expected_helper_sha256 and expected_helper_sha256 != current_helper_sha256:
        raise ValueError("Explicit helper hash mismatch")
    if not execute:
        with ExitStack() as guards:
            for target in (
                "socket.socket.connect",
                "socket.getaddrinfo",
                "backend.shared.tushare_pipeline.get_secret",
                "backend.shared.runtime_secrets.get_secret",
            ):
                guards.enter_context(
                    patch(
                        target, side_effect=AssertionError("Offline exact batch plan")
                    )
                )
            verified = importer.verify_batch(
                batch_manifest, manifest_sha256, audit_report, shard=None
            )
            records = _records(verified)
        counts = Counter(row["api_name"] for row in records)
        return {
            "schema_version": 1,
            "status": "plan_only",
            "batch_manifest_sha256": verified["manifest_sha256"],
            "all_task_ids_sha256": verified["all_task_ids_sha256"],
            "helper_sha256": current_helper_sha256,
            "verified_jobs": len(records),
            "api_counts": dict(sorted(counts.items())),
            "max_upstream_calls": max_requests,
            "max_seconds": max_seconds,
            "selection": "exact_manifest_task_ids_api_fair",
            "would_access_authority": False,
            "would_access_credentials": False,
            "would_call_upstream": False,
            "would_publish": False,
        }
    if not all(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in (
            expected_task_ids_sha256,
            expected_config_sha256,
            expected_helper_sha256,
        )
    ):
        raise ValueError(
            "Execute requires pinned task, config and helper SHA-256 values"
        )
    if root is None:
        raise ValueError("Execute requires authority root")
    return _execute(
        root,
        batch_manifest,
        manifest_sha256,
        audit_report,
        expected_task_ids_sha256,
        expected_config_sha256,
        max_requests,
        max_seconds,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--expected-task-ids-sha256")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--max-requests", type=int, default=360)
    parser.add_argument("--max-seconds", type=float, default=90)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = run_batch(
            args.batch_manifest,
            args.manifest_sha256,
            args.audit_report,
            expected_task_ids_sha256=args.expected_task_ids_sha256,
            expected_config_sha256=args.expected_config_sha256,
            expected_helper_sha256=args.expected_helper_sha256,
            root=args.root,
            max_requests=args.max_requests,
            max_seconds=args.max_seconds,
            execute=args.execute,
        )
    except (ValueError, OSError, sqlite3.Error, httpx.HTTPError, TimeoutError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
