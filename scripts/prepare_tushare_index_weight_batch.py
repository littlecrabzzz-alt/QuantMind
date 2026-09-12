#!/usr/bin/env python3
"""Pin a small, high-margin and index-fair batch of queued index-weight history."""

from __future__ import annotations

import argparse
import calendar
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_rate_policy import resolved_api_rate  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS  # noqa: E402


API = "index_weight"
GROUP = "market"
EPOCH = "history"
MAX_BATCH_JOBS = 360
LEGACY_SELECTION = "latest_history_rounds_interleaved_by_supplier_suffix"
LEGACY_ROOT_SELECTION = "full_month_first_history_rounds_interleaved_by_supplier_suffix"
SELECTION = "pristine_parentless_full_month_rounds_interleaved_by_supplier_suffix"
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
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


def preparation_sha256():
    return sha(Path(__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


@contextmanager
def _read_lock(root):
    descriptor = os.open(
        _regular(Path(root) / "pipeline.lock", "Pipeline lock"),
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def fixed_release_evidence(root, release_id, manifest_sha256):
    root = Path(root).resolve()
    match = RELEASE_RE.fullmatch(str(release_id))
    if not match or match.group(1) != manifest_sha256:
        raise ValueError("Release ID must be derived from its manifest SHA-256")
    pointer = json.loads(
        _regular(root / "CURRENT.json", "Current pointer").read_bytes()
    )
    if pointer != {"manifest_sha256": manifest_sha256, "release_id": release_id}:
        raise ValueError("Explicit release is not the current fixed release")
    release = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(release) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    return {"release_id": release_id, "release_manifest_sha256": manifest_sha256}


def rate_gate(config):
    if (
        config.get("rate_policy") != "tiered_v1"
        or config.get("requests_per_minute") != 500
        or config.get("rollout_account_rpm") != 500
    ):
        raise ValueError("index_weight exact batch requires the tiered 500 rpm gate")
    resolved = resolved_api_rate(API, EXTENDED_CONTRACTS[API], config)
    if resolved.get("rpm") != 500 or resolved.get("review_required"):
        raise ValueError("index_weight permission does not resolve to reviewed 500 rpm")
    return {
        "rate_policy": "tiered_v1",
        "account_rpm": 500,
        "rollout_account_rpm": 500,
        "api_rpm": 500,
        "rate_source": resolved["source"],
    }


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


def _inventory_payload(manifests, tasks, logical, requests):
    payload = {
        "manifests": manifests,
        "tasks": len(tasks),
        "logical_keys": len(logical),
        "requests": len(requests),
        "task_ids_sha256": digest(json_bytes(sorted(tasks))),
        "logical_keys_sha256": digest(json_bytes(sorted(logical))),
        "requests_sha256": digest(json_bytes(sorted(requests))),
    }
    payload["inventory_sha256"] = digest(json_bytes(payload))
    return payload


def history_inventory(root):
    root = Path(root)
    tasks, logical, requests, manifests = set(), set(), set(), []
    for pattern in (
        "validation/index-weight-batch-*/batch-*-manifest.json",
        "validation/index-weight-descendant-batch-*/batch-*-manifest.json",
    ):
        for path in sorted(root.glob(pattern)):
            raw = _regular(path, "Historical batch manifest").read_bytes()
            value = json.loads(raw)
            rows = [
                row
                for row in value.get("records", [])
                if row.get("job", {}).get("api_name") == API
            ]
            if not rows:
                continue
            manifests.append(
                {
                    "path": str(path.relative_to(root)),
                    "sha256": digest(raw),
                    "records": len(rows),
                }
            )
            for row in rows:
                tasks.add(row["task_id"])
                logical.add(row["logical_key"])
                requests.add(request_signature(row["job"]))
    return (
        _inventory_payload(manifests, tasks, logical, requests),
        tasks,
        logical,
        requests,
    )


def descendant_inventory(db):
    rows = db.execute(
        "WITH RECURSIVE descendants(id) AS ("
        "SELECT pc.child_id FROM jobs roots INDEXED BY jobs_partition_lookup "
        "JOIN partition_children pc ON pc.parent_id=roots.id "
        "WHERE roots.epoch=? AND json_extract(roots.job,'$.api_name')=? UNION "
        "SELECT pc.child_id FROM partition_children pc JOIN descendants d ON pc.parent_id=d.id) "
        "SELECT DISTINCT j.id,j.logical_key,j.job FROM descendants d JOIN jobs j ON j.id=d.id "
        "WHERE json_extract(j.job,'$.api_name')=? ORDER BY j.id",
        (EPOCH, API, API),
    ).fetchall()
    tasks = {row["id"] for row in rows}
    logical = {row["logical_key"] for row in rows}
    requests = {request_signature(json.loads(row["job"])) for row in rows}
    return _inventory_payload([], tasks, logical, requests), tasks, logical, requests


def eligible_roots(db, history, descendants):
    _, historical_tasks, historical_logical, historical_requests = history
    _, descendant_tasks, descendant_logical, descendant_requests = descendants
    rows = db.execute(
        "WITH candidates AS ("
        "SELECT id,logical_key,epoch,job,priority,group_name,state,tries,result,"
        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=jobs.id) attempts,"
        "(SELECT COUNT(*) FROM partition_children pc WHERE pc.child_id=jobs.id) parent_count,"
        "json_extract(job,'$.params.index_code') AS index_code,"
        "substr(json_extract(job,'$.params.index_code'),"
        "instr(json_extract(job,'$.params.index_code'),'.')+1) AS suffix,"
        "substr(json_extract(job,'$.params.start_date'),7,2)='01' AS full_month_start,"
        "json_extract(job,'$.params.end_date')=strftime('%Y%m%d',"
        "substr(json_extract(job,'$.params.start_date'),1,4)||'-'||"
        "substr(json_extract(job,'$.params.start_date'),5,2)||'-01',"
        "'+1 month','-1 day') AS full_month_end "
        "FROM jobs INDEXED BY jobs_ready_api_history WHERE state='pending' "
        "AND tries=0 AND result IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM attempts a WHERE a.job_id=jobs.id) "
        "AND NOT EXISTS(SELECT 1 FROM partition_children pc WHERE pc.child_id=jobs.id) "
        "AND group_name=? AND epoch=? AND json_extract(job,'$.api_name')=?),"
        "per_index AS (SELECT *,"
        "ROW_NUMBER() OVER (PARTITION BY json_extract(job,'$.params.index_code') "
        "ORDER BY json_extract(job,'$.params.end_date') DESC,"
        "json_extract(job,'$.params.start_date') DESC,id) AS request_round "
        "FROM candidates WHERE full_month_start AND full_month_end),"
        "suffix_ranked AS (SELECT *,ROW_NUMBER() OVER ("
        "PARTITION BY request_round,suffix ORDER BY index_code,id) AS suffix_rank "
        "FROM per_index) SELECT * FROM suffix_ranked "
        "ORDER BY request_round,suffix_rank,suffix,index_code,id",
        (GROUP, EPOCH, API),
    ).fetchall()
    eligible = []
    for row in rows:
        job = json.loads(row["job"])
        signature = request_signature(job)
        if (
            row["id"] in historical_tasks
            or row["logical_key"] in historical_logical
            or signature in historical_requests
            or row["id"] in descendant_tasks
            or row["logical_key"] in descendant_logical
            or signature in descendant_requests
        ):
            continue
        eligible.append(row)
    return eligible


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
        or type(record["priority"]) is not int
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


def _validate_frozen_record(record):
    frozen = {"state", "tries", "result", "attempts", "parent_count"}
    if not isinstance(record, dict) or not frozen.issubset(record):
        raise ValueError("Missing pristine root evidence")
    code = _validate_record(
        {key: value for key, value in record.items() if key not in frozen}
    )
    if (
        record["state"] != "pending"
        or type(record["tries"]) is not int
        or record["tries"] != 0
        or record["result"] is not None
        or type(record["attempts"]) is not int
        or record["attempts"] != 0
        or type(record["parent_count"]) is not int
        or record["parent_count"] != 0
    ):
        raise ValueError("Batch contains a non-pristine or descendant root task")
    params = record["job"]["params"]
    try:
        start = datetime.strptime(params["start_date"], "%Y%m%d").date()
        end = datetime.strptime(params["end_date"], "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("Batch contains an invalid calendar date") from exc
    if (
        start.day != 1
        or end.year != start.year
        or end.month != start.month
        or end.day != calendar.monthrange(start.year, start.month)[1]
    ):
        raise ValueError("Batch contains a non-full-month root task")
    return code


def _selected_stats(records):
    codes = [
        _validate_frozen_record(record)
        if "state" in record
        else _validate_record(record)
        for record in records
    ]
    per_index = Counter(codes)
    suffixes = Counter(code.rsplit(".", 1)[1] for code in codes)
    request_counts = Counter(per_index.values())
    return {
        "api_count": len(records),
        "index_count": len(per_index),
        "suffix_counts": dict(sorted(suffixes.items())),
        "requests_per_index_counts": {
            str(requests): indexes
            for requests, indexes in sorted(request_counts.items())
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
    if (
        not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256)
        or sha(path) != manifest_sha256
    ):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    legacy_source = isinstance(source, dict) and set(source) == {
        "api_name",
        "epoch",
        "state",
        "pending_jobs",
        "pending_indexes",
        "selection",
    }
    if legacy_source:
        if (
            source.get("selection") not in (LEGACY_SELECTION, LEGACY_ROOT_SELECTION)
            or type(source.get("pending_jobs")) is not int
            or type(source.get("pending_indexes")) is not int
        ):
            raise ValueError("Invalid legacy batch selection")
    else:
        required_source = {
            "release_id",
            "release_manifest_sha256",
            "authority_config_sha256",
            "preparation_sha256",
            "api_name",
            "epoch",
            "state",
            "tries",
            "selection",
            "rate_gate",
            "eligible_jobs",
            "eligible_indexes",
            "eligible_task_ids_sha256",
            "history_inventory",
            "descendant_inventory",
        }
        if not isinstance(source, dict) or set(source) != required_source:
            raise ValueError("Invalid batch source")
        for inventory_name in ("history_inventory", "descendant_inventory"):
            inventory = source[inventory_name]
            if not isinstance(inventory, dict) or inventory.get(
                "inventory_sha256"
            ) != digest(
                json_bytes(
                    {
                        key: value
                        for key, value in inventory.items()
                        if key != "inventory_sha256"
                    }
                )
            ):
                raise ValueError("Invalid overlap inventory")
        if (
            source.get("release_id")
            != "data-" + str(source.get("release_manifest_sha256", ""))
            or source.get("preparation_sha256") != preparation_sha256()
            or source.get("selection") != SELECTION
            or type(source.get("tries")) is not int
            or source.get("tries") != 0
            or source.get("rate_gate", {}).get("api_rpm") != 500
            or source.get("rate_gate", {}).get("account_rpm") != 500
            or type(source.get("eligible_jobs")) is not int
            or source.get("eligible_jobs") < 1
            or type(source.get("eligible_indexes")) is not int
            or source.get("eligible_indexes") < 1
        ):
            raise ValueError("Invalid pinned batch source")
        for key in (
            "release_manifest_sha256",
            "authority_config_sha256",
            "preparation_sha256",
            "eligible_task_ids_sha256",
        ):
            if not re.fullmatch(r"[a-f0-9]{64}", str(source.get(key, ""))):
                raise ValueError("Invalid source SHA-256")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "index_weight_exact_batch"
        or source.get("api_name") != API
        or source.get("epoch") != EPOCH
        or source.get("state") != "pending"
        or manifest.get("boundaries") != BOUNDARIES
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch manifest")
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    logical_keys = sorted(record["logical_key"] for record in records)
    requests = sorted(request_signature(record["job"]) for record in records)
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if not legacy_source and (
        manifest.get("all_logical_keys_sha256") != digest(json_bytes(logical_keys))
        or manifest.get("all_request_signatures_sha256") != digest(json_bytes(requests))
    ):
        raise ValueError("Logical/request inventory hash mismatch")
    if manifest.get("selected") != _selected_stats(records):
        raise ValueError("Selected inventory mismatch")
    available_jobs = (
        source["pending_jobs"] if legacy_source else source["eligible_jobs"]
    )
    available_indexes = (
        source["pending_indexes"] if legacy_source else source["eligible_indexes"]
    )
    if (
        available_jobs < len(records)
        or available_indexes < manifest["selected"]["index_count"]
    ):
        raise ValueError("Source inventory is smaller than selected inventory")
    return manifest


def prepare(
    root,
    output,
    release_id,
    release_manifest_sha256,
    batch_jobs=MAX_BATCH_JOBS,
):
    if type(batch_jobs) is not int or not 1 <= batch_jobs <= MAX_BATCH_JOBS:
        raise ValueError("batch_jobs must be between 1 and 360")
    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output.is_symlink()
        or output == root
        or root in output.parents
    ):
        raise ValueError("Output must not exist or be inside authority")
    with _read_lock(root):
        release = fixed_release_evidence(root, release_id, release_manifest_sha256)
        config_bytes = _regular(
            root / "pipeline-config.json", "Pipeline config"
        ).read_bytes()
        history = history_inventory(root)
        database = _regular(root / "pipeline.sqlite", "Pipeline database")
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            db.execute("BEGIN")
            descendants = descendant_inventory(db)
            eligible = eligible_roots(db, history, descendants)
        finally:
            db.close()
    if len(eligible) < batch_jobs:
        raise ValueError("Insufficient pristine parentless index-weight roots")
    rows = eligible[:batch_jobs]
    records = [
        {
            "task_id": row["id"],
            "logical_key": row["logical_key"],
            "epoch": row["epoch"],
            "priority": row["priority"],
            "group_name": row["group_name"],
            "state": row["state"],
            "tries": row["tries"],
            "result": row["result"],
            "attempts": row["attempts"],
            "parent_count": row["parent_count"],
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
            **release,
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
            "api_name": API,
            "epoch": EPOCH,
            "state": "pending",
            "tries": 0,
            "selection": SELECTION,
            "rate_gate": rate_gate(json.loads(config_bytes)),
            "eligible_jobs": len(eligible),
            "eligible_indexes": len(
                {json.loads(row["job"])["params"]["index_code"] for row in eligible}
            ),
            "eligible_task_ids_sha256": digest(
                json_bytes(sorted(row["id"] for row in eligible))
            ),
            "history_inventory": history[0],
            "descendant_inventory": descendants[0],
        },
        "boundaries": BOUNDARIES,
        "selected": stats,
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "all_logical_keys_sha256": digest(
            json_bytes(sorted(record["logical_key"] for record in records))
        ),
        "all_request_signatures_sha256": digest(
            json_bytes(sorted(request_signature(record["job"]) for record in records))
        ),
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
    parser.add_argument("--batch-jobs", type=int, default=MAX_BATCH_JOBS)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--release-manifest-sha256", required=True)
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.output,
        args.release_id,
        args.release_manifest_sha256,
        args.batch_jobs,
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "selected": result["selected"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "all_logical_keys_sha256": result["all_logical_keys_sha256"],
                "all_request_signatures_sha256": result[
                    "all_request_signatures_sha256"
                ],
                "authority_config_sha256": result["source"]["authority_config_sha256"],
                "preparation_sha256": result["source"]["preparation_sha256"],
                "history_inventory_sha256": result["source"]["history_inventory"][
                    "inventory_sha256"
                ],
                "descendant_inventory_sha256": result["source"]["descendant_inventory"][
                    "inventory_sha256"
                ],
                "boundaries": result["boundaries"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
