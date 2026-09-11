#!/usr/bin/env python3
"""Freeze pristine IRM Q&A tasks against one fixed release."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_pipeline import contract_for  # noqa: E402
from backend.shared.tushare_rate_policy import resolved_api_rate  # noqa: E402


ALLOWED_APIS = ("irm_qa_sh", "irm_qa_sz")
EXPECTED_RPM = {"irm_qa_sh": 500, "irm_qa_sz": 500}
GROUP = "text"
MAX_BATCH_JOBS = 360
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"
)
DAY_RE = re.compile(r"[0-9]{8}")
AXES = ("question", "reply")


def sha(path):
    return digest(Path(path).read_bytes())


def preparation_sha256():
    return sha(Path(__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"Invalid {label} SHA-256")
    return value


@contextmanager
def _read_lock(root):
    path = _regular(Path(root) / "pipeline.lock", "Pipeline lock")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def release_evidence(root, release_id, manifest_sha256):
    root = Path(root).resolve()
    match = RELEASE_RE.fullmatch(str(release_id))
    _hash(manifest_sha256, "release manifest")
    if not match or match.group(1) != manifest_sha256:
        raise ValueError("Release ID must be derived from its manifest SHA-256")
    pointer = json.loads(
        _regular(root / "CURRENT.json", "Current pointer").read_bytes()
    )
    if pointer != {"manifest_sha256": manifest_sha256, "release_id": release_id}:
        raise ValueError("Explicit release is not the current fixed release")
    manifest = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(manifest) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    return {"release_id": release_id, "release_manifest_sha256": manifest_sha256}


def rate_contracts(config):
    contracts = {}
    for api in ALLOWED_APIS:
        resolved = resolved_api_rate(api, contract_for(api), config)
        if (
            resolved.get("rpm") != EXPECTED_RPM[api]
            or resolved.get("source", "").split("+")[0]
            != "user_purchased_permission_family"
        ):
            raise ValueError(f"Unexpected IRM Q&A rate contract for {api}")
        contracts[api] = {
            "rpm": EXPECTED_RPM[api],
            "source": resolved["source"],
        }
    return contracts


def _axis(params):
    if not isinstance(params, dict):
        return None
    if set(params) == {"start_date", "end_date"}:
        if (
            DAY_RE.fullmatch(str(params["start_date"]))
            and DAY_RE.fullmatch(str(params["end_date"]))
            and params["start_date"] <= params["end_date"]
        ):
            return "question"
        return None
    if set(params) == {"pub_start", "pub_end"}:
        if (
            TIMESTAMP_RE.fullmatch(str(params["pub_start"]))
            and TIMESTAMP_RE.fullmatch(str(params["pub_end"]))
            and params["pub_start"] <= params["pub_end"]
        ):
            return "reply"
    return None


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "state",
        "tries",
        "attempts",
        "partition_child",
        "job",
    }:
        raise ValueError("Invalid task record")
    job = record["job"]
    api = job.get("api_name") if isinstance(job, dict) else None
    if (
        api not in ALLOWED_APIS
        or record["group_name"] != GROUP
        or record["state"] != "pending"
        or record["tries"] != 0
        or record["attempts"] != 0
        or type(record["partition_child"]) is not bool
        or type(record["priority"]) is not int
        or not isinstance(record["epoch"], str)
        or _axis(job.get("params")) is None
    ):
        raise ValueError("Batch contains a non-IRM-Q&A or non-pristine task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return api, _axis(job["params"])


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "irm_qa_exact_batch"
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
        or manifest.get("api_rate_contracts")
        != {
            api: {
                "rpm": EXPECTED_RPM[api],
                "source": manifest.get("api_rate_contracts", {}).get(api, {}).get(
                    "source"
                ),
            }
            for api in ALLOWED_APIS
        }
        or any(
            not str(manifest["api_rate_contracts"][api]["source"]).startswith(
                "user_purchased_permission_family"
            )
            for api in ALLOWED_APIS
        )
    ):
        raise ValueError("Invalid batch manifest")
    validated = [_validate_record(record) for record in records]
    counts = Counter(api for api, _ in validated)
    axis_counts = Counter(f"{api}:{axis}" for api, axis in validated)
    if manifest.get("api_counts") != dict(sorted(counts.items())):
        raise ValueError("API counts mismatch")
    if manifest.get("axis_counts") != dict(sorted(axis_counts.items())):
        raise ValueError("Axis counts mismatch")
    partition_counts = Counter(
        "child" if record["partition_child"] else "unsplit" for record in records
    )
    if manifest.get("partition_counts") != dict(sorted(partition_counts.items())):
        raise ValueError("Partition counts mismatch")
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    logical_keys = [record["logical_key"] for record in records]
    logical_count = len(set(logical_keys))
    if manifest.get("logical_request_counts") != {
        "distinct": logical_count,
        "duplicate_tasks": len(records) - logical_count,
    }:
        raise ValueError("Logical request counts mismatch")
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or source.get("epoch") != "history"
        or source.get("tries") != 0
        or source.get("attempts") != 0
        or source.get("selection")
        != "balanced_api_axis_history_leaves_without_prior_attempts"
        or type(source.get("eligible_tasks")) is not int
        or source["eligible_tasks"] < len(records)
        or type(source.get("excluded_invalid_parameter_tasks")) is not int
        or source["excluded_invalid_parameter_tasks"] < 0
        or type(source.get("skipped_logical_duplicates")) is not int
        or source["skipped_logical_duplicates"] < 0
        or not re.fullmatch(
            r"[a-f0-9]{64}", str(source.get("authority_config_sha256", ""))
        )
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or source["release_id"]
        != "data-" + str(source.get("release_manifest_sha256", ""))
        or source.get("preparation_sha256") != preparation_sha256()
    ):
        raise ValueError("Invalid pinned source evidence")
    return manifest


def _record(row):
    return {
        "task_id": row["id"],
        "logical_key": row["logical_key"],
        "epoch": row["epoch"],
        "priority": row["priority"],
        "group_name": row["group_name"],
        "state": row["state"],
        "tries": row["tries"],
        "attempts": row["attempts"],
        "partition_child": bool(row["partition_child"]),
        "job": json.loads(row["job"]),
    }


def _selection_key(record):
    params = record["job"]["params"]
    axis = _axis(params)
    if axis == "question":
        start = datetime.strptime(params["start_date"], "%Y%m%d")
        end = datetime.strptime(params["end_date"], "%Y%m%d")
    else:
        start = datetime.strptime(params["pub_start"], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(params["pub_end"], "%Y-%m-%d %H:%M:%S")
    return (
        not record["partition_child"],
        (end - start).total_seconds(),
        -int(end.strftime("%Y%m%d%H%M%S")),
        record["task_id"],
    )


def prepare(root, output, release_id, release_manifest_sha256, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 1 <= jobs <= MAX_BATCH_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output.is_symlink()
        or output == root
        or root in output.parents
    ):
        raise ValueError("Output must not exist or be inside authority")
    release = release_evidence(root, release_id, release_manifest_sha256)
    config_path = _regular(root / "pipeline-config.json", "Pipeline config")
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    rates = rate_contracts(config)
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    with _read_lock(root):
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            placeholders = ",".join("?" for _ in ALLOWED_APIS)
            rows = db.execute(
                "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
                "j.state,j.tries,"
                "(SELECT COUNT(*) FROM attempts a JOIN jobs prior "
                "ON prior.id=a.job_id WHERE prior.logical_key=j.logical_key) attempts,"
                "EXISTS(SELECT 1 FROM partition_children pc "
                "WHERE pc.child_id=j.id) partition_child "
                "FROM jobs j WHERE j.group_name=? AND j.state='pending' "
                "AND j.epoch='history' "
                "AND j.tries=0 AND NOT EXISTS(SELECT 1 FROM attempts a "
                "JOIN jobs prior ON prior.id=a.job_id "
                "WHERE prior.logical_key=j.logical_key) "
                "AND NOT EXISTS(SELECT 1 FROM jobs prior_state "
                "WHERE prior_state.logical_key=j.logical_key "
                "AND prior_state.id<>j.id AND prior_state.state<>'pending') "
                "AND json_extract(job,'$.api_name') IN ("
                + placeholders
                + ") ORDER BY j.id",
                (GROUP, *ALLOWED_APIS),
            ).fetchall()
        finally:
            db.close()
    inventory = [_record(row) for row in rows]
    eligible = [
        record for record in inventory if _axis(record["job"].get("params")) is not None
    ]
    buckets = {(api, axis): [] for api in ALLOWED_APIS for axis in AXES}
    seen_logical_keys = set()
    for record in eligible:
        if record["logical_key"] in seen_logical_keys:
            continue
        seen_logical_keys.add(record["logical_key"])
        axis = _axis(record["job"]["params"])
        buckets[(record["job"]["api_name"], axis)].append(record)
    for bucket in buckets.values():
        bucket.sort(key=_selection_key)
    records = []
    offsets = dict.fromkeys(buckets, 0)
    while len(records) < jobs:
        added = False
        for key in buckets:
            offset = offsets[key]
            if offset < len(buckets[key]):
                records.append(buckets[key][offset])
                offsets[key] += 1
                added = True
                if len(records) == jobs:
                    break
        if not added:
            break
    if not records:
        raise ValueError("No pristine IRM Q&A tasks are pending")
    task_ids = sorted(record["task_id"] for record in records)
    logical_keys = [record["logical_key"] for record in records]
    counts = Counter(record["job"]["api_name"] for record in records)
    axis_counts = Counter(
        f"{record['job']['api_name']}:{_axis(record['job']['params'])}"
        for record in records
    )
    partition_counts = Counter(
        "child" if record["partition_child"] else "unsplit" for record in records
    )
    manifest = {
        "schema_version": 1,
        "kind": "irm_qa_exact_batch",
        "source": {
            **release,
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
            "group_name": GROUP,
            "state": "pending",
            "epoch": "history",
            "tries": 0,
            "attempts": 0,
            "selection": "balanced_api_axis_history_leaves_without_prior_attempts",
            "eligible_tasks": len(eligible),
            "excluded_invalid_parameter_tasks": len(inventory) - len(eligible),
            "skipped_logical_duplicates": len(eligible)
            - len({record["logical_key"] for record in eligible}),
        },
        "api_rate_contracts": rates,
        "api_counts": dict(sorted(counts.items())),
        "axis_counts": dict(sorted(axis_counts.items())),
        "partition_counts": dict(sorted(partition_counts.items())),
        "logical_request_counts": {
            "distinct": len(set(logical_keys)),
            "duplicate_tasks": len(records) - len(set(logical_keys)),
        },
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "records": records,
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
    result = prepare(
        args.root,
        args.output,
        args.release_id,
        args.release_manifest_sha256,
        args.jobs,
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "axis_counts": result["axis_counts"],
                "partition_counts": result["partition_counts"],
                "logical_request_counts": result["logical_request_counts"],
                "api_rate_contracts": result["api_rate_contracts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "authority_config_sha256": result["source"][
                    "authority_config_sha256"
                ],
                "preparation_sha256": result["source"]["preparation_sha256"],
                "upstream_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
