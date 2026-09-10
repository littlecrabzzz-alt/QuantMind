#!/usr/bin/env python3
"""Pin a small, API-fair batch of already queued financial statement leaves."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402


ALLOWED_APIS = ("income_vip", "balancesheet_vip", "cashflow_vip")
MAX_JOBS_PER_API = 120
MAX_BATCH_JOBS = len(ALLOWED_APIS) * MAX_JOBS_PER_API
CANDIDATE_MULTIPLIER = 10


def sha(path):
    value = digest(Path(path).read_bytes())
    return value


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "job",
    }:
        raise ValueError("Invalid task record")
    job = record["job"]
    if (
        not isinstance(job, dict)
        or job.get("api_name") not in ALLOWED_APIS
        or record["group_name"] != "structured"
        or not isinstance(job.get("params"), dict)
        or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", str(job["params"].get("ts_code", "")))
        or not re.fullmatch(r"[0-9]{8}", str(job["params"].get("period", "")))
    ):
        raise ValueError("Batch contains a non-financial or non-leaf task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return job["api_name"]


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256) or sha(path) != manifest_sha256:
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "financial_pit_exact_batch"
        or not isinstance(manifest.get("records"), list)
        or not 1 <= len(manifest["records"]) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch manifest")
    counts = Counter(_validate_record(record) for record in manifest["records"])
    if any(count > MAX_JOBS_PER_API for count in counts.values()):
        raise ValueError("Per-API task limit exceeded")
    task_ids = sorted(record["task_id"] for record in manifest["records"])
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if manifest.get("api_counts") != dict(sorted(counts.items())):
        raise ValueError("API counts mismatch")
    return manifest


def prepare(root, output, epoch, jobs_per_api=MAX_JOBS_PER_API):
    if not re.fullmatch(r"[0-9]{8}", epoch):
        raise ValueError("Epoch must be YYYYMMDD")
    if type(jobs_per_api) is not int or not 1 <= jobs_per_api <= MAX_JOBS_PER_API:
        raise ValueError("jobs_per_api must be between 1 and 120")
    root, output = Path(root).resolve(), Path(output).resolve()
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    if output.exists() or output.is_symlink() or output == root or root in output.parents:
        raise ValueError("Output must not exist")
    candidates = {}
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        for api in ALLOWED_APIS:
            rows = db.execute(
                "SELECT id,logical_key,epoch,job,priority,group_name FROM jobs "
                "WHERE epoch=? AND json_extract(job,'$.api_name')=? "
                "AND state='pending' AND json_type(job,'$.params.ts_code')='text' "
                "ORDER BY json_extract(job,'$.params.period') DESC,"
                "CAST(json_extract(job,'$.params.report_type') AS INTEGER),"
                "json_extract(job,'$.params.ts_code'),id LIMIT ?",
                (epoch, api, jobs_per_api * CANDIDATE_MULTIPLIER),
            ).fetchall()
            candidates[api] = {}
            for row in rows:
                job = json.loads(row["job"])
                key = (
                    job["params"]["period"],
                    job["params"].get("report_type"),
                    job["params"]["ts_code"],
                )
                candidates[api][key] = {
                    "task_id": row["id"],
                    "logical_key": row["logical_key"],
                    "epoch": row["epoch"],
                    "priority": row["priority"],
                    "group_name": row["group_name"],
                    "job": job,
                }
    finally:
        db.close()
    common = set.intersection(*(set(candidates[api]) for api in ALLOWED_APIS))
    selected = sorted(
        common,
        key=lambda key: (
            -int(key[0]),
            int(key[1]) if key[1] is not None else -1,
            key[2],
        ),
    )[:jobs_per_api]
    if len(selected) != jobs_per_api:
        raise ValueError("Insufficient common pending statement leaves")
    records = [candidates[api][key] for api in ALLOWED_APIS for key in selected]
    counts = Counter(_validate_record(record) for record in records)
    records.sort(key=lambda row: (ALLOWED_APIS.index(row["job"]["api_name"]), row["task_id"]))
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "financial_pit_exact_batch",
        "source": {
            "epoch": epoch,
            "state": "pending",
            "selection": "latest_period_common_code_specific_leaves",
        },
        "api_counts": dict(sorted(counts.items())),
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as target:
        target.write(json_bytes(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epoch", required=True)
    parser.add_argument("--jobs-per-api", type=int, default=MAX_JOBS_PER_API)
    args = parser.parse_args()
    result = prepare(args.root, args.output, args.epoch, args.jobs_per_api)
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
