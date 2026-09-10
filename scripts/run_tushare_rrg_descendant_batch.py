#!/usr/bin/env python3
"""Plan or execute one hash-pinned exact batch of RRG task descendants."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
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
from scripts import import_tushare_rrg_acquisition_shard as importer  # noqa: E402
from scripts import run_tushare_rrg_acquisition_batch as exact_runner  # noqa: E402

MAX_DESCENDANTS = 5000
MAX_UPSTREAM_REQUESTS = 360
MAX_SECONDS = 90


def sha(path):
    return digest(Path(path).read_bytes())


def helper_sha256():
    return sha(Path(__file__).resolve())


def _source(batch_manifest, manifest_sha256, audit_report):
    verified = importer.verify_batch(
        batch_manifest, manifest_sha256, audit_report, shard=None
    )
    parents = [
        row for row in exact_runner._records(verified) if row["api_name"] == "etf_limit"
    ]
    if not parents or len(parents) > 100:
        raise ValueError("Expected 1..100 etf_limit source parents")
    return verified, parents


def _rows_by_id(db, task_ids):
    placeholders = ",".join("?" for _ in task_ids)
    rows = db.execute(
        "SELECT id,logical_key,epoch,group_name,job,priority,state,tries "
        f"FROM jobs WHERE id IN ({placeholders})",
        task_ids,
    ).fetchall()
    return {row["id"]: row for row in rows}


def _verify_parents(db, parents):
    saved = _rows_by_id(db, [row["task_id"] for row in parents])
    for expected in parents:
        row = saved.get(expected["task_id"])
        if row is None:
            raise ValueError("Verified source parent is missing from authority")
        actual = {
            "task_id": row["id"],
            "logical_key": row["logical_key"],
            "epoch": row["epoch"],
            "group_name": row["group_name"],
            "job": json.loads(row["job"]),
        }
        if actual != {key: expected[key] for key in actual}:
            raise ValueError("Authority source parent identity mismatch")
    return saved


def _counts(rows, field):
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def _snapshot(db, parents):
    saved_parents = _verify_parents(db, parents)
    parent_ids = [row["task_id"] for row in parents]
    placeholders = ",".join("?" for _ in parent_ids)
    roots = [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT parent_id FROM partition_children "
            f"WHERE parent_id IN ({placeholders}) ORDER BY parent_id",
            parent_ids,
        )
    ]
    if not roots:
        raise ValueError("Verified etf_limit parents have no descendants")
    root_placeholders = ",".join("?" for _ in roots)
    descendants = [
        row[0]
        for row in db.execute(
            f"""
            WITH RECURSIVE descendants(task_id) AS (
              SELECT child_id FROM partition_children
              WHERE parent_id IN ({root_placeholders})
              UNION
              SELECT c.child_id FROM partition_children c
              JOIN descendants d ON c.parent_id=d.task_id
            )
            SELECT task_id FROM descendants ORDER BY task_id
            """,
            roots,
        )
    ]
    if not 1 <= len(descendants) <= MAX_DESCENDANTS:
        raise ValueError("Descendant task set exceeds the explicit job limit")
    descendant_set = set(descendants)
    nodes = _rows_by_id(db, descendants)
    if set(nodes) != descendant_set:
        raise ValueError("Descendant graph references a missing authority task")
    edge_parents = roots + descendants
    edge_placeholders = ",".join("?" for _ in edge_parents)
    edges = [
        tuple(row)
        for row in db.execute(
            "SELECT parent_id,child_id FROM partition_children "
            f"WHERE parent_id IN ({edge_placeholders}) ORDER BY parent_id,child_id",
            edge_parents,
        )
        if row[1] in descendant_set
    ]
    adjacency = {task_id: [] for task_id in roots + descendants}
    for parent_id, child_id in edges:
        adjacency[parent_id].append(child_id)
    color = {}
    topological = []

    def visit(task_id):
        if color.get(task_id) == 1:
            raise ValueError("Descendant graph contains a cycle")
        if color.get(task_id) == 2:
            return
        color[task_id] = 1
        for child_id in adjacency[task_id]:
            visit(child_id)
        color[task_id] = 2
        topological.append(task_id)

    for task_id in roots:
        visit(task_id)
    depth = dict.fromkeys(roots, 0)
    root_membership = {task_id: {task_id} for task_id in roots}
    for parent_id in reversed(topological):
        for child_id in adjacency[parent_id]:
            proposed = depth[parent_id] + 1
            depth[child_id] = min(depth.get(child_id, proposed), proposed)
            root_membership.setdefault(child_id, set()).update(
                root_membership[parent_id]
            )
    if set(depth) != set(roots) | descendant_set:
        raise ValueError("Descendant graph is not fully rooted in the source batch")
    attempts = dict(
        db.execute(
            "SELECT job_id,COUNT(*) FROM attempts "
            f"WHERE job_id IN ({','.join('?' for _ in roots + descendants)}) "
            "GROUP BY job_id",
            roots + descendants,
        )
    )
    split_rows = {
        row["parent_id"]: row
        for row in db.execute(
            "SELECT parent_id,method,status,gap,coverage_proven "
            f"FROM partition_splits WHERE parent_id IN ({edge_placeholders})",
            edge_parents,
        )
    }
    details = []
    for task_id in roots + descendants:
        row = saved_parents[task_id] if task_id in saved_parents else nodes[task_id]
        job = json.loads(row["job"])
        if (
            job.get("api_name") != "etf_limit"
            or row["group_name"] != "cross_asset_extra"
        ):
            raise ValueError("Descendant escaped the etf_limit Pipeline scope")
        split = split_rows.get(task_id)
        details.append(
            {
                "task_id": task_id,
                "depth": depth[task_id],
                "root_task_ids": sorted(root_membership[task_id]),
                "logical_key": row["logical_key"],
                "epoch": row["epoch"],
                "group_name": row["group_name"],
                "job": job,
                "state": row["state"],
                "priority": row["priority"],
                "tries": row["tries"],
                "attempt_rows": attempts.get(task_id, 0),
                "split": (
                    {
                        "method": split["method"],
                        "status": split["status"],
                        "gap": split["gap"],
                        "coverage_proven": bool(split["coverage_proven"]),
                    }
                    if split
                    else None
                ),
            }
        )
    details.sort(key=lambda row: (row["depth"], row["task_id"]))
    descendant_details = [row for row in details if row["depth"] > 0]
    identities = [
        {
            key: row[key]
            for key in ("task_id", "logical_key", "epoch", "group_name", "job")
        }
        for row in descendant_details
    ]
    task_set = {
        "parents": roots,
        "descendants": sorted(identities, key=lambda row: row["task_id"]),
        "edges": [
            {"parent_task_id": parent_id, "task_id": child_id}
            for parent_id, child_id in edges
        ],
    }
    layers = []
    for layer in sorted(set(depth.values())):
        rows = [row for row in details if row["depth"] == layer]
        layers.append(
            {
                "depth": layer,
                "tasks": len(rows),
                "task_ids": [row["task_id"] for row in rows],
                "states": _counts(rows, "state"),
                "priorities": _counts(rows, "priority"),
                "tries": _counts(rows, "tries"),
                "attempt_rows": _counts(rows, "attempt_rows"),
            }
        )
    return {
        "roots": roots,
        "descendant_ids": descendants,
        "task_set_sha256": digest(json_bytes(task_set)),
        "tasks": details,
        "layers": layers,
        "edges": len(edges),
        "pending_descendants": sum(
            row["state"] == "pending" for row in descendant_details
        ),
    }


def _authority_sha(schema_version, marker_sha256, verified, roots):
    return digest(
        json_bytes(
            {
                "schema_version": schema_version,
                "authority_marker_sha256": marker_sha256,
                "batch_manifest_sha256": verified["manifest_sha256"],
                "source_task_ids_sha256": verified["all_task_ids_sha256"],
                "descendant_roots": roots,
            }
        )
    )


def _inspect(
    root, batch_manifest, manifest_sha256, audit_report, max_requests, max_seconds
):
    root = Path(root)
    marker = exact_runner._regular(root / "ENABLED", "enable marker")
    config = exact_runner._regular(root / "pipeline-config.json", "pipeline config")
    database = exact_runner._regular(root / "pipeline.sqlite", "pipeline database")
    verified, parents = _source(batch_manifest, manifest_sha256, audit_report)
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]
        if schema_version != 6:
            raise ValueError("Authority pipeline schema must already be version 6")
        snapshot = _snapshot(db, parents)
    finally:
        db.close()
    marker_sha256 = sha(marker)
    return {
        "schema_version": 1,
        "status": "plan_only",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "authority_schema_version": schema_version,
        "authority_sha256": _authority_sha(
            schema_version, marker_sha256, verified, snapshot["roots"]
        ),
        "authority_marker_sha256": marker_sha256,
        "authority_config_sha256": sha(config),
        "helper_sha256": helper_sha256(),
        "batch_manifest_sha256": verified["manifest_sha256"],
        "source_task_ids_sha256": verified["all_task_ids_sha256"],
        "source_etf_parent_tasks": len(parents),
        "descendant_root_tasks": len(snapshot["roots"]),
        "descendant_tasks": len(snapshot["descendant_ids"]),
        "pending_descendant_tasks": snapshot["pending_descendants"],
        "descendant_edges": snapshot["edges"],
        "task_set_sha256": snapshot["task_set_sha256"],
        "layers": snapshot["layers"],
        "tasks": snapshot["tasks"],
        "free_bytes": shutil.disk_usage(root).free,
        "max_upstream_calls": max_requests,
        "max_seconds": max_seconds,
        "selection": "all current descendants; execution selects only pending IDs from this hash-pinned set",
        "authority_accessed_read_only": True,
        "credentials_accessed": False,
        "upstream_calls": 0,
        "release_published": False,
        "current_release_switched": False,
    }


def _execute(
    root,
    batch_manifest,
    manifest_sha256,
    audit_report,
    expected_authority_sha256,
    expected_config_sha256,
    expected_helper_sha256,
    expected_task_set_sha256,
    max_requests,
    max_seconds,
):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    marker = exact_runner._regular(root / "ENABLED", "enable marker")
    lock_path = root / "pipeline.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe pipeline lock")
    descriptor = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        exact_runner._schema6(root)
        verified, parents = _source(batch_manifest, manifest_sha256, audit_report)
        config_path = exact_runner._regular(
            root / "pipeline-config.json", "pipeline config"
        )
        config_bytes = config_path.read_bytes()
        if digest(config_bytes) != expected_config_sha256:
            raise ValueError("Explicit authority config hash mismatch")
        config = json.loads(config_bytes)
        pipeline = pipeline_module.Pipeline(root, verified["catalog"])
        try:
            snapshot = _snapshot(pipeline.db, parents)
            actual_authority_sha256 = _authority_sha(
                6, sha(marker), verified, snapshot["roots"]
            )
            if actual_authority_sha256 != expected_authority_sha256:
                raise ValueError("Explicit authority hash mismatch")
            if snapshot["task_set_sha256"] != expected_task_set_sha256:
                raise ValueError("Explicit descendant task set hash mismatch")
            task_ids = snapshot["descendant_ids"]
            pipeline._install_exact_task_scope(task_ids)
            before_states = exact_runner._state_counts(pipeline)
            before_attempts = exact_runner._attempt_counts(pipeline)
            base = {
                "schema_version": 1,
                "authority_sha256": actual_authority_sha256,
                "authority_config_sha256": expected_config_sha256,
                "helper_sha256": expected_helper_sha256,
                "batch_manifest_sha256": verified["manifest_sha256"],
                "source_task_ids_sha256": verified["all_task_ids_sha256"],
                "task_set_sha256": snapshot["task_set_sha256"],
                "verified_descendant_tasks": len(task_ids),
                "pending_descendant_tasks": snapshot["pending_descendants"],
                "upstream_calls": 0,
                "max_upstream_calls": max_requests,
                "max_seconds": max_seconds,
                "release_published": False,
                "current_release_switched": False,
            }
            if not snapshot["pending_descendants"]:
                return {**base, "status": "no_pending_descendants"}
            if shutil.disk_usage(root).free < 100 * 2**30:
                return {**base, "status": "blocked_disk_reserve"}
            pointer = root / "CURRENT.json"
            pointer_before = (
                sha(exact_runner._regular(pointer, "current pointer"))
                if pointer.exists()
                else None
            )
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {**base, "status": "blocked_missing_token"}
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
            after_snapshot = _snapshot(pipeline.db, parents)
            pointer_after = (
                sha(exact_runner._regular(pointer, "current pointer"))
                if pointer.exists()
                else None
            )
            if (
                exact_runner._regular(config_path, "pipeline config").read_bytes()
                != config_bytes
            ):
                raise RuntimeError("Authority config changed while lock was held")
            if pointer_after != pointer_before:
                raise RuntimeError("Current release pointer changed during exact batch")
        finally:
            pipeline.close()
    receipt = {
        **base,
        "status": "exact_descendant_batch_executed",
        "before_states": before_states,
        "after_states": after_states,
        "attempted_by_api": attempted,
        "upstream_calls": run["requests"],
        "max_upstream_calls": max_requests,
        "max_seconds": max_seconds,
        "elapsed_seconds": run["elapsed_seconds"],
        "exact_task_scope": run["exact_task_scope"],
        "scoped_jobs": run["scoped_jobs"],
        "after_descendant_tasks": len(after_snapshot["descendant_ids"]),
        "after_pending_descendant_tasks": after_snapshot["pending_descendants"],
        "after_task_set_sha256": after_snapshot["task_set_sha256"],
        "pipeline_normalization_attempt_retry_and_split_reused": True,
        "account_api_and_daily_quota_gates_reused": True,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def run_batch(
    batch_manifest,
    manifest_sha256,
    audit_report,
    *,
    root,
    expected_authority_sha256=None,
    expected_config_sha256=None,
    expected_helper_sha256=None,
    expected_task_set_sha256=None,
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
        with (
            patch(
                "backend.shared.tushare_pipeline.get_secret",
                side_effect=AssertionError("Plan-only must not read credentials"),
            ),
            patch(
                "backend.shared.runtime_secrets.get_secret",
                side_effect=AssertionError("Plan-only must not read credentials"),
            ),
            patch(
                "socket.socket.connect",
                side_effect=AssertionError("Plan-only must not use the network"),
            ),
            patch(
                "socket.getaddrinfo",
                side_effect=AssertionError("Plan-only must not use the network"),
            ),
        ):
            return _inspect(
                root,
                batch_manifest,
                manifest_sha256,
                audit_report,
                max_requests,
                max_seconds,
            )
    hashes = (
        expected_authority_sha256,
        expected_config_sha256,
        expected_helper_sha256,
        expected_task_set_sha256,
    )
    if not all(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in hashes
    ):
        raise ValueError(
            "Execute requires pinned authority, config, helper and task-set SHA-256 values"
        )
    return _execute(
        root,
        batch_manifest,
        manifest_sha256,
        audit_report,
        expected_authority_sha256,
        expected_config_sha256,
        expected_helper_sha256,
        expected_task_set_sha256,
        max_requests,
        max_seconds,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--expected-authority-sha256")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--expected-task-set-sha256")
    parser.add_argument("--max-requests", type=int, default=360)
    parser.add_argument("--max-seconds", type=float, default=90)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = run_batch(
            args.batch_manifest,
            args.manifest_sha256,
            args.audit_report,
            root=args.root,
            expected_authority_sha256=args.expected_authority_sha256,
            expected_config_sha256=args.expected_config_sha256,
            expected_helper_sha256=args.expected_helper_sha256,
            expected_task_set_sha256=args.expected_task_set_sha256,
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
