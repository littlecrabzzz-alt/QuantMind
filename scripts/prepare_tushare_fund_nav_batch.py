#!/usr/bin/env python3
"""Pin existing fund_nav history leaves without changing the authority."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys


API = "fund_nav"
GROUP = "market"
HISTORY_EPOCH = "history"
MAX_BATCH_JOBS = 360
BOUNDARIES = {
    "fund_universe": (
        "The observed union of fund_basic responses is context, not proof of a complete "
        "vendor universe; planned-only and discovery-only codes remain explicit gaps."
    ),
    "lifecycle": (
        "Existing queued request windows are preserved byte-for-byte. Listing, due and "
        "delisting dates are context only and never turn a missing NAV into coverage."
    ),
    "net_asset_value_revision": (
        "Raw observations remain immutable. Corrections may reuse ts_code, nav_date and "
        "ann_date, so downstream work must pin a release and retain observation identity."
    ),
    "point_in_time": (
        "ann_date is nullable and fetched_at proves capture time only; this batch does "
        "not prove when a value first became knowable."
    ),
}
LIFECYCLE_FIELDS = (
    "market",
    "status",
    "list_date",
    "due_date",
    "delist_date",
    "issue_date",
)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _valid_code(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", value)


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
    params = job.get("params") if isinstance(job, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("api_name") != API
        or record["group_name"] != GROUP
        or record["epoch"] != HISTORY_EPOCH
        or not isinstance(params, dict)
        or set(params) != {"ts_code", "start_date", "end_date"}
        or not _valid_code(params.get("ts_code"))
        or not re.fullmatch(r"[0-9]{8}", str(params.get("start_date", "")))
        or not re.fullmatch(r"[0-9]{8}", str(params.get("end_date", "")))
        or params["start_date"] > params["end_date"]
        or job.get("row_cap") != 1000
        or set(job.get("required_fields", ())) != {"ts_code", "nav_date"}
        or "ann_date" not in job.get("nullable_fields", ())
        or not {"ts_code", "nav_date", "ann_date"}.issubset(
            set(str(job.get("fields", "")).split(","))
        )
    ):
        raise ValueError("Batch contains a non-fund-nav or non-history leaf task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return params["ts_code"]


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if (
        not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256)
        or sha(path) != manifest_sha256
    ):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    required = {
        "schema_version",
        "kind",
        "source",
        "api_counts",
        "all_task_ids_sha256",
        "selection_counts",
        "selection_reasons",
        "universe",
        "selected_funds",
        "boundaries",
        "records",
    }
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "fund_nav_history_exact_batch"
        or manifest.get("source") != {"epoch": HISTORY_EPOCH, "state": "pending"}
        or manifest.get("boundaries") != BOUNDARIES
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch manifest")
    codes = [_validate_record(record) for record in records]
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if manifest.get("api_counts") != {API: len(records)}:
        raise ValueError("API counts mismatch")
    reasons = manifest.get("selection_reasons")
    if (
        not isinstance(reasons, dict)
        or set(reasons) != set(task_ids)
        or any(
            value not in ("pending_split_leaf", "pending_history_root")
            for value in reasons.values()
        )
        or manifest.get("selection_counts")
        != dict(sorted(Counter(reasons.values()).items()))
    ):
        raise ValueError("Selection evidence mismatch")
    selected = manifest.get("selected_funds")
    if (
        not isinstance(selected, list)
        or [row.get("ts_code") for row in selected] != sorted(set(codes))
        or any(
            not isinstance(row, dict)
            or not {"ts_code", "observed_in_fund_basic"} <= set(row)
            or set(row) - {"ts_code", "observed_in_fund_basic", *LIFECYCLE_FIELDS}
            or not _valid_code(row.get("ts_code"))
            or not isinstance(row.get("observed_in_fund_basic"), bool)
            for row in selected
        )
    ):
        raise ValueError("Selected fund context mismatch")
    universe = manifest.get("universe")
    universe_keys = {
        "observed_fund_basic_codes",
        "observed_fund_basic_codes_sha256",
        "planned_fund_nav_codes",
        "planned_fund_nav_codes_sha256",
        "fund_basic_codes_not_planned",
        "planned_codes_not_observed_in_fund_basic",
    }
    if (
        not isinstance(universe, dict)
        or set(universe) != universe_keys
        or any(
            type(universe.get(key)) is not int or universe[key] < 0
            for key in (
                "observed_fund_basic_codes",
                "planned_fund_nav_codes",
                "fund_basic_codes_not_planned",
                "planned_codes_not_observed_in_fund_basic",
            )
        )
        or any(
            not re.fullmatch(r"[a-f0-9]{64}", str(universe.get(key, "")))
            for key in (
                "observed_fund_basic_codes_sha256",
                "planned_fund_nav_codes_sha256",
            )
        )
    ):
        raise ValueError("Invalid universe evidence")
    return manifest


def _records(payload):
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    for item in data.get("items") or []:
        if isinstance(item, list) and len(item) == len(fields):
            yield dict(zip(fields, item, strict=True))


def _fund_universe(root, db):
    funds = {}
    objects = set()
    rows = db.execute(
        "SELECT result FROM jobs INDEXED BY jobs_partition_lookup "
        "WHERE json_extract(job,'$.api_name')='fund_basic' AND result IS NOT NULL"
    )
    for row in rows:
        result = json.loads(row[0])
        object_sha = result.get("object_sha256")
        if (
            not isinstance(object_sha, str)
            or object_sha in objects
            or result.get("status")
            in {
                "transport_error",
                "rate_limited",
                "permission_denied",
                "api_error",
                "invalid_response",
            }
        ):
            continue
        objects.add(object_sha)
        source = root / "objects" / (object_sha + ".json")
        if not source.is_file() or source.is_symlink():
            continue
        for row in _records(json.loads(source.read_bytes())):
            code = row.get("ts_code")
            if not _valid_code(code):
                continue
            saved = funds.setdefault(code, {})
            for field in LIFECYCLE_FIELDS:
                if row.get(field) not in (None, ""):
                    saved[field] = row[field]
    return funds


def prepare(root, output=None, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 1 <= jobs <= MAX_BATCH_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    root = Path(root).resolve()
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        funds = _fund_universe(root, db)
        planned_codes = sorted(
            row[0]
            for row in db.execute(
                "SELECT DISTINCT json_extract(job,'$.params.ts_code') "
                "FROM jobs INDEXED BY jobs_partition_lookup "
                "WHERE json_extract(job,'$.api_name')=? ORDER BY 1",
                (API,),
            )
            if _valid_code(row[0])
        )
        candidates = []
        rows = db.execute(
            "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
            "EXISTS(SELECT 1 FROM partition_children c WHERE c.child_id=j.id) split_leaf "
            "FROM jobs j INDEXED BY jobs_partition_lookup "
            "WHERE j.epoch=? AND json_extract(j.job,'$.api_name')=? "
            "AND j.state='pending'",
            (HISTORY_EPOCH, API),
        )
        for row in rows:
            job = json.loads(row["job"])
            params = job["params"]
            candidates.append(
                (
                    0 if row["split_leaf"] else 1,
                    params["end_date"],
                    params["start_date"],
                    params["ts_code"],
                    row["id"],
                    {
                        "task_id": row["id"],
                        "logical_key": row["logical_key"],
                        "epoch": row["epoch"],
                        "priority": row["priority"],
                        "group_name": row["group_name"],
                        "job": job,
                    },
                )
            )
    finally:
        db.close()
    candidates.sort()
    selected = candidates[:jobs]
    if len(selected) != jobs:
        raise ValueError("Insufficient pending fund_nav history tasks")
    records = [row[-1] for row in selected]
    for record in records:
        _validate_record(record)
    task_ids = sorted(record["task_id"] for record in records)
    reasons = {
        row[-1]["task_id"]: "pending_split_leaf"
        if row[0] == 0
        else "pending_history_root"
        for row in selected
    }
    selected_codes = sorted({row["job"]["params"]["ts_code"] for row in records})
    contexts = []
    for code in selected_codes:
        context = {"ts_code": code, "observed_in_fund_basic": code in funds}
        context.update(funds.get(code, {}))
        contexts.append(context)
    fund_codes = sorted(funds)
    manifest = {
        "schema_version": 1,
        "kind": "fund_nav_history_exact_batch",
        "source": {"epoch": HISTORY_EPOCH, "state": "pending"},
        "api_counts": {API: len(records)},
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "selection_counts": dict(sorted(Counter(reasons.values()).items())),
        "selection_reasons": reasons,
        "universe": {
            "observed_fund_basic_codes": len(fund_codes),
            "observed_fund_basic_codes_sha256": digest(json_bytes(fund_codes)),
            "planned_fund_nav_codes": len(planned_codes),
            "planned_fund_nav_codes_sha256": digest(json_bytes(planned_codes)),
            "fund_basic_codes_not_planned": len(set(fund_codes) - set(planned_codes)),
            "planned_codes_not_observed_in_fund_basic": len(
                set(planned_codes) - set(fund_codes)
            ),
        },
        "selected_funds": contexts,
        "boundaries": BOUNDARIES,
        "records": records,
    }
    if output is not None:
        output = Path(output).resolve()
        if (
            output.exists()
            or output.is_symlink()
            or output == root
            or root in output.parents
        ):
            raise ValueError("Output must not exist and must be outside authority")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            target.write(json_bytes(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--jobs", type=int, default=MAX_BATCH_JOBS)
    args = parser.parse_args()
    result = prepare(args.root, None if args.output == "-" else args.output, args.jobs)
    if args.output == "-":
        sys.stdout.buffer.write(json_bytes(result))
    else:
        print(
            json.dumps(
                {
                    "status": "prepared_not_executed",
                    "jobs": len(result["records"]),
                    "selection_counts": result["selection_counts"],
                    "manifest_sha256": sha(args.output),
                    "all_task_ids_sha256": result["all_task_ids_sha256"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
