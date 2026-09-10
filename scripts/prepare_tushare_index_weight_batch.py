#!/usr/bin/env python3
"""Pin a small, recent and index-fair batch of queued index-weight history."""

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


API = "index_weight"
GROUP = "market"
EPOCH = "history"
MAX_BATCH_JOBS = 360
BOUNDARIES = {
    "history_start_is_request_scope_not_verified_availability": True,
    "index_universe_complete": False,
    "known_at_verified": False,
    "single_index_single_day_saturation_proves_coverage": False,
}
CODE = re.compile(r"[A-Za-z0-9]+\.[A-Z]+")
DAY = re.compile(r"[0-9]{8}")


def sha(path):
    return digest(Path(path).read_bytes())


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
    job, params = record["job"], record.get("job", {}).get("params")
    if (
        not isinstance(job, dict)
        or set(job)
        != {
            "api_name",
            "params",
            "fields",
            "row_cap",
            "required_fields",
            "nullable_fields",
            "positive_fields",
        }
        or job.get("api_name") != API
        or job.get("fields") != "con_code,index_code,trade_date,weight"
        or job.get("row_cap") != 1000
        or job.get("required_fields") != ["index_code", "con_code", "trade_date"]
        or job.get("nullable_fields") != []
        or job.get("positive_fields") != []
        or record["group_name"] != GROUP
        or record["epoch"] != EPOCH
        or not isinstance(record["priority"], int)
        or not isinstance(params, dict)
        or set(params) != {"index_code", "start_date", "end_date"}
        or not CODE.fullmatch(str(params.get("index_code", "")))
        or not DAY.fullmatch(str(params.get("start_date", "")))
        or not DAY.fullmatch(str(params.get("end_date", "")))
        or params["start_date"] > params["end_date"]
    ):
        raise ValueError("Batch contains a non-index-weight historical leaf")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return params["index_code"]


def _selected_stats(records):
    codes = [_validate_record(record) for record in records]
    per_index = Counter(codes)
    suffixes = Counter(code.rsplit(".", 1)[1] for code in codes)
    request_counts = Counter(per_index.values())
    return {
        "api_count": len(records),
        "index_count": len(per_index),
        "suffix_counts": dict(sorted(suffixes.items())),
        "requests_per_index_counts": {
            str(requests): indexes for requests, indexes in sorted(request_counts.items())
        },
        "request_start_min": min(
            record["job"]["params"]["start_date"] for record in records
        ),
        "request_end_max": max(
            record["job"]["params"]["end_date"] for record in records
        ),
    }


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256) or sha(path) != manifest_sha256:
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "index_weight_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "api_name",
            "epoch",
            "state",
            "pending_jobs",
            "pending_indexes",
            "selection",
        }
        or source.get("api_name") != API
        or source.get("epoch") != EPOCH
        or source.get("state") != "pending"
        or source.get("selection")
        != "latest_history_rounds_interleaved_by_supplier_suffix"
        or type(source.get("pending_jobs")) is not int
        or type(source.get("pending_indexes")) is not int
        or manifest.get("boundaries") != BOUNDARIES
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch manifest")
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if manifest.get("selected") != _selected_stats(records):
        raise ValueError("Selected inventory mismatch")
    if source["pending_jobs"] < len(records) or source["pending_indexes"] < manifest[
        "selected"
    ]["index_count"]:
        raise ValueError("Source inventory is smaller than selected inventory")
    return manifest


def prepare(root, output, batch_jobs=MAX_BATCH_JOBS):
    if type(batch_jobs) is not int or not 1 <= batch_jobs <= MAX_BATCH_JOBS:
        raise ValueError("batch_jobs must be between 1 and 360")
    root, output = Path(root).resolve(), Path(output).resolve()
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    if output.exists() or output.is_symlink() or output == root or root in output.parents:
        raise ValueError("Output must not exist or be inside authority")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        db.execute("BEGIN")
        source = db.execute(
            "SELECT COUNT(*),COUNT(DISTINCT json_extract(job,'$.params.index_code')) "
            "FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' "
            "AND group_name=? AND epoch=? AND json_extract(job,'$.api_name')=?",
            (GROUP, EPOCH, API),
        ).fetchone()
        rows = db.execute(
            "WITH per_index AS ("
            "SELECT id,logical_key,epoch,job,priority,group_name,"
            "json_extract(job,'$.params.index_code') AS index_code,"
            "substr(json_extract(job,'$.params.index_code'),"
            "instr(json_extract(job,'$.params.index_code'),'.')+1) AS suffix,"
            "ROW_NUMBER() OVER (PARTITION BY json_extract(job,'$.params.index_code') "
            "ORDER BY json_extract(job,'$.params.end_date') DESC,"
            "json_extract(job,'$.params.start_date') DESC,id) AS request_round "
            "FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' "
            "AND group_name=? AND epoch=? AND json_extract(job,'$.api_name')=?),"
            "suffix_ranked AS (SELECT *,ROW_NUMBER() OVER ("
            "PARTITION BY request_round,suffix ORDER BY index_code,id) AS suffix_rank "
            "FROM per_index) SELECT id,logical_key,epoch,job,priority,group_name "
            "FROM suffix_ranked ORDER BY request_round,suffix_rank,suffix,index_code,id LIMIT ?",
            (GROUP, EPOCH, API, batch_jobs),
        ).fetchall()
    finally:
        db.close()
    if len(rows) != batch_jobs:
        raise ValueError("Insufficient pending index-weight history")
    records = [
        {
            "task_id": row["id"],
            "logical_key": row["logical_key"],
            "epoch": row["epoch"],
            "priority": row["priority"],
            "group_name": row["group_name"],
            "job": json.loads(row["job"]),
        }
        for row in rows
    ]
    stats = _selected_stats(records)
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "index_weight_exact_batch",
        "source": {
            "api_name": API,
            "epoch": EPOCH,
            "state": "pending",
            "pending_jobs": source[0],
            "pending_indexes": source[1],
            "selection": "latest_history_rounds_interleaved_by_supplier_suffix",
        },
        "boundaries": BOUNDARIES,
        "selected": stats,
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
    parser.add_argument("--batch-jobs", type=int, default=MAX_BATCH_JOBS)
    args = parser.parse_args()
    result = prepare(args.root, args.output, args.batch_jobs)
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "selected": result["selected"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "boundaries": result["boundaries"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
