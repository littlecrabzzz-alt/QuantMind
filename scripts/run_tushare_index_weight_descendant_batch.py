#!/usr/bin/env python3
"""Plan or execute one hash-pinned index_weight sibling-pair batch."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, contextmanager, ExitStack
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
from scripts import prepare_tushare_index_weight_descendant_batch as preparation  # noqa: E402
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


@contextmanager
def _shared_lock(root):
    descriptor = os.open(
        _regular(Path(root) / "pipeline.lock", "pipeline lock"),
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def _graph_snapshot(db, parent_ids):
    if not parent_ids:
        raise ValueError("Missing descendant parents")
    placeholders = ",".join("?" for _ in parent_ids)
    ids = [row[0] for row in db.execute(
        f"""WITH RECURSIVE family(id) AS (
        SELECT id FROM jobs WHERE id IN ({placeholders})
        UNION SELECT pc.child_id FROM partition_children pc JOIN family f ON pc.parent_id=f.id
        ) SELECT id FROM family ORDER BY id""", parent_ids
    )]
    if not set(parent_ids).issubset(ids):
        raise ValueError("A pinned split parent is missing")
    node_placeholders = ",".join("?" for _ in ids)
    rows = db.execute(
        "SELECT j.id,j.logical_key,j.epoch,j.group_name,j.job,j.priority,j.state,j.tries,j.result,"
        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) attempts "
        f"FROM jobs j WHERE j.id IN ({node_placeholders}) ORDER BY j.id", ids
    ).fetchall()
    if len(rows) != len(ids):
        raise ValueError("Descendant graph references a missing task")
    for row in rows:
        job = json.loads(row["job"])
        if job.get("api_name") != preparation.API or row["group_name"] != preparation.GROUP or row["epoch"] != preparation.EPOCH:
            raise ValueError("Descendant graph escaped the index_weight family")
    edges = [dict(row) for row in db.execute(
        "SELECT parent_id,child_id FROM partition_children "
        f"WHERE parent_id IN ({node_placeholders}) ORDER BY parent_id,child_id", ids
    )]
    adjacency = {task_id: [] for task_id in ids}
    for edge in edges:
        if edge["child_id"] not in adjacency:
            raise ValueError("Descendant edge references a missing task")
        adjacency[edge["parent_id"]].append(edge["child_id"])
    color = {}
    def visit(task_id):
        if color.get(task_id) == 1:
            raise ValueError("Descendant graph contains a cycle")
        if color.get(task_id) == 2:
            return
        color[task_id] = 1
        for child in adjacency[task_id]:
            visit(child)
        color[task_id] = 2
    for parent_id in parent_ids:
        visit(parent_id)
    splits = [dict(row) for row in db.execute(
        "SELECT parent_id,method,expected_children,coverage_proven,evidence,status,gap "
        f"FROM partition_splits WHERE parent_id IN ({node_placeholders}) ORDER BY parent_id", ids
    )]
    payload = {
        "nodes": [{
            "task_id": row["id"], "logical_key": row["logical_key"], "epoch": row["epoch"],
            "group_name": row["group_name"], "job": json.loads(row["job"]), "priority": row["priority"],
            "state": row["state"], "tries": row["tries"], "result": json.loads(row["result"]) if row["result"] else None,
            "attempts": row["attempts"],
        } for row in rows],
        "edges": edges,
        "splits": [{**row, "coverage_proven": bool(row["coverage_proven"]), "evidence": json.loads(row["evidence"])} for row in splits],
    }
    return {"sha256": digest(json_bytes(payload)), "tasks": len(rows), "edges": len(edges), "payload": payload}


def _verify_live(pipeline, verified):
    pairs = []
    for expected in verified["pairs"]:
        parent_id = expected["parent"]["task_id"]
        parent = pipeline.db.execute(
            "SELECT p.id,p.logical_key,p.epoch,p.priority,p.group_name,p.job,p.state,p.tries,p.result,"
            "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=p.id) attempts,"
            "s.method,s.expected_children,s.coverage_proven,s.evidence,s.status split_status,s.gap "
            "FROM jobs p JOIN partition_splits s ON s.parent_id=p.id WHERE p.id=?", (parent_id,)
        ).fetchone()
        if parent is None or preparation._pair(pipeline.db, parent) != expected:
            raise ValueError("Authority sibling pair changed after preparation")
        pairs.append(expected)
    history, ht, hl, hr = preparation.history_inventory(pipeline.root)
    if history != verified["source"]["history_inventory"]:
        raise ValueError("Historical batch inventory changed after preparation")
    logical_keys = [row["logical_key"] for row in verified["records"]]
    placeholders = ",".join("?" for _ in logical_keys)
    prior = pipeline.db.execute(
        "SELECT 1 FROM jobs j "
        f"WHERE j.logical_key IN ({placeholders}) "
        "AND EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=j.id) LIMIT 1",
        logical_keys,
    ).fetchone()
    if prior is not None:
        raise ValueError("Selected logical request gained an attempt")
    for row in verified["records"]:
        if row["task_id"] in ht or row["logical_key"] in hl or row["request_signature_sha256"] in hr:
            raise ValueError("Selected sibling pair now overlaps batch history")
    return pairs


def inspect_authority(root, verified):
    root = Path(root).resolve()
    with _shared_lock(root):
        preparation.fixed_release_evidence(
            root,
            verified["source"]["release_id"],
            verified["source"]["release_manifest_sha256"],
        )
        config = _regular(root / "pipeline-config.json", "pipeline config")
        if sha(config) != verified["source"]["authority_config_sha256"]:
            raise ValueError("Authority config changed after preparation")
        db = sqlite3.connect(
            _regular(root / "pipeline.sqlite", "pipeline database").as_uri()
            + "?mode=ro",
            uri=True,
            timeout=1,
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
            holder = type("ReadOnlyPipeline", (), {"db": db, "root": root})()
            _verify_live(holder, verified)
            graph = _graph_snapshot(
                db, [pair["parent"]["task_id"] for pair in verified["pairs"]]
            )
        finally:
            db.close()
    return {
        "schema_version": 1,
        "status": "authority_inspected_read_only",
        "graph_sha256": graph["sha256"],
        "graph_tasks": graph["tasks"],
        "graph_edges": graph["edges"],
        "history_inventory_sha256": verified["source"]["history_inventory"][
            "inventory_sha256"
        ],
        "authority_config_sha256": verified["source"]["authority_config_sha256"],
        "credentials_accessed": False,
        "upstream_calls": 0,
        "authority_writes": 0,
    }


def _execute(root, verified, manifest_sha256, expected, max_seconds):
    root = Path(root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    root = root.resolve()
    pipeline_module.authority()
    _regular(root / "ENABLED", "enable marker")
    descriptor = os.open(_regular(root / "pipeline.lock", "pipeline lock"), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(sqlite3.connect(_regular(root / "pipeline.sqlite", "pipeline database").as_uri() + "?mode=ro", uri=True)) as check:
            if check.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
        preparation.fixed_release_evidence(root, verified["source"]["release_id"], verified["source"]["release_manifest_sha256"])
        config_path = _regular(root / "pipeline-config.json", "pipeline config")
        config_bytes = config_path.read_bytes()
        if digest(config_bytes) != expected["config"] or verified["source"]["authority_config_sha256"] != expected["config"]:
            raise ValueError("Explicit authority config hash mismatch")
        config = json.loads(config_bytes)
        if preparation.rate_gate(config) != verified["source"]["rate_gate"]:
            raise ValueError("Pinned index_weight rate gate changed")
        catalog = json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        pipeline = pipeline_module.Pipeline(root, catalog)
        try:
            _verify_live(pipeline, verified)
            task_ids = [row["task_id"] for row in verified["records"]]
            parent_ids = [pair["parent"]["task_id"] for pair in verified["pairs"]]
            before_graph = _graph_snapshot(pipeline.db, parent_ids)
            if before_graph["sha256"] != expected["graph"]:
                raise ValueError("Explicit family graph hash mismatch")
            pipeline._install_exact_task_scope(task_ids)
            before_states = exact_runner._state_counts(pipeline)
            before_attempts = exact_runner._attempt_counts(pipeline)
            pointer = _regular(root / "CURRENT.json", "current pointer")
            pointer_before = sha(pointer)
            base = {
                "schema_version": 1, "batch_manifest_sha256": manifest_sha256,
                "all_task_ids_sha256": verified["all_task_ids_sha256"], "pair_set_sha256": verified["pair_set_sha256"],
                "before_graph_sha256": before_graph["sha256"], "verified_jobs": len(task_ids), "verified_pairs": len(parent_ids),
                "upstream_calls": 0, "release_published": False, "current_release_switched": False,
                "sibling_pair_atomicity_claimed": False, "coverage_complete_claimed": False,
            }
            if shutil.disk_usage(root).free < MIN_FREE_BYTES:
                return {**base, "status": "blocked_disk_reserve"}
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {**base, "status": "blocked_missing_token"}
            with exact_runner._hard_deadline(max_seconds), httpx.Client(trust_env=False, timeout=min(30, max_seconds), follow_redirects=False) as client:
                run = pipeline.run(client, token, config, max_requests=len(task_ids), max_seconds=max_seconds, pause=0, task_ids=task_ids)
            after_attempts = exact_runner._attempt_counts(pipeline)
            after_states = exact_runner._state_counts(pipeline)
            after_graph = _graph_snapshot(pipeline.db, parent_ids)
            if config_path.read_bytes() != config_bytes or sha(pointer) != pointer_before:
                raise RuntimeError("Authority config or CURRENT changed during exact batch")
        finally:
            pipeline.close()
    receipt = {
        **base, "status": "exact_descendant_batch_executed", "before_states": before_states,
        "after_states": after_states, "attempted_by_api": {api: after_attempts[api] - before_attempts[api] for api in sorted(after_attempts | before_attempts) if after_attempts[api] != before_attempts[api]},
        "upstream_calls": run["requests"], "max_upstream_calls": len(task_ids), "max_seconds": max_seconds,
        "elapsed_seconds": run["elapsed_seconds"], "exact_task_scope": run["exact_task_scope"],
        "after_graph_sha256": after_graph["sha256"], "before_graph_tasks": before_graph["tasks"], "after_graph_tasks": after_graph["tasks"],
        "new_descendant_tasks": after_graph["tasks"] - before_graph["tasks"], "after_graph_edges": after_graph["edges"],
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def run_batch(manifest, manifest_sha256, *, root=None, expected_task_ids_sha256=None, expected_config_sha256=None, expected_helper_sha256=None, expected_preparation_sha256=None, expected_release_id=None, expected_release_manifest_sha256=None, expected_pair_set_sha256=None, expected_history_inventory_sha256=None, expected_graph_sha256=None, max_requests=None, max_seconds=MAX_SECONDS, inspect=False, execute=False):
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError("Wall-clock limit must be greater than 0 and at most 90 seconds")
    current_helper, current_preparation = helper_sha256(), preparation_sha256()
    if expected_helper_sha256 and expected_helper_sha256 != current_helper:
        raise ValueError("Explicit helper hash mismatch")
    if expected_preparation_sha256 and expected_preparation_sha256 != current_preparation:
        raise ValueError("Explicit preparation hash mismatch")
    if inspect and execute:
        raise ValueError("inspect and execute are mutually exclusive")
    with ExitStack() as guards:
        if not execute:
            for target in ("socket.socket.connect", "socket.getaddrinfo", "backend.shared.tushare_pipeline.get_secret", "backend.shared.runtime_secrets.get_secret"):
                guards.enter_context(patch(target, side_effect=AssertionError("Offline index_weight descendant plan")))
        verified = preparation.verify_manifest(manifest, manifest_sha256)
    task_count = len(verified["records"])
    requested = task_count if max_requests is None else max_requests
    if type(requested) is not int or requested != task_count or requested > MAX_UPSTREAM_REQUESTS:
        raise ValueError("max_requests must equal the selected leaf count")
    if verified["source"]["preparation_sha256"] != current_preparation:
        raise ValueError("Manifest preparation hash does not match loaded code")
    before = {
        "schema_version": 1, "status": "plan_only", "batch_manifest_sha256": manifest_sha256,
        "all_task_ids_sha256": verified["all_task_ids_sha256"], "pair_set_sha256": verified["pair_set_sha256"],
        "history_inventory_sha256": verified["source"]["history_inventory"]["inventory_sha256"],
        "helper_sha256": current_helper, "preparation_sha256": current_preparation,
        "verified_jobs": task_count, "verified_pairs": verified["pair_count"], "max_upstream_calls": requested,
        "max_seconds": max_seconds, "boundaries": verified["boundaries"],
    }
    if not execute:
        if inspect:
            if root is None:
                raise ValueError("Authority inspection requires root")
            return {**before, **inspect_authority(root, verified)}
        return {**before, "would_access_authority": False, "would_access_credentials": False, "would_call_upstream": False, "would_write": False, "would_publish": False}
    pins = (expected_task_ids_sha256, expected_config_sha256, expected_helper_sha256, expected_preparation_sha256, expected_release_manifest_sha256, expected_pair_set_sha256, expected_history_inventory_sha256, expected_graph_sha256)
    if not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) for value in pins) or not preparation.RELEASE_RE.fullmatch(str(expected_release_id or "")):
        raise ValueError("Execute requires every explicit SHA and release pin")
    checks = {
        "tasks": verified["all_task_ids_sha256"] == expected_task_ids_sha256,
        "pairs": verified["pair_set_sha256"] == expected_pair_set_sha256,
        "history": verified["source"]["history_inventory"]["inventory_sha256"] == expected_history_inventory_sha256,
        "release": verified["source"]["release_id"] == expected_release_id and verified["source"]["release_manifest_sha256"] == expected_release_manifest_sha256,
    }
    if not all(checks.values()):
        raise ValueError("Explicit execution pins do not match manifest")
    if root is None:
        raise ValueError("Execute requires authority root")
    return _execute(root, verified, manifest_sha256, {"config": expected_config_sha256, "graph": expected_graph_sha256}, max_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    for name in ("task-ids", "config", "helper", "preparation", "release-manifest", "pair-set", "history-inventory", "graph"):
        parser.add_argument("--expected-" + name + "-sha256")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--inspect-authority", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = run_batch(args.manifest, args.manifest_sha256, root=args.root, expected_task_ids_sha256=args.expected_task_ids_sha256, expected_config_sha256=args.expected_config_sha256, expected_helper_sha256=args.expected_helper_sha256, expected_preparation_sha256=args.expected_preparation_sha256, expected_release_id=args.expected_release_id, expected_release_manifest_sha256=args.expected_release_manifest_sha256, expected_pair_set_sha256=args.expected_pair_set_sha256, expected_history_inventory_sha256=args.expected_history_inventory_sha256, expected_graph_sha256=args.expected_graph_sha256, max_requests=args.max_requests, max_seconds=args.max_seconds, inspect=args.inspect_authority, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
