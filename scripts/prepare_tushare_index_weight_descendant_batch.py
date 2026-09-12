#!/usr/bin/env python3
"""Freeze pristine index_weight date-split children as complete sibling pairs."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_rate_policy import resolved_api_rate  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS  # noqa: E402
from scripts import prepare_tushare_index_weight_batch as root_preparation  # noqa: E402


API = "index_weight"
EPOCH = "history"
GROUP = "market"
MAX_BATCH_JOBS = 360
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
DAY_RE = re.compile(r"[0-9]{8}")
CODE_RE = re.compile(r"[A-Za-z0-9]+\.[A-Z]+")
SELECTION = "oldest_pristine_complete_direct_sibling_pairs"


def sha(path):
    return digest(Path(path).read_bytes())


def preparation_sha256():
    return sha(Path(__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


@contextmanager
def _read_lock(root):
    path = _regular(Path(root) / "pipeline.lock", "Pipeline lock")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def fixed_release_evidence(root, release_id, manifest_sha256):
    root = Path(root).resolve()
    match = RELEASE_RE.fullmatch(str(release_id))
    if not match or match.group(1) != manifest_sha256:
        raise ValueError("Release ID must be derived from its manifest SHA-256")
    pointer = json.loads(_regular(root / "CURRENT.json", "Current pointer").read_bytes())
    if pointer != {"manifest_sha256": manifest_sha256, "release_id": release_id}:
        raise ValueError("Explicit release is not the current fixed release")
    manifest = _regular(root / "releases" / release_id / "manifest.json", "Release manifest")
    if sha(manifest) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    return {"release_id": release_id, "release_manifest_sha256": manifest_sha256}


def rate_gate(config):
    if config.get("rate_policy") != "tiered_v1" or config.get("requests_per_minute") != 500 or config.get("rollout_account_rpm") != 500:
        raise ValueError("index_weight descendant batch requires the tiered 500 rpm gate")
    resolved = resolved_api_rate(API, EXTENDED_CONTRACTS[API], config)
    if resolved.get("rpm") != 500 or resolved.get("review_required"):
        raise ValueError("index_weight permission does not resolve to reviewed 500 rpm")
    return {"rate_policy": "tiered_v1", "account_rpm": 500, "rollout_account_rpm": 500, "api_rpm": 500, "rate_source": resolved["source"]}


def request_signature(job):
    return digest(
        json_bytes(
            {
                "api_name": job["api_name"],
                "params": job["params"],
                "fields": job.get("fields"),
            }
        )
    )


def history_inventory(root):
    root = Path(root)
    patterns = (
        "validation/index-weight-batch-*/batch-*-manifest.json",
        "validation/index-weight-descendant-batch-*/batch-*-manifest.json",
    )
    task_ids, logical_keys, requests, manifests = set(), set(), set(), []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            path = _regular(path, "Historical batch manifest")
            value = json.loads(path.read_bytes())
            records = value.get("records", []) if isinstance(value, dict) else []
            selected = [row for row in records if row.get("job", {}).get("api_name") == API]
            if not selected:
                continue
            manifests.append({"path": str(path.relative_to(root)), "sha256": sha(path), "records": len(selected)})
            for row in selected:
                task_ids.add(row["task_id"])
                logical_keys.add(row["logical_key"])
                requests.add(request_signature(row["job"]))
    payload = {
        "manifests": manifests,
        "task_ids_sha256": digest(json_bytes(sorted(task_ids))),
        "logical_keys_sha256": digest(json_bytes(sorted(logical_keys))),
        "requests_sha256": digest(json_bytes(sorted(requests))),
        "tasks": len(task_ids),
        "logical_keys": len(logical_keys),
        "requests": len(requests),
    }
    payload["inventory_sha256"] = digest(json_bytes(payload))
    return payload, task_ids, logical_keys, requests


def _identity(job, epoch):
    logical_key = digest(json_bytes(job))
    return logical_key, digest(json_bytes([logical_key, epoch]))


def _result_status(raw):
    try:
        return json.loads(raw or "null").get("status")
    except (AttributeError, json.JSONDecodeError):
        return None


def _pair(db, parent):
    parent_job = json.loads(parent["job"])
    children = db.execute(
        "SELECT j.id,j.logical_key,j.epoch,j.priority,j.group_name,j.job,j.state,j.tries,j.result,"
        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) attempts,"
        "(SELECT COUNT(*) FROM partition_children pc2 WHERE pc2.child_id=j.id) parent_count,"
        "(SELECT COUNT(*) FROM partition_children pc3 WHERE pc3.parent_id=j.id) child_count "
        "FROM partition_children pc JOIN jobs j ON j.id=pc.child_id WHERE pc.parent_id=? ORDER BY j.id",
        (parent["id"],),
    ).fetchall()
    if len(children) != 2:
        return None
    expected_params = pipeline_module.Pipeline.date_children(None, parent_job)
    expected_jobs = sorted(json_bytes({**parent_job, "params": params}) for params in (expected_params or []))
    actual_jobs = sorted(json_bytes(json.loads(row["job"])) for row in children)
    if len(expected_jobs) != 2 or expected_jobs != actual_jobs:
        return None
    records = []
    for row in children:
        job = json.loads(row["job"])
        logical_key, task_id = _identity(job, row["epoch"])
        params = job.get("params", {})
        if (
            row["id"] != task_id or row["logical_key"] != logical_key
            or row["epoch"] != EPOCH or row["group_name"] != GROUP
            or row["state"] != "pending" or row["tries"] != 0 or row["result"] is not None
            or row["attempts"] != 0 or row["parent_count"] != 1 or row["child_count"] != 0
            or job.get("api_name") != API or not CODE_RE.fullmatch(str(params.get("index_code", "")))
            or not DAY_RE.fullmatch(str(params.get("start_date", "")))
            or not DAY_RE.fullmatch(str(params.get("end_date", "")))
        ):
            return None
        records.append({
            "task_id": row["id"], "logical_key": row["logical_key"], "epoch": row["epoch"],
            "priority": row["priority"], "group_name": row["group_name"], "state": row["state"],
            "tries": row["tries"], "result": None, "attempts": row["attempts"],
            "parent_count": row["parent_count"], "child_count": row["child_count"],
            "request_signature_sha256": request_signature(job), "job": job,
        })
    return {
        "parent": {
            "task_id": parent["id"], "logical_key": parent["logical_key"], "epoch": parent["epoch"],
            "priority": parent["priority"], "group_name": parent["group_name"], "state": parent["state"],
            "tries": parent["tries"], "attempts": parent["attempts"], "result_status": _result_status(parent["result"]),
            "job": parent_job,
        },
        "split": {"method": parent["method"], "expected_children": parent["expected_children"], "coverage_proven": bool(parent["coverage_proven"]), "evidence": json.loads(parent["evidence"]), "status": parent["split_status"], "gap": parent["gap"]},
        "children": sorted(records, key=lambda row: row["task_id"]),
    }


def eligible_pairs(db, historical):
    historical_tasks, historical_logical, historical_requests = historical
    parents = db.execute(
        "SELECT p.id,p.logical_key,p.epoch,p.priority,p.group_name,p.job,p.state,p.tries,p.result,"
        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=p.id) attempts,"
        "s.method,s.expected_children,s.coverage_proven,s.evidence,s.status split_status,s.gap "
        "FROM partition_splits s JOIN jobs p ON p.id=s.parent_id "
        "WHERE p.epoch=? AND p.group_name=? AND p.state='split_pending' "
        "AND json_extract(p.job,'$.api_name')=? AND json_extract(p.result,'$.status')='possibly_truncated' "
        "AND s.method='date_bisection' AND s.expected_children=2 AND s.coverage_proven=1 "
        "ORDER BY json_extract(p.job,'$.params.end_date'),json_extract(p.job,'$.params.start_date'),p.id",
        (EPOCH, GROUP, API),
    ).fetchall()
    accepted, excluded = [], Counter()
    for parent in parents:
        if parent["attempts"] < 1:
            excluded["parent_without_attempt"] += 1
            continue
        pair = _pair(db, parent)
        if pair is None:
            excluded["invalid_pair"] += 1
            continue
        children = pair["children"]
        overlaps = {
            "task": any(row["task_id"] in historical_tasks for row in children),
            "logical": any(row["logical_key"] in historical_logical for row in children),
            "request": any(request_signature(row["job"]) in historical_requests for row in children),
        }
        if any(overlaps.values()):
            for key, value in overlaps.items():
                excluded[f"historical_{key}_overlap"] += int(value)
            continue
        accepted.append(pair)
    return accepted, dict(sorted(excluded.items()))


def _validate_pair(pair):
    if not isinstance(pair, dict) or set(pair) != {"parent", "split", "children"}:
        raise ValueError("Invalid sibling pair")
    parent, split, children = pair["parent"], pair["split"], pair["children"]
    if (
        parent.get("state") != "split_pending" or parent.get("result_status") != "possibly_truncated"
        or parent.get("attempts", 0) < 1 or parent.get("epoch") != EPOCH or parent.get("group_name") != GROUP
        or split.get("method") != "date_bisection" or split.get("expected_children") != 2
        or split.get("coverage_proven") is not True or not isinstance(split.get("evidence"), dict)
        or split.get("status") != "gap" or split.get("gap") != "child_not_verified"
        or not isinstance(children, list) or len(children) != 2
    ):
        raise ValueError("Invalid split parent contract")
    parent_logical, parent_task = _identity(parent["job"], parent["epoch"])
    if parent.get("logical_key") != parent_logical or parent.get("task_id") != parent_task:
        raise ValueError("Invalid split parent identity")
    root_preparation._validate_record(
        {
            key: parent[key]
            for key in (
                "task_id",
                "logical_key",
                "epoch",
                "priority",
                "group_name",
                "job",
            )
        }
    )
    expected = pipeline_module.Pipeline.date_children(None, parent["job"])
    if sorted(json_bytes(x["job"]["params"]) for x in children) != sorted(json_bytes(x) for x in (expected or [])):
        raise ValueError("Children do not match Pipeline.date_children")
    for row in children:
        root_preparation._validate_record(
            {
                key: row[key]
                for key in (
                    "task_id",
                    "logical_key",
                    "epoch",
                    "priority",
                    "group_name",
                    "job",
                )
            }
        )
        logical_key, task_id = _identity(row["job"], row["epoch"])
        if row.get("state") != "pending" or type(row.get("tries")) is not int or row.get("tries") != 0 or row.get("result") is not None or row.get("attempts") != 0 or row.get("parent_count") != 1 or row.get("child_count") != 0 or row.get("request_signature_sha256") != request_signature(row["job"]) or row.get("logical_key") != logical_key or row.get("task_id") != task_id:
            raise ValueError("Invalid pristine split child")


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if sha(path) != manifest_sha256:
        raise ValueError("Batch manifest hash mismatch")
    value = json.loads(path.read_bytes())
    pairs = value.get("pairs") if isinstance(value, dict) else None
    records = value.get("records") if isinstance(value, dict) else None
    source = value.get("source") if isinstance(value, dict) else None
    if value.get("schema_version") != 1 or value.get("kind") != "index_weight_descendant_exact_batch" or not isinstance(pairs, list) or not pairs or not isinstance(records, list) or len(records) != 2 * len(pairs) or len(records) > MAX_BATCH_JOBS:
        raise ValueError("Invalid descendant batch manifest")
    if (
        not isinstance(source, dict)
        or source.get("api_name") != API
        or source.get("epoch") != EPOCH
        or source.get("group_name") != GROUP
        or source.get("selection") != SELECTION
        or source.get("release_id")
        != "data-" + str(source.get("release_manifest_sha256", ""))
        or source.get("preparation_sha256") != preparation_sha256()
        or source.get("rate_gate", {}).get("api_rpm") != 500
        or source.get("rate_gate", {}).get("account_rpm") != 500
        or not isinstance(source.get("history_inventory"), dict)
        or source["history_inventory"].get("inventory_sha256")
        != digest(
            json_bytes(
                {
                    key: value
                    for key, value in source["history_inventory"].items()
                    if key != "inventory_sha256"
                }
            )
        )
        or value.get("pair_count") != len(pairs)
        or value.get("api_counts") != {API: len(records)}
        or value.get("boundaries")
        != {
            "complete_sibling_pairs_selected": True,
            "timeout_can_leave_a_pair_partial": True,
            "coverage_complete_claimed": False,
        }
    ):
        raise ValueError("Invalid descendant batch source")
    for key in (
        "release_manifest_sha256",
        "authority_config_sha256",
        "preparation_sha256",
    ):
        if not re.fullmatch(r"[a-f0-9]{64}", str(source.get(key, ""))):
            raise ValueError("Invalid source SHA-256")
    for pair in pairs:
        _validate_pair(pair)
    flattened = [row for pair in pairs for row in pair["children"]]
    if records != flattened:
        raise ValueError("Flat task list does not match sibling pairs")
    task_ids = sorted(row["task_id"] for row in records)
    logical_keys = sorted(row["logical_key"] for row in records)
    requests = sorted(row["request_signature_sha256"] for row in records)
    pair_ids = sorted(pair["parent"]["task_id"] for pair in pairs)
    if len(task_ids) != len(set(task_ids)) or len(logical_keys) != len(set(logical_keys)) or len(requests) != len(set(requests)) or value.get("all_task_ids_sha256") != digest(json_bytes(task_ids)) or value.get("all_logical_keys_sha256") != digest(json_bytes(logical_keys)) or value.get("all_request_signatures_sha256") != digest(json_bytes(requests)) or value.get("all_parent_ids_sha256") != digest(json_bytes(pair_ids)) or value.get("pair_set_sha256") != digest(json_bytes(pairs)):
        raise ValueError("Descendant inventory hash mismatch")
    return value


def prepare(root, output, release_id, release_manifest_sha256, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 2 <= jobs <= MAX_BATCH_JOBS or jobs % 2:
        raise ValueError("jobs must be an even integer from 2 to 360")
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output.is_symlink() or output == root or root in output.parents:
        raise ValueError("Output must not exist or be inside authority")
    release = fixed_release_evidence(root, release_id, release_manifest_sha256)
    config_path = _regular(root / "pipeline-config.json", "Pipeline config")
    config_bytes = config_path.read_bytes()
    history, ht, hl, hr = history_inventory(root)
    with _read_lock(root):
        db = sqlite3.connect(_regular(root / "pipeline.sqlite", "Pipeline database").as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            db.execute("BEGIN")
            eligible, excluded = eligible_pairs(db, (ht, hl, hr))
        finally:
            db.close()
    pairs = eligible[: jobs // 2]
    if len(pairs) != jobs // 2:
        raise ValueError("Insufficient pristine complete sibling pairs")
    records = [row for pair in pairs for row in pair["children"]]
    task_ids = sorted(row["task_id"] for row in records)
    parent_ids = sorted(pair["parent"]["task_id"] for pair in pairs)
    logical_keys = sorted(row["logical_key"] for row in records)
    requests = sorted(row["request_signature_sha256"] for row in records)
    manifest = {
        "schema_version": 1, "kind": "index_weight_descendant_exact_batch",
        "source": {**release, "authority_config_sha256": digest(config_bytes), "preparation_sha256": preparation_sha256(), "api_name": API, "epoch": EPOCH, "group_name": GROUP, "selection": SELECTION, "rate_gate": rate_gate(json.loads(config_bytes)), "history_inventory": history, "eligible_pairs": len(eligible), "excluded_pairs": excluded},
        "api_counts": {API: len(records)}, "pair_count": len(pairs),
        "all_task_ids_sha256": digest(json_bytes(task_ids)), "all_logical_keys_sha256": digest(json_bytes(logical_keys)),
        "all_request_signatures_sha256": digest(json_bytes(requests)), "all_parent_ids_sha256": digest(json_bytes(parent_ids)),
        "pair_set_sha256": digest(json_bytes(pairs)), "pairs": pairs, "records": records,
        "boundaries": {"complete_sibling_pairs_selected": True, "timeout_can_leave_a_pair_partial": True, "coverage_complete_claimed": False},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as target:
        target.write(json_bytes(manifest))
    return verify_manifest(output, sha(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--release-manifest-sha256", required=True)
    parser.add_argument("--jobs", type=int, default=MAX_BATCH_JOBS)
    args = parser.parse_args()
    result = prepare(args.root, args.output, args.release_id, args.release_manifest_sha256, args.jobs)
    print(json.dumps({"status": "prepared_not_executed", "jobs": len(result["records"]), "pairs": result["pair_count"], "manifest_sha256": sha(args.output), "all_task_ids_sha256": result["all_task_ids_sha256"], "all_parent_ids_sha256": result["all_parent_ids_sha256"], "pair_set_sha256": result["pair_set_sha256"], "authority_config_sha256": result["source"]["authority_config_sha256"], "preparation_sha256": result["source"]["preparation_sha256"], "history_inventory_sha256": result["source"]["history_inventory"]["inventory_sha256"], "upstream_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
