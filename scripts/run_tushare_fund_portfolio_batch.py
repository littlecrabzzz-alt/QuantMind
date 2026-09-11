#!/usr/bin/env python3
"""Plan or execute one hash-pinned fund_portfolio history batch."""

from __future__ import annotations

import argparse
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
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from scripts import prepare_tushare_fund_portfolio_batch as preparation  # noqa: E402
from scripts import run_tushare_fund_nav_batch as exact_runner  # noqa: E402


MAX_UPSTREAM_REQUESTS = 360
MAX_SECONDS = 90
MIN_FREE_BYTES = 100 * 2**30


def sha(path):
    return digest(Path(path).read_bytes())


def helper_sha256():
    return exact_runner.helper_sha256((__file__, exact_runner.__file__))


def preparation_sha256():
    return exact_runner.preparation_sha256(preparation)


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Authority {label} must be a regular file")
    return path


def _verify_release(root, verified):
    source = verified["source"]
    actual = preparation.fixed_release_evidence(
        root, source["release_id"], source["release_manifest_sha256"]
    )
    if actual != {
        "release_id": source["release_id"],
        "release_manifest_sha256": source["release_manifest_sha256"],
    }:
        raise ValueError("Pinned release evidence changed")


def _verify_authority_jobs(pipeline, records):
    logical_keys = set()
    for expected in records:
        saved = pipeline.db.execute(
            "SELECT id,logical_key,epoch,job,priority,group_name,state,tries "
            "FROM jobs WHERE id=?",
            (expected["task_id"],),
        ).fetchone()
        if saved is None:
            raise ValueError("Verified batch task is missing from authority")
        actual = {
            "task_id": saved["id"],
            "logical_key": saved["logical_key"],
            "epoch": saved["epoch"],
            "priority": saved["priority"],
            "group_name": saved["group_name"],
            "state": saved["state"],
            "tries": saved["tries"],
            "job": json.loads(saved["job"]),
        }
        if actual != expected:
            raise ValueError("Authority task no longer matches the pristine manifest")
        prior = pipeline.db.execute(
            "SELECT 1 FROM attempts WHERE job_id=? LIMIT 1", (expected["task_id"],)
        ).fetchone()
        if prior is not None:
            raise ValueError("Authority task is no longer a first attempt")
        if pipeline.db.execute(
            "SELECT 1 FROM partition_children WHERE parent_id=? LIMIT 1",
            (expected["task_id"],),
        ).fetchone():
            raise ValueError("Authority task is no longer a leaf")
        logical_keys.add(expected["logical_key"])
    for logical_key in logical_keys:
        if pipeline.db.execute(
            "SELECT 1 FROM attempts a JOIN jobs j ON j.id=a.job_id "
            "WHERE j.logical_key=? LIMIT 1",
            (logical_key,),
        ).fetchone():
            raise ValueError("Logical request has a prior attempt in another epoch")
        if pipeline.db.execute(
            "SELECT 1 FROM jobs WHERE logical_key=? AND state<>'pending' LIMIT 1",
            (logical_key,),
        ).fetchone():
            raise ValueError("Logical request has a terminal sibling in another epoch")


