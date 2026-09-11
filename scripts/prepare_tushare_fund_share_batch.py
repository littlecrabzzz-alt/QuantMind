#!/usr/bin/env python3
"""Pin a recent-first, market-fair batch of queued fund_share history."""

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


API = "fund_share"
GROUP = "market"
EPOCH = "history"
MARKETS = ("SH", "SZ")
MAX_BATCH_JOBS = 360
SELECTION = "newest_pristine_rounds_interleaved_by_market"
SUPPORTED_SELECTIONS = {
    SELECTION,
    "newest_pending_rounds_interleaved_by_market",
    "oldest_pending_rounds_interleaved_by_market",
}
SEMANTIC_DEDUP = "api_params_fields_across_epochs_exclude_attempted_or_nonpending"
BOUNDARIES = {
    "history_start_is_request_scope_not_verified_availability": True,
    "non_trading_day_empty_is_verified_absence": False,
    "fund_universe_complete": False,
    "known_at_verified": False,
    "planning_complete_is_data_complete": False,
}
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
    job = record["job"]
    params = job.get("params") if isinstance(job, dict) else None
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
        or job.get("fields") != "fd_share,trade_date,ts_code"
        or job.get("row_cap") != 2000
        or job.get("required_fields") != ["ts_code", "trade_date"]
        or job.get("nullable_fields") != []
        or job.get("positive_fields") != []
        or record["group_name"] != GROUP
        or record["epoch"] != EPOCH
        or not isinstance(record["priority"], int)
        or not isinstance(params, dict)
        or set(params) != {"market", "trade_date"}
        or params.get("market") not in MARKETS
        or not DAY.fullmatch(str(params.get("trade_date", "")))
    ):
        raise ValueError("Batch contains a non-fund-share history task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return params


def _selected_stats(records):
    params = [_validate_record(record) for record in records]
    markets = Counter(item["market"] for item in params)
    dates = [item["trade_date"] for item in params]
    return {
        "jobs": len(records),
        "market_counts": dict(sorted(markets.items())),
        "trade_date_min": min(dates),
        "trade_date_max": max(dates),
    }


def _request_signature(job):
    return digest(json_bytes([API, job["params"], job["fields"]]))


def _record(row):
    return {
        "task_id": row["id"],
        "logical_key": row["logical_key"],
        "epoch": row["epoch"],
        "priority": row["priority"],
        "group_name": row["group_name"],
        "job": json.loads(row["job"]),
    }


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    legacy_source = {
        "api_name",
        "group_name",
        "epoch",
        "state",
        "selection",
        "pending_jobs",
    }
    current_source = {
        "api_name",
        "group_name",
        "epoch",
        "state",
        "tries",
        "attempts",
        "semantic_dedup",
        "selection",
        "eligible_jobs",
        "eligible_task_ids_sha256",
    }
    if (
        not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256)
        or sha(path) != manifest_sha256
    ):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    records = manifest.get("records") if isinstance(manifest, dict) else None
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "kind",
            "source",
            "api_counts",
            "all_task_ids_sha256",
            "selected",
            "boundaries",
            "records",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "fund_share_history_exact_batch"
        or not isinstance(source, dict)
        or set(source) not in (legacy_source, current_source)
        or source.get("api_name") != API
        or source.get("group_name") != GROUP
        or source.get("epoch") != EPOCH
        or source.get("state") != "pending"
        or source.get("selection") not in SUPPORTED_SELECTIONS
        or manifest.get("boundaries") != BOUNDARIES
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch manifest")
    if set(source) == current_source:
        if (
            source.get("selection") != SELECTION
            or type(source.get("tries")) is not int
            or source["tries"] != 0
            or type(source.get("attempts")) is not int
            or source["attempts"] != 0
            or source.get("semantic_dedup") != SEMANTIC_DEDUP
            or type(source.get("eligible_jobs")) is not int
            or source["eligible_jobs"] < 1
            or not re.fullmatch(
                r"[a-f0-9]{64}", str(source.get("eligible_task_ids_sha256", ""))
            )
        ):
            raise ValueError("Invalid batch source")
        source_jobs = source["eligible_jobs"]
    else:
        if (
            type(source.get("pending_jobs")) is not int
            or source["pending_jobs"] < 1
        ):
            raise ValueError("Invalid batch source")
        source_jobs = source["pending_jobs"]
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if manifest.get("api_counts") != {API: len(records)}:
        raise ValueError("API counts mismatch")
    if manifest.get("selected") != _selected_stats(records):
        raise ValueError("Selected inventory mismatch")
    if source_jobs < len(records):
        raise ValueError("Source inventory is smaller than selected inventory")
    return manifest


