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
MARKETS = ("SH", "SZ", "BJ")
MAX_JOBS_PER_API = 120
MAX_BATCH_JOBS = len(ALLOWED_APIS) * MAX_JOBS_PER_API
# One recent epoch can already contain the latest report for the whole exchange.
# Read deeply enough to reach the next cohort while keeping the query bounded.
CANDIDATE_MULTIPLIER = 100
SQLITE_PARAMETER_BATCH = 500
SELECTION_MODE = (
    "latest_period_report_type_exchange_balanced_"
    "common_first_independent_api_fill_code_specific_leaves"
)


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
        or not re.fullmatch(
            r"[0-9]{6}\.(SH|SZ|BJ)", str(job["params"].get("ts_code", ""))
        )
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
    if (
        not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256)
        or sha(path) != manifest_sha256
    ):
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


def _cross_epoch_duplicates(db, candidates, epoch):
    logical_keys = {
        record["logical_key"]
        for rows in candidates.values()
        for record in rows.values()
    }
    excluded = set()
    other_epochs = [
        row[0]
        for row in db.execute("SELECT DISTINCT epoch FROM jobs ORDER BY epoch")
        if row[0] != epoch
    ]
    for other_epoch in other_epochs:
        task_ids = {
            digest(json_bytes([logical_key, other_epoch])): logical_key
            for logical_key in logical_keys
        }
        ids = list(task_ids)
        for start in range(0, len(ids), SQLITE_PARAMETER_BATCH):
            batch = ids[start : start + SQLITE_PARAMETER_BATCH]
            placeholders = ",".join("?" for _ in batch)
            for task_id, state in db.execute(
                f"SELECT id,state FROM jobs WHERE id IN ({placeholders})", batch
            ):
                if state != "pending" or other_epoch < epoch:
                    excluded.add(task_ids[task_id])
    return excluded


def _balanced_selection(keys, limit):
    cohorts = {}
    for key in keys:
        cohorts.setdefault((key[0], key[1]), []).append(key)
    selected = []
    for cohort in sorted(
        cohorts,
        key=lambda key: (-int(key[0]), int(key[1]) if key[1] is not None else -1),
    ):
        buckets = {
            market: iter(
                sorted(key for key in cohorts[cohort] if key[2].endswith("." + market))
            )
            for market in MARKETS
        }
        while len(selected) < limit:
            added = False
            for market in MARKETS:
                key = next(buckets[market], None)
                if key is not None:
                    selected.append(key)
                    added = True
                    if len(selected) == limit:
                        break
            if not added:
                break
        if len(selected) == limit:
            break
    return selected


def prepare(root, output, epoch, jobs_per_api=MAX_JOBS_PER_API):
    if not re.fullmatch(r"(?:[0-9]{8}|history)", epoch):
        raise ValueError("Epoch must be YYYYMMDD or history")
    if type(jobs_per_api) is not int or not 1 <= jobs_per_api <= MAX_JOBS_PER_API:
        raise ValueError("jobs_per_api must be between 1 and 120")
    root, output = Path(root).resolve(), Path(output).resolve()
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    if (
        output.exists()
        or output.is_symlink()
        or output == root
        or root in output.parents
    ):
        raise ValueError("Output must not exist")
    candidates = {}
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        market_candidates = (
            (jobs_per_api + len(MARKETS) - 1) // len(MARKETS)
        ) * CANDIDATE_MULTIPLIER
        for api in ALLOWED_APIS:
            candidates[api] = {}
            for market in MARKETS:
                rows = db.execute(
                    "SELECT id,logical_key,epoch,job,priority,group_name FROM jobs "
                    "WHERE epoch=? AND json_extract(job,'$.api_name')=? "
                    "AND state='pending' AND json_extract(job,'$.params.ts_code') GLOB ? "
                    "ORDER BY json_extract(job,'$.params.period') DESC,"
                    "CAST(json_extract(job,'$.params.report_type') AS INTEGER),"
                    "json_extract(job,'$.params.ts_code'),id LIMIT ?",
                    (epoch, api, "*." + market, market_candidates),
                ).fetchall()
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
        excluded = _cross_epoch_duplicates(db, candidates, epoch)
    finally:
        db.close()
    eligible = {
        api: {
            key
            for key, record in candidates[api].items()
            if record["logical_key"] not in excluded
        }
        for api in ALLOWED_APIS
    }
    common = set.intersection(*(eligible[api] for api in ALLOWED_APIS))
    common_selected = _balanced_selection(common, jobs_per_api)
    common_selected_set = set(common_selected)
    selected = {
        api: common_selected
        + _balanced_selection(
            eligible[api] - common_selected_set,
            jobs_per_api - len(common_selected),
        )
        for api in ALLOWED_APIS
    }
    records = [
        candidates[api][key] for api in ALLOWED_APIS for key in selected[api]
    ]
    if not records:
        raise ValueError("No eligible pending financial statement leaves")
    counts = Counter(_validate_record(record) for record in records)
    records.sort(
        key=lambda row: (ALLOWED_APIS.index(row["job"]["api_name"]), row["task_id"])
    )
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "financial_pit_exact_batch",
        "source": {
            "epoch": epoch,
            "state": "pending",
            "selection": SELECTION_MODE,
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