def _execute(
    root,
    manifest,
    manifest_sha256,
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
    lock_path = _regular(root / "pipeline.lock", "pipeline lock")
    descriptor = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        database = _regular(root / "pipeline.sqlite", "pipeline database")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
        verified = preparation.verify_manifest(manifest, manifest_sha256)
        if verified["all_task_ids_sha256"] != expected_task_ids_sha256:
            raise ValueError("Explicit task ID inventory hash mismatch")
        if verified["source"]["preparation_sha256"] != preparation_sha256():
            raise ValueError("Manifest preparation hash does not match loaded code")
        _verify_release(root, verified)
        config_path = _regular(root / "pipeline-config.json", "pipeline config")
        config_bytes = config_path.read_bytes()
        if (
            digest(config_bytes) != expected_config_sha256
            or verified["source"]["authority_config_sha256"] != expected_config_sha256
        ):
            raise ValueError("Explicit authority config hash mismatch")
        config = json.loads(config_bytes)
        if preparation.rate_gate(config) != verified["source"]["rate_gate"]:
            raise ValueError("Pinned fund_portfolio rate gate changed")
        pipeline = pipeline_module.Pipeline(
            root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        try:
            _verify_authority_jobs(pipeline, verified["records"])
            task_ids = [record["task_id"] for record in verified["records"]]
            pipeline._install_exact_task_scope(task_ids)
            before_states = exact_runner._state_counts(pipeline)
            before_attempts = exact_runner._attempt_counts(pipeline)
            pointer = _regular(root / "CURRENT.json", "current pointer")
            pointer_before = sha(pointer)
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
                    config,
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
            if _regular(config_path, "pipeline config").read_bytes() != config_bytes:
                raise RuntimeError("Authority config changed while lock was held")
            if sha(_regular(pointer, "current pointer")) != pointer_before:
                raise RuntimeError("Current release pointer changed during exact batch")
        finally:
            pipeline.close()
    receipt = {
        "schema_version": 1,
        "status": "exact_batch_executed",
        "batch_manifest_sha256": manifest_sha256,
        "all_task_ids_sha256": expected_task_ids_sha256,
        "authority_config_sha256": expected_config_sha256,
        "release_id": verified["source"]["release_id"],
        "release_manifest_sha256": verified["source"]["release_manifest_sha256"],
        "api_counts": verified["api_counts"],
        "selected": verified["selected"],
        "selection_reasons": verified["selection_reasons"],
        "boundaries": verified["boundaries"],
        "eligible_jobs": verified["source"]["eligible_jobs"],
        "eligible_task_ids_sha256": verified["source"]["eligible_task_ids_sha256"],
        "rate_gate": verified["source"]["rate_gate"],
        "helper_sha256": helper_sha256(),
        "preparation_sha256": preparation_sha256(),
        "verified_jobs": len(verified["records"]),
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
    receipt["receipt_id"] = digest(json_bytes(receipt))
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
    max_requests=MAX_UPSTREAM_REQUESTS,
    max_seconds=MAX_SECONDS,
    execute=False,
):
    if type(max_requests) is not int or not 1 <= max_requests <= MAX_UPSTREAM_REQUESTS:
        raise ValueError("Upstream request limit must be an integer from 1 to 360")
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError(
            "Wall-clock limit must be greater than 0 and at most 90 seconds"
        )
    current_helper_sha256 = helper_sha256()
    current_preparation_sha256 = preparation_sha256()
    if expected_helper_sha256 and expected_helper_sha256 != current_helper_sha256:
        raise ValueError("Explicit helper hash mismatch")
    if (
        expected_preparation_sha256
        and expected_preparation_sha256 != current_preparation_sha256
    ):
        raise ValueError("Explicit preparation hash mismatch")
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
                        side_effect=AssertionError("Offline fund_portfolio batch plan"),
                    )
                )
        verified = preparation.verify_manifest(manifest, manifest_sha256)
    if verified["source"]["preparation_sha256"] != current_preparation_sha256:
        raise ValueError("Manifest preparation hash does not match loaded code")
    if not execute:
        return {
            "schema_version": 1,
            "status": "plan_only",
            "batch_manifest_sha256": manifest_sha256,
            "all_task_ids_sha256": verified["all_task_ids_sha256"],
            "authority_config_sha256": verified["source"]["authority_config_sha256"],
            "release_id": verified["source"]["release_id"],
            "release_manifest_sha256": verified["source"]["release_manifest_sha256"],
            "api_counts": verified["api_counts"],
            "selected": verified["selected"],
            "selection_reasons": verified["selection_reasons"],
            "boundaries": verified["boundaries"],
            "eligible_jobs": verified["source"]["eligible_jobs"],
            "eligible_task_ids_sha256": verified["source"]["eligible_task_ids_sha256"],
            "rate_gate": verified["source"]["rate_gate"],
            "helper_sha256": current_helper_sha256,
            "preparation_sha256": current_preparation_sha256,
            "verified_jobs": len(verified["records"]),
            "max_upstream_calls": max_requests,
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
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in hashes
    ) or not preparation.RELEASE_RE.fullmatch(str(expected_release_id or "")):
        raise ValueError(
            "Execute requires pinned release, manifest, task, config, helper and "
            "preparation values"
        )
    if (
        verified["source"]["release_id"] != expected_release_id
        or verified["source"]["release_manifest_sha256"]
        != expected_release_manifest_sha256
    ):
        raise ValueError("Explicit fixed release does not match batch manifest")
    if root is None:
        raise ValueError("Execute requires authority root")
    return _execute(
        root,
        manifest,
        manifest_sha256,
        expected_task_ids_sha256,
        expected_config_sha256,
        max_requests,
        max_seconds,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-task-ids-sha256")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--expected-preparation-sha256")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-release-manifest-sha256")
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--max-requests", type=int, default=MAX_UPSTREAM_REQUESTS)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = run_batch(
        args.manifest,
        args.manifest_sha256,
        expected_task_ids_sha256=args.expected_task_ids_sha256,
        expected_config_sha256=args.expected_config_sha256,
        expected_helper_sha256=args.expected_helper_sha256,
        expected_preparation_sha256=args.expected_preparation_sha256,
        expected_release_id=args.expected_release_id,
        expected_release_manifest_sha256=args.expected_release_manifest_sha256,
        root=args.root,
        max_requests=args.max_requests,
        max_seconds=args.max_seconds,
        execute=args.execute,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