def prepare(root, output, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 1 <= jobs <= MAX_BATCH_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    root, requested_output = Path(root).resolve(), Path(output)
    if requested_output.exists() or requested_output.is_symlink():
        raise ValueError("Output must not exist or be inside authority")
    output = requested_output.resolve()
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    if output == root or root in output.parents:
        raise ValueError("Output must not exist or be inside authority")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        db.execute("BEGIN")
        candidates = db.execute(
            "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
            "json_extract(j.job,'$.params.market') market,"
            "json_extract(j.job,'$.params.trade_date') trade_date "
            "FROM jobs j INDEXED BY jobs_ready_api_history WHERE "
            "j.state='pending' AND j.tries=0 AND j.group_name=? AND j.epoch=? "
            "AND json_extract(j.job,'$.api_name')=? AND NOT EXISTS("
            "SELECT 1 FROM attempts a WHERE a.job_id=j.id)",
            (GROUP, EPOCH, API),
        ).fetchall()
        blocked_signatures = set()
        other_epochs = [
            row[0]
            for row in db.execute("SELECT DISTINCT epoch FROM jobs ORDER BY epoch")
        ]
        for other_epoch in other_epochs:
            blocked_signatures.update(
                _request_signature(json.loads(row["job"]))
                for row in db.execute(
                    "SELECT j.job FROM jobs j INDEXED BY jobs_partition_lookup "
                    "WHERE j.epoch=? AND json_extract(j.job,'$.api_name')=? AND "
                    "(j.state<>'pending' OR j.tries<>0 OR EXISTS("
                    "SELECT 1 FROM attempts a WHERE a.job_id=j.id))",
                    (other_epoch, API),
                )
            )
    finally:
        db.close()
    winners = {}
    for row in candidates:
        record = _record(row)
        try:
            _validate_record(record)
        except ValueError:
            continue
        signature = _request_signature(record["job"])
        if signature not in blocked_signatures:
            saved = winners.get(signature)
            if saved is None or row["id"] < saved["id"]:
                winners[signature] = row
    eligible = sorted(winners.values(), key=lambda row: row["id"])
    by_market = {market: [] for market in MARKETS}
    for row in eligible:
        by_market[row["market"]].append(row)
    for rows in by_market.values():
        rows.sort(key=lambda row: (-int(row["trade_date"]), row["id"]))
    ranked = [
        (request_round, -int(row["trade_date"]), market, row["id"], row)
        for market, market_rows in by_market.items()
        for request_round, row in enumerate(market_rows, 1)
    ]
    ranked.sort()
    rows = [item[-1] for item in ranked[:jobs]]
    if len(rows) != jobs:
        raise ValueError("Insufficient pristine fund_share history tasks")
    records = [_record(row) for row in rows]
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "fund_share_history_exact_batch",
        "source": {
            "api_name": API,
            "group_name": GROUP,
            "epoch": EPOCH,
            "state": "pending",
            "tries": 0,
            "attempts": 0,
            "semantic_dedup": SEMANTIC_DEDUP,
            "selection": SELECTION,
            "eligible_jobs": len(eligible),
            "eligible_task_ids_sha256": digest(
                json_bytes(sorted(row["id"] for row in eligible))
            ),
        },
        "api_counts": {API: len(records)},
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "selected": _selected_stats(records),
        "boundaries": BOUNDARIES,
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
    parser.add_argument("--jobs", type=int, default=MAX_BATCH_JOBS)
    args = parser.parse_args()
    result = prepare(args.root, args.output, args.jobs)
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "selected": result["selected"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
