#!/usr/bin/env python3
"""Freeze pristine fina_mainbz year-window tasks against one fixed release."""

from __future__ import annotations

import argparse
from collections import Counter, deque
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


API = "fina_mainbz"
EXPECTED_API_RPM = 500
EXPECTED_ACCOUNT_RPM = 500
GROUP = "research_extra"
EPOCH = "history"
MARKETS = ("SH", "SZ", "BJ")
TYPES = ("P", "D", "I")
MAX_BATCH_JOBS = 360
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
DAY_RE = re.compile(r"[0-9]{8}")
CODE_RE = re.compile(r"[A-Z0-9]+\.(SH|SZ|BJ)")
EXPECTED_FIELDS = (
    "bz_code,bz_cost,bz_item,bz_profit,bz_sales,curr_type,end_date,ts_code,"
    "update_flag"
)
BOUNDARIES = {
    "output_end_date_is_report_period": True,
    "request_report_period_bounds_preserved": True,
    "request_type_identity_preserved": True,
    "source_company_identity_preserved": True,
    "announcement_time_available": False,
    "known_at_verified": False,
    "pit_verified": False,
    "history_completeness_verified": False,
    "empty_response_proves_absence": False,
}


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
        != "points_regular_allowlist_doc290"
        or resolved.get("review_required") is not False
    ):
        raise ValueError("Unexpected fina_mainbz rate contract")
    account_rpm = positive_int(
        config.get("requests_per_minute"), "account request rate"
    )
    rollout = config.get("rollout_account_rpm")
    if rollout is not None:
        account_rpm = min(
            account_rpm, positive_int(rollout, "rollout account rate")
        )
    if account_rpm != EXPECTED_ACCOUNT_RPM:
        raise ValueError("Unexpected account rate contract")
    return {
        "api": {"rpm": EXPECTED_API_RPM, "source": resolved["source"]},
        "account": {"rpm": EXPECTED_ACCOUNT_RPM, "source": "configured_shared_gate"},
    }


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
        "job": json.loads(row["job"]),
    }


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
        or job.get("fields") != EXPECTED_FIELDS
        or job.get("row_cap") != 100
        or job.get("required_fields") != ["ts_code", "end_date", "bz_item"]
        or job.get("nullable_fields")
        != ["bz_code", "bz_sales", "bz_profit", "bz_cost", "curr_type", "update_flag"]
        or job.get("positive_fields") != []
        or not isinstance(params, dict)
        or set(params) != {"ts_code", "type", "start_date", "end_date"}
        or CODE_RE.fullmatch(str(params.get("ts_code", ""))) is None
        or params.get("type") not in TYPES
        or DAY_RE.fullmatch(str(params.get("start_date", ""))) is None
        or DAY_RE.fullmatch(str(params.get("end_date", ""))) is None
        or params["start_date"] > params["end_date"]
        or record["epoch"] != EPOCH
        or record["group_name"] != GROUP
        or record["state"] != "pending"
        or record["tries"] != 0
        or record["attempts"] != 0
        or type(record["priority"]) is not int
    ):
        raise ValueError("Batch contains a non-pristine fina_mainbz history task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return params


def _selected(records):
    params = [_validate_record(record) for record in records]
    codes = sorted({item["ts_code"] for item in params})
    return {
        "jobs": len(records),
        "company_count": len(codes),
        "company_ids_sha256": digest(json_bytes(codes)),
        "market_counts": dict(
            sorted(
                Counter(
                    item["ts_code"].rsplit(".", 1)[1] for item in params
                ).items()
            )
        ),
        "type_counts": dict(sorted(Counter(item["type"] for item in params).items())),
        "report_period_start_min": min(item["start_date"] for item in params),
        "report_period_start_max": max(item["start_date"] for item in params),
        "report_period_end_min": min(item["end_date"] for item in params),
        "report_period_end_max": max(item["end_date"] for item in params),
    }


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
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
            "rate_contracts",
            "api_counts",
            "all_task_ids_sha256",
            "selected",
            "boundaries",
            "records",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "fina_mainbz_history_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "current_pointer_sha256",
            "api_name",
            "group_name",
            "epoch",
            "state",
            "tries",
            "attempts",
            "selection",
            "eligible_tasks",
            "eligible_task_ids_sha256",
            "authority_config_sha256",
            "preparation_sha256",
        }
        or source.get("api_name") != API
        or source.get("group_name") != GROUP
        or source.get("epoch") != EPOCH
        or source.get("state") != "pending"
        or source.get("tries") != 0
        or source.get("attempts") != 0
        or source.get("selection")
        != "report_window_desc_type_market_round_robin_pristine_tasks"
        or source.get("preparation_sha256") != preparation_sha256()
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or source["release_id"]
        != "data-" + str(source.get("release_manifest_sha256", ""))
        or type(source.get("eligible_tasks")) is not int
        or source["eligible_tasks"] < 1
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
        or manifest.get("boundaries") != BOUNDARIES
        or manifest.get("rate_contracts", {}).get("api", {}).get("rpm")
        != EXPECTED_API_RPM
        or not str(
            manifest.get("rate_contracts", {}).get("api", {}).get("source", "")
        ).startswith("points_regular_allowlist_doc290")
        or manifest.get("rate_contracts", {}).get("account")
        != {"rpm": EXPECTED_ACCOUNT_RPM, "source": "configured_shared_gate"}
    ):
        raise ValueError("Invalid batch manifest")
    for key in (
        "release_manifest_sha256",
        "current_pointer_sha256",
        "authority_config_sha256",
        "preparation_sha256",
        "eligible_task_ids_sha256",
    ):
        _hash(source.get(key), key)
    task_ids = sorted(record["task_id"] for record in records)
    if (
        len(task_ids) != len(set(task_ids))
        or manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids))
        or manifest.get("api_counts") != {API: len(records)}
        or manifest.get("selected") != _selected(records)
        or source["eligible_tasks"] < len(records)
    ):
        raise ValueError("Batch selection evidence mismatch")
    return manifest


