#!/usr/bin/env python3
"""Freeze up to 360 pristine dividend history tasks from the authority catalog."""

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


API = "dividend"
EPOCH = "history"
GROUP = "equity_event"
MARKETS = ("SH", "SZ", "BJ")
MAX_BATCH_JOBS = 360
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")


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


def fixed_release_evidence(root, release_id, manifest_sha256):
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
    params = job.get("params") if isinstance(job, dict) else None
    code = params.get("ts_code") if isinstance(params, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("api_name") != API
        or not isinstance(params, dict)
        or set(params) != {"ts_code"}
        or not re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", str(code))
        or record["epoch"] != EPOCH
        or record["group_name"] != GROUP
        or record["state"] != "pending"
        or record["tries"] != 0
        or type(record["priority"]) is not int
    ):
        raise ValueError("Batch contains a non-pristine dividend history task")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return code


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "kind",
        "source",
        "api_counts",
        "market_counts",
        "selected_codes_sha256",
        "all_task_ids_sha256",
        "records",
    }:
        raise ValueError("Invalid batch manifest")
    source = manifest["source"]
    records = manifest["records"]
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "dividend_history_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "authority_config_sha256",
            "preparation_sha256",
            "epoch",
            "group_name",
            "state",
            "tries",
            "selection",
        }
        or source.get("epoch") != EPOCH
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or source.get("tries") != 0
        or source.get("selection")
        != "market_round_robin_pristine_stock_history_without_prior_attempts"
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or RELEASE_RE.fullmatch(source["release_id"]).group(1)
        != source.get("release_manifest_sha256")
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid batch source")
    for key in (
        "release_manifest_sha256",
        "authority_config_sha256",
        "preparation_sha256",
    ):
        _hash(source.get(key), key)
    codes = [_validate_record(record) for record in records]
    task_ids = sorted(record["task_id"] for record in records)
    markets = Counter(code.rsplit(".", 1)[1] for code in codes)
    if (
        len(codes) != len(set(codes))
        or len(task_ids) != len(set(task_ids))
        or manifest.get("api_counts") != {API: len(records)}
        or manifest.get("market_counts") != dict(sorted(markets.items()))
        or manifest.get("selected_codes_sha256") != digest(json_bytes(sorted(codes)))
        or manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids))
    ):
        raise ValueError("Batch selection evidence mismatch")
    return manifest


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
    release = fixed_release_evidence(root, release_id, release_manifest_sha256)
    config_sha256 = sha(_regular(root / "pipeline-config.json", "Pipeline config"))
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
                "j.state,j.tries FROM jobs j INDEXED BY jobs_ready_api_history "
                "WHERE j.epoch=? AND json_extract(j.job,'$.api_name')=? "
                "AND j.group_name=? AND j.state='pending' AND j.tries=0 "
                "AND NOT EXISTS(SELECT 1 FROM attempts a WHERE a.job_id=j.id) "
                "ORDER BY json_extract(j.job,'$.params.ts_code'),j.id",
                (EPOCH, API, GROUP),
            ).fetchall()
        finally:
            db.close()
    buckets = {market: [] for market in MARKETS}
    for row in rows:
        record = _record(row)
        code = _validate_record(record)
        buckets[code.rsplit(".", 1)[1]].append(record)
    records = []
    while len(records) < jobs and any(buckets.values()):
        for market in MARKETS:
            if buckets[market]:
                records.append(buckets[market].pop(0))
                if len(records) == jobs:
                    break
    if len(records) != jobs:
        raise ValueError("Insufficient pristine dividend history tasks")
    codes = [record["job"]["params"]["ts_code"] for record in records]
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "dividend_history_exact_batch",
        "source": {
            **release,
            "authority_config_sha256": config_sha256,
            "preparation_sha256": preparation_sha256(),
            "epoch": EPOCH,
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "selection": (
                "market_round_robin_pristine_stock_history_without_prior_attempts"
            ),
        },
        "api_counts": {API: len(records)},
        "market_counts": dict(
            sorted(Counter(code.rsplit(".", 1)[1] for code in codes).items())
        ),
        "selected_codes_sha256": digest(json_bytes(sorted(codes))),
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
                "market_counts": result["market_counts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "authority_config_sha256": result["source"]["authority_config_sha256"],
                "preparation_sha256": result["source"]["preparation_sha256"],
                "upstream_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
