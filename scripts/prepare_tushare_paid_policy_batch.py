#!/usr/bin/env python3
"""Freeze pristine paid policy/report tasks against one fixed release."""

from __future__ import annotations

import argparse
from collections import Counter
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
from backend.shared.tushare_rate_policy import resolved_api_rate  # noqa: E402


ALLOWED_APIS = ("npr", "monetary_policy")
EXPECTED_RPM = {"npr": 500, "monetary_policy": 200}
GROUP = "text"
MAX_BATCH_JOBS = 360
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
NPR_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
DAY_RE = re.compile(r"[0-9]{8}")


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
            raise ValueError(f"Unexpected paid API rate contract for {api}")
        contracts[api] = {
            "rpm": EXPECTED_RPM[api],
            "source": resolved["source"],
        }
    return contracts


def _valid_params(api, params):
    if not isinstance(params, dict):
        return False
    if api == "monetary_policy":
        return (
            set(params) == {"start_date", "end_date"}
            and DAY_RE.fullmatch(str(params["start_date"])) is not None
            and DAY_RE.fullmatch(str(params["end_date"])) is not None
            and params["start_date"] <= params["end_date"]
        )
    if not set(params).issubset({"org", "start_date", "end_date", "ptype"}):
        return False
    if (
        "end_date" not in params
        or NPR_DATE_RE.fullmatch(str(params["end_date"])) is None
    ):
        return False
    if "start_date" in params and (
        NPR_DATE_RE.fullmatch(str(params["start_date"])) is None
        or params["start_date"] > params["end_date"]
    ):
        return False
    return True


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "state",
        "tries",
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
        or type(record["priority"]) is not int
        or not isinstance(record["epoch"], str)
        or not _valid_params(api, job.get("params"))
    ):
        raise ValueError("Batch contains a non-policy or non-pristine task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return api


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "paid_policy_exact_batch"
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
    counts = Counter(_validate_record(record) for record in records)
    if manifest.get("api_counts") != dict(sorted(counts.items())):
        raise ValueError("API counts mismatch")
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
        or source.get("tries") != 0
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
        "job": json.loads(row["job"]),
    }


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
                "SELECT id,logical_key,epoch,job,priority,group_name,state,tries "
                "FROM jobs WHERE group_name=? AND state='pending' AND tries=0 "
                "AND json_extract(job,'$.api_name') IN ("
                + placeholders
                + ") ORDER BY CASE json_extract(job,'$.api_name') "
                "WHEN 'monetary_policy' THEN 0 ELSE 1 END,priority,"
                "COALESCE(json_extract(job,'$.params.start_date'),''),"
                "json_extract(job,'$.params.end_date'),epoch,id",
                (GROUP, *ALLOWED_APIS),
            ).fetchall()
        finally:
            db.close()
    eligible = [_record(row) for row in rows]
    records = []
    seen_logical_keys = set()
    for record in eligible:
        if record["logical_key"] in seen_logical_keys:
            continue
        seen_logical_keys.add(record["logical_key"])
        records.append(record)
        if len(records) == jobs:
            break
    if not records:
        raise ValueError("No pristine paid policy tasks are pending")
    task_ids = sorted(record["task_id"] for record in records)
    logical_keys = [record["logical_key"] for record in records]
    counts = Counter(record["job"]["api_name"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "paid_policy_exact_batch",
        "source": {
            **release,
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "selection": "deterministic_distinct_pristine_logical_requests",
            "eligible_tasks": len(eligible),
            "skipped_logical_duplicates": len(eligible)
            - len({record["logical_key"] for record in eligible}),
        },
        "api_rate_contracts": rates,
        "api_counts": dict(sorted(counts.items())),
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
