#!/usr/bin/env python3
"""Plan or execute one hash-pinned paired top10 holder exact batch."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from unittest.mock import patch

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest  # noqa: E402
from scripts import prepare_tushare_top10_holders_batch as preparation  # noqa: E402
from scripts import run_tushare_fund_nav_batch as exact_runner  # noqa: E402

MAX_UPSTREAM_REQUESTS = 360
MAX_SECONDS = 90
MIN_FREE_BYTES = 100 * 2**30


def sha(path):
    return digest(Path(path).read_bytes())


def helper_sha256():
    return sha(Path(__file__).resolve())


def preparation_sha256():
    return sha(Path(preparation.__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Authority {label} must be a regular file")
    return path


def _verify_code(manifest):
    expected = manifest["source"]["code_sha256"]
    actual = {path: sha(REPO / path) for path in preparation.CODE_PATHS}
    if actual != expected:
        raise ValueError("Pinned code SHA-256 inventory changed")
    if actual["scripts/prepare_tushare_top10_holders_batch.py"] != preparation_sha256():
        raise ValueError("Pinned preparation SHA-256 changed")
    if actual["scripts/run_tushare_top10_holders_batch.py"] != helper_sha256():
        raise ValueError("Pinned helper SHA-256 changed")


def _verify_release_file(root, source):
    release = source["release_id"]
    manifest = _regular(
        root / "releases" / release / "manifest.json", "release manifest"
    )
    if sha(manifest) != source["release_manifest_sha256"]:
        raise ValueError("Pinned fixed release manifest changed")


def _verify_authority_jobs(pipeline, records):
    for expected in records:
        row = pipeline.db.execute(
            "SELECT j.id,j.logical_key,j.epoch,j.priority,j.group_name,j.state,j.tries,j.result,j.job,"
            "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) attempts FROM jobs j WHERE j.id=?",
            (expected["task_id"],),
        ).fetchone()
        if row is None:
            raise ValueError("Pinned task is missing from authority")
        actual = {
            "task_id": row["id"],
            "logical_key": row["logical_key"],
            "epoch": row["epoch"],
            "priority": row["priority"],
            "group_name": row["group_name"],
            "state": row["state"],
            "tries": row["tries"],
            "attempts": row["attempts"],
            "job": json.loads(row["job"]),
        }
        if actual != expected or row["result"] is not None:
            raise ValueError(
                "Pinned task is no longer pristine or its identity changed"
            )


def _execute(
    root, verified, manifest_sha256, expected_config_sha256, max_requests, max_seconds
):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    _regular(root / "ENABLED", "enable marker")
    _verify_release_file(root, verified["source"])
    lock_path = _regular(root / "pipeline.lock", "pipeline lock")
    descriptor = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pointer_path = _regular(root / "CURRENT.json", "current pointer")
        pointer_bytes = pointer_path.read_bytes()
        source = verified["source"]
        if digest(pointer_bytes) != source["current_pointer_sha256"] or json.loads(
            pointer_bytes
        ) != {
            "manifest_sha256": source["release_manifest_sha256"],
            "release_id": source["release_id"],
        }:
            raise ValueError("Pinned fixed release is no longer CURRENT")
        config_path = _regular(root / "pipeline-config.json", "pipeline config")
        config_bytes = config_path.read_bytes()
        if (
            digest(config_bytes) != expected_config_sha256
            or source["authority_config_sha256"] != expected_config_sha256
        ):
            raise ValueError("Pinned authority config changed")
        database = _regular(root / "pipeline.sqlite", "pipeline database")
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0)
        ) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
        pipeline = pipeline_module.Pipeline(
            root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        try:
            _verify_authority_jobs(pipeline, verified["records"])
            task_ids = [row["task_id"] for row in verified["records"]]
            pipeline._install_exact_task_scope(task_ids)
            before_states = exact_runner._state_counts(pipeline)
            before_attempts = exact_runner._attempt_counts(pipeline)
            if shutil.disk_usage(root).free < MIN_FREE_BYTES:
                return {
                    "status": "blocked_disk_reserve",
                    "upstream_calls": 0,
                    "release_published": False,
                    "current_release_switched": False,
                }
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {
                    "status": "blocked_missing_token",
                    "upstream_calls": 0,
                    "release_published": False,
                    "current_release_switched": False,
                }
            with (
                exact_runner._hard_deadline(max_seconds),
                httpx.Client(
                    trust_env=False,
                    timeout=min(30, max_seconds),
                    follow_redirects=False,
                ) as client,
            ):
                run = pipeline.run(
                    client,
                    token,
                    json.loads(config_bytes),
                    max_requests=max_requests,
                    max_seconds=max_seconds,
                    pause=0,
                    task_ids=task_ids,
                )
            after_attempts = exact_runner._attempt_counts(pipeline)
            after_states = exact_runner._state_counts(pipeline)
            attempted = {
                api: after_attempts[api] - before_attempts[api]
                for api in sorted(after_attempts | before_attempts)
                if after_attempts[api] != before_attempts[api]
            }
            if (
                config_path.read_bytes() != config_bytes
                or pointer_path.read_bytes() != pointer_bytes
            ):
                raise RuntimeError(
                    "Authority config or CURRENT changed while lock was held"
                )
            _verify_code(verified)
        finally:
            pipeline.close()
    receipt = {
        "schema_version": 1,
        "status": "top10_holders_exact_batch_executed",
        "batch_manifest_sha256": manifest_sha256,
        "all_task_ids_sha256": verified["all_task_ids_sha256"],
        "all_logical_keys_sha256": verified["all_logical_keys_sha256"],
        "authority_config_sha256": expected_config_sha256,
        "release_id": verified["source"]["release_id"],
        "release_manifest_sha256": verified["source"]["release_manifest_sha256"],
        "helper_sha256": helper_sha256(),
        "preparation_sha256": preparation_sha256(),
        "verified_jobs": len(verified["records"]),
        "pair_count": verified["selected"]["pair_count"],
        "api_counts": verified["api_counts"],
        "before_states": before_states,
        "after_states": after_states,
        "attempted_by_api": attempted,
        "upstream_calls": run["requests"],
        "max_upstream_calls": max_requests,
        "max_seconds": max_seconds,
        "elapsed_seconds": run["elapsed_seconds"],
        "exact_task_scope": run["exact_task_scope"],
        "release_published": False,
        "current_release_switched": False,
    }
    receipt["receipt_id"] = digest(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode()
    )
    return receipt


def run_batch(
    manifest,
    manifest_sha256,
    *,
    expected_task_ids_sha256=None,
    expected_config_sha256=None,
    expected_helper_sha256=None,
    expected_preparation_sha256=None,
    expected_release_id=None,
    expected_release_manifest_sha256=None,
    root=None,
    max_requests=None,
    max_seconds=MAX_SECONDS,
    execute=False,
):
    current_helper = helper_sha256()
    current_preparation = preparation_sha256()
    if expected_helper_sha256 and expected_helper_sha256 != current_helper:
        raise ValueError("Explicit helper hash mismatch")
    if (
        expected_preparation_sha256
        and expected_preparation_sha256 != current_preparation
    ):
        raise ValueError("Explicit preparation hash mismatch")
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError(
            "Wall-clock limit must be greater than 0 and at most 90 seconds"
        )
    with ExitStack() as guards:
        if not execute:
            for target in (
                "socket.socket.connect",
                "socket.getaddrinfo",
                "backend.shared.tushare_pipeline.get_secret",
                "backend.shared.runtime_secrets.get_secret",
            ):
                guards.enter_context(
                    patch(
                        target,
                        side_effect=AssertionError("Offline top10 holder batch plan"),
                    )
                )
        verified = preparation.verify_manifest(manifest, manifest_sha256)
        _verify_code(verified)
    jobs = len(verified["records"])
    effective_requests = jobs if max_requests is None else max_requests
    if (
        type(effective_requests) is not int
        or effective_requests != jobs
        or not 1 <= effective_requests <= MAX_UPSTREAM_REQUESTS
    ):
        raise ValueError(
            "Request limit must equal the pinned task count and be at most 360"
        )
    if not execute:
        return {
            "schema_version": 1,
            "status": "plan_only",
            "batch_manifest_sha256": manifest_sha256,
            "all_task_ids_sha256": verified["all_task_ids_sha256"],
            "all_logical_keys_sha256": verified["all_logical_keys_sha256"],
            "authority_config_sha256": verified["source"]["authority_config_sha256"],
            "release_id": verified["source"]["release_id"],
            "release_manifest_sha256": verified["source"]["release_manifest_sha256"],
            "helper_sha256": current_helper,
            "preparation_sha256": current_preparation,
            "verified_jobs": jobs,
            "pair_count": verified["selected"]["pair_count"],
            "api_counts": verified["api_counts"],
            "max_upstream_calls": effective_requests,
            "max_seconds": max_seconds,
            "would_access_authority": False,
            "would_access_credentials": False,
            "would_call_upstream": False,
            "would_write": False,
            "would_publish": False,
        }
    hashes = (
        expected_task_ids_sha256,
        expected_config_sha256,
        expected_helper_sha256,
        expected_preparation_sha256,
        expected_release_manifest_sha256,
    )
    if not all(
        isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for v in hashes
    ) or not preparation.RELEASE_RE.fullmatch(str(expected_release_id or "")):
        raise ValueError(
            "Execute requires pinned release, manifest, task, config, helper and preparation values"
        )
    source = verified["source"]
    if (
        expected_task_ids_sha256 != verified["all_task_ids_sha256"]
        or expected_release_id != source["release_id"]
        or expected_release_manifest_sha256 != source["release_manifest_sha256"]
    ):
        raise ValueError("Explicit execution pins do not match batch manifest")
    if root is None:
        raise ValueError("Execute requires authority root")
    return _execute(
        root,
        verified,
        manifest_sha256,
        expected_config_sha256,
        effective_requests,
        max_seconds,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--expected-task-ids-sha256")
    p.add_argument("--expected-config-sha256")
    p.add_argument("--expected-helper-sha256")
    p.add_argument("--expected-preparation-sha256")
    p.add_argument("--expected-release-id")
    p.add_argument("--expected-release-manifest-sha256")
    p.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    p.add_argument("--max-requests", type=int)
    p.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    print(
        json.dumps(
            run_batch(
                a.manifest,
                a.manifest_sha256,
                expected_task_ids_sha256=a.expected_task_ids_sha256,
                expected_config_sha256=a.expected_config_sha256,
                expected_helper_sha256=a.expected_helper_sha256,
                expected_preparation_sha256=a.expected_preparation_sha256,
                expected_release_id=a.expected_release_id,
                expected_release_manifest_sha256=a.expected_release_manifest_sha256,
                root=a.root,
                max_requests=a.max_requests,
                max_seconds=a.max_seconds,
                execute=a.execute,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