def _fair_selection(inventory, jobs):
    buckets = {
        (kind, market): deque()
        for kind in TYPES
        for market in MARKETS
    }
    for record in inventory:
        params = _validate_record(record)
        buckets[(params["type"], params["ts_code"].rsplit(".", 1)[1])].append(record)
    records = []
    while len(records) < jobs and any(buckets.values()):
        for kind in TYPES:
            for market in MARKETS:
                bucket = buckets[(kind, market)]
                if bucket:
                    records.append(bucket.popleft())
                    if len(records) == jobs:
                        return records
    return records


def eligible_records(db):
    rows = db.execute(
        "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
        "j.state,j.tries,(SELECT COUNT(*) FROM attempts a "
        "WHERE a.job_id=j.id) attempts "
        "FROM jobs j INDEXED BY jobs_ready_api_history "
        "WHERE j.epoch=? AND json_extract(j.job,'$.api_name')=? "
        "AND j.group_name=? AND j.state='pending' AND j.tries=0 "
        "AND NOT EXISTS(SELECT 1 FROM attempts a WHERE a.job_id=j.id) "
        "AND json_type(j.job,'$.params.start_date')='text' "
        "AND json_type(j.job,'$.params.end_date')='text' "
        "ORDER BY json_extract(j.job,'$.params.end_date') DESC,"
        "json_extract(j.job,'$.params.start_date') DESC,"
        "json_extract(j.job,'$.params.type'),"
        "json_extract(j.job,'$.params.ts_code'),j.id",
        (EPOCH, API, GROUP),
    ).fetchall()
    return [_record(row) for row in rows]


def prepare(root, output, release_id, release_manifest_sha256, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 1 <= jobs <= MAX_BATCH_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    root, requested_output = Path(root).resolve(), Path(output)
    if requested_output.exists() or requested_output.is_symlink():
        raise ValueError("Output must not exist or be inside authority")
    output = requested_output.resolve()
    if output == root or root in output.parents:
        raise ValueError("Output must not exist or be inside authority")
    _regular(root / "ENABLED", "Enable marker")
    with _read_lock(root):
        release = release_evidence(root, release_id, release_manifest_sha256)
        config_path = _regular(root / "pipeline-config.json", "Pipeline config")
        config_bytes = config_path.read_bytes()
        rates = rate_contracts(json.loads(config_bytes))
        database = _regular(root / "pipeline.sqlite", "Pipeline database")
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            inventory = eligible_records(db)
        finally:
            db.close()
    if len(inventory) < jobs:
        raise ValueError("Insufficient pristine fina_mainbz history tasks")
    records = _fair_selection(inventory, jobs)
    if len(records) != jobs:
        raise ValueError("Insufficient valid fina_mainbz history tasks")
    eligible_ids = sorted(record["task_id"] for record in inventory)
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "fina_mainbz_history_exact_batch",
        "source": {
            **release,
            "api_name": API,
            "group_name": GROUP,
            "epoch": EPOCH,
            "state": "pending",
            "tries": 0,
            "attempts": 0,
            "selection": "report_window_desc_type_market_round_robin_pristine_tasks",
            "eligible_tasks": len(inventory),
            "eligible_task_ids_sha256": digest(json_bytes(eligible_ids)),
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
        },
        "rate_contracts": rates,
        "api_counts": {API: len(records)},
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "selected": _selected(records),
        "boundaries": BOUNDARIES,
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
        args.root, args.output, args.release_id, args.release_manifest_sha256, args.jobs
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "selected": result["selected"],
                "rate_contracts": result["rate_contracts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "eligible_task_ids_sha256": result["source"][
                    "eligible_task_ids_sha256"
                ],
                "authority_config_sha256": result["source"]["authority_config_sha256"],
                "preparation_sha256": result["source"]["preparation_sha256"],
                "upstream_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
