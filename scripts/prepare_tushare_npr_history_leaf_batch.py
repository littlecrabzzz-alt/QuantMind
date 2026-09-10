#!/usr/bin/env python3
"""Freeze the six untouched NPR history leaves against one fixed release."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
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
from backend.shared.tushare_rate_policy import (  # noqa: E402
    positive_int,
    resolved_api_rate,
)


API = "npr"
EXPECTED_API_RPM = 500
EXPECTED_ACCOUNT_RPM = 500
GROUP = "text"
EXPECTED_BATCH_JOBS = 6
AUDITED_TASK_IDS_SHA256 = (
    "09dc4c11afe018732e18f4f7108e9be0939b87715265d1f15cbea79bbc05d846"
)
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
NPR_DATE_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"
)


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
    pointer_path = _regular(root / "CURRENT.json", "Current pointer")
    pointer = json.loads(pointer_path.read_bytes())
    if pointer != {"manifest_sha256": manifest_sha256, "release_id": release_id}:
        raise ValueError("Explicit release is not the current fixed release")
    manifest = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(manifest) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    return {
        "release_id": release_id,
        "release_manifest_sha256": manifest_sha256,
        "current_pointer_sha256": sha(pointer_path),
    }


def rate_contracts(config):
    resolved = resolved_api_rate(API, contract_for(API), config)
    if (
        resolved.get("rpm") != EXPECTED_API_RPM
        or resolved.get("source", "").split("+")[0]
        != "user_purchased_permission_family"
    ):
        raise ValueError("Unexpected npr rate contract")
    account_rpm = positive_int(
        config.get("requests_per_minute"), "account request rate"
    )
    rollout = config.get("rollout_account_rpm")
    if rollout is not None:
        account_rpm = min(
            account_rpm,
            positive_int(rollout, "rollout account rate"),
        )
    if account_rpm != EXPECTED_ACCOUNT_RPM:
        raise ValueError("Unexpected account rate contract")
    return {
        "api": {"rpm": EXPECTED_API_RPM, "source": resolved["source"]},
        "account": {"rpm": EXPECTED_ACCOUNT_RPM, "source": "configured_shared_gate"},
    }


def _valid_params(params):
    return (
        isinstance(params, dict)
        and set(params) == {"start_date", "end_date"}
        and NPR_DATE_RE.fullmatch(str(params["start_date"])) is not None
        and NPR_DATE_RE.fullmatch(str(params["end_date"])) is not None
        and params["start_date"] <= params["end_date"]
    )


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
        "parent_ids",
        "job",
    }:
        raise ValueError("Invalid task record")
    job = record["job"]
    if (
        not isinstance(job, dict)
        or job.get("api_name") != API
        or record["group_name"] != GROUP
        or record["state"] != "pending"
        or record["tries"] != 0
        or record["attempts"] != 0
        or not isinstance(record["parent_ids"], list)
        or not record["parent_ids"]
        or record["parent_ids"] != sorted(set(record["parent_ids"]))
        or any(
            not isinstance(parent_id, str) or not parent_id
            for parent_id in record["parent_ids"]
        )
        or type(record["priority"]) is not int
        or not isinstance(record["epoch"], str)
        or not _valid_params(job.get("params"))
        or job.get("row_cap") != 500
    ):
        raise ValueError("Batch contains a non-pristine NPR history leaf")
    if record["epoch"] != "history":
        raise ValueError("Batch contains a non-history NPR task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return record["logical_key"]


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "npr_history_leaf_exact_batch"
        or not isinstance(records, list)
        or len(records) != EXPECTED_BATCH_JOBS
        or manifest.get("rate_contracts", {}).get("api", {}).get("rpm")
        != EXPECTED_API_RPM
        or not str(
            manifest.get("rate_contracts", {}).get("api", {}).get("source", "")
        ).startswith("user_purchased_permission_family")
        or manifest.get("rate_contracts", {}).get("account")
        != {"rpm": EXPECTED_ACCOUNT_RPM, "source": "configured_shared_gate"}
    ):
        raise ValueError("Invalid batch manifest")
    logical_keys = [_validate_record(record) for record in records]
    if manifest.get("api_counts") != {API: len(records)}:
        raise ValueError("API count mismatch")
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if len(logical_keys) != len(set(logical_keys)):
        raise ValueError("Duplicate logical request")
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or source.get("tries") != 0
        or source.get("attempts") != 0
        or source.get("direct_split_child") is not True
        or source.get("audited_task_ids_sha256") != AUDITED_TASK_IDS_SHA256
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or source["release_id"]
        != "data-" + str(source.get("release_manifest_sha256", ""))
        or source.get("preparation_sha256") != preparation_sha256()
        or not re.fullmatch(
            r"[a-f0-9]{64}", str(source.get("current_pointer_sha256", ""))
        )
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
        "parent_ids": json.loads(row["parent_ids"]),
        "job": json.loads(row["job"]),
    }


def prepare(root, output, release_id, release_manifest_sha256):
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
            rows = db.execute(
                "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
                "j.state,j.tries,"
                "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) attempts,"
                "(SELECT json_group_array(parent_id) FROM "
                "(SELECT pc.parent_id FROM partition_children pc "
                "JOIN partition_splits ps ON ps.parent_id=pc.parent_id "
                "WHERE pc.child_id=j.id AND ps.method='date_bisection' "
                "ORDER BY pc.parent_id)) parent_ids "
                "FROM jobs j INDEXED BY jobs_partition_lookup "
                "WHERE json_extract(j.job,'$.api_name')=? "
                "ORDER BY j.priority,(j.epoch!='history'),j.epoch,"
                "json_extract(j.job,'$.params.start_date'),"
                "json_extract(j.job,'$.params.end_date'),j.id",
                (API,),
            ).fetchall()
        finally:
            db.close()
    inventory = [_record(row) for row in rows]
    attempted_logical_keys = {
        record["logical_key"] for record in inventory if record["attempts"]
    }
    eligible = [
        record
        for record in inventory
        if record["group_name"] == GROUP
        and record["epoch"] == "history"
        and record["state"] == "pending"
        and record["tries"] == 0
        and record["attempts"] == 0
        and record["parent_ids"]
        and record["logical_key"] not in attempted_logical_keys
    ]
    records = []
    seen_logical_keys = set()
    for record in eligible:
        if record["logical_key"] in seen_logical_keys:
            continue
        seen_logical_keys.add(record["logical_key"])
        records.append(record)
    if len(records) != EXPECTED_BATCH_JOBS:
        raise ValueError(
            "Expected exactly 6 untouched NPR history leaves; "
            f"found {len(records)}"
        )
    task_ids = sorted(record["task_id"] for record in records)
    task_ids_sha256 = digest(json_bytes(task_ids))
    if task_ids_sha256 != AUDITED_TASK_IDS_SHA256:
        raise ValueError("Audited NPR task inventory changed")
    logical_keys = [record["logical_key"] for record in records]
    manifest = {
        "schema_version": 1,
        "kind": "npr_history_leaf_exact_batch",
        "source": {
            **release,
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "attempts": 0,
            "direct_split_child": True,
            "audited_task_ids_sha256": AUDITED_TASK_IDS_SHA256,
            "selection": "all_distinct_unattempted_npr_history_leaves",
            "eligible_tasks": len(eligible),
            "skipped_logical_duplicates": len(eligible)
            - len({record["logical_key"] for record in eligible}),
        },
        "rate_contracts": rates,
        "api_counts": {API: len(records)},
        "all_task_ids_sha256": task_ids_sha256,
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
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.output,
        args.release_id,
        args.release_manifest_sha256,
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "rate_contracts": result["rate_contracts"],
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
