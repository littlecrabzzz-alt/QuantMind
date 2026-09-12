#!/usr/bin/env python3
"""Freeze balanced pristine top10 holder sibling pairs from one fixed authority."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
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

APIS = ("top10_holders", "top10_floatholders")
GROUP = "equity_event"
MARKETS = ("SH", "SZ", "BJ")
MAX_PAIRS = 180
MAX_JOBS = MAX_PAIRS * len(APIS)
CANDIDATE_MULTIPLIER = 20
SQLITE_BATCH = 400
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
CODE_PATHS = (
    "backend/shared/tushare_pipeline.py",
    "backend/shared/tushare_intake.py",
    "backend/shared/tushare_equity_event_contracts.py",
    "backend/shared/tushare_rate_policy.py",
    "config/tushare-catalog.json",
    "scripts/run_tushare_fund_nav_batch.py",
    "scripts/prepare_tushare_top10_holders_batch.py",
    "scripts/run_tushare_top10_holders_batch.py",
)
SELECTION = "latest_bounded_report_window_complete_api_pair_market_balanced_pristine"


def sha(path):
    return digest(Path(path).read_bytes())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"Invalid {label} SHA-256")
    return value


def code_sha256():
    return {path: sha(REPO / path) for path in CODE_PATHS}


@contextmanager
def _read_lock(root):
    path = _regular(Path(root) / "pipeline.lock", "Pipeline lock")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"Invalid {label}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc


def _pair_key(record):
    job = record.get("job") if isinstance(record, dict) else None
    params = job.get("params") if isinstance(job, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("api_name") not in APIS
        or not isinstance(params, dict)
        or set(params) != {"ts_code", "start_date", "end_date"}
        or not re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", str(params.get("ts_code", "")))
        or record.get("group_name") != GROUP
        or not isinstance(record.get("epoch"), str)
        or type(record.get("priority")) is not int
    ):
        raise ValueError("Invalid top10 bounded-window task")
    start = _date(params["start_date"], "start_date")
    end = _date(params["end_date"], "end_date")
    if start > end:
        raise ValueError("Reversed report-period window")
    return record["epoch"], params["start_date"], params["end_date"], params["ts_code"]


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
    key = _pair_key(record)
    if (
        record["state"] != "pending"
        or type(record["tries"]) is not int
        or record["tries"] != 0
        or type(record["attempts"]) is not int
        or record["attempts"] != 0
    ):
        raise ValueError("Batch contains a non-pristine task")
    logical = digest(json_bytes(record["job"]))
    task_id = digest(json_bytes([logical, record["epoch"]]))
    if logical != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return record["job"]["api_name"], key


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "kind",
        "source",
        "selected",
        "api_counts",
        "all_task_ids_sha256",
        "all_logical_keys_sha256",
        "records",
    }:
        raise ValueError("Invalid batch manifest")
    source, selected, records = (
        manifest["source"],
        manifest["selected"],
        manifest["records"],
    )
    release_match = (
        RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        if isinstance(source, dict)
        else None
    )
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "top10_holders_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "current_pointer_sha256",
            "authority_config_sha256",
            "code_sha256",
            "epoch",
            "group_name",
            "state",
            "tries",
            "attempts",
            "selection",
            "eligible_pairs",
            "history_manifest_sha256",
        }
        or not release_match
        or release_match.group(1) != source.get("release_manifest_sha256")
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or type(source.get("tries")) is not int
        or source["tries"] != 0
        or type(source.get("attempts")) is not int
        or source["attempts"] != 0
        or not isinstance(source.get("epoch"), str)
        or not re.fullmatch(r"(?:[0-9]{8}|history)", source["epoch"])
        or source.get("selection") != SELECTION
        or not isinstance(source.get("eligible_pairs"), int)
        or source["eligible_pairs"] < 1
        or not isinstance(source.get("history_manifest_sha256"), list)
        or source["history_manifest_sha256"]
        != sorted(set(source["history_manifest_sha256"]))
        or not isinstance(source.get("code_sha256"), dict)
        or set(source["code_sha256"]) != set(CODE_PATHS)
        or not isinstance(records, list)
        or not 2 <= len(records) <= MAX_JOBS
        or len(records) % 2
    ):
        raise ValueError("Invalid batch source")
    for key in (
        "release_manifest_sha256",
        "current_pointer_sha256",
        "authority_config_sha256",
    ):
        _hash(source.get(key), key)
    for key, value in source["code_sha256"].items():
        _hash(value, key)
    for value in source["history_manifest_sha256"]:
        _hash(value, "history manifest")
    checked = [_validate_record(record) for record in records]
    if any(record["epoch"] != source["epoch"] for record in records):
        raise ValueError("Record epoch does not match batch source")
    counts = Counter(api for api, _ in checked)
    if counts != Counter({api: len(records) // 2 for api in APIS}):
        raise ValueError("API counts are not a complete balanced pair set")
    pair_members = {}
    for api, key in checked:
        pair_members.setdefault(key, set()).add(api)
    if any(members != set(APIS) for members in pair_members.values()):
        raise ValueError("Incomplete top10 sibling pair")
    pair_keys = [list(key) for key in sorted(pair_members)]
    if (
        not isinstance(selected, dict)
        or set(selected)
        != {"pair_count", "pair_keys_sha256", "min_end_date", "max_end_date"}
        or selected["pair_count"] != len(pair_keys)
        or source["eligible_pairs"] < len(pair_keys)
        or selected["pair_keys_sha256"] != digest(json_bytes(pair_keys))
        or selected["min_end_date"] != min(key[2] for key in pair_keys)
        or selected["max_end_date"] != max(key[2] for key in pair_keys)
        or manifest["api_counts"] != dict(sorted(counts.items()))
    ):
        raise ValueError("Selected pair inventory mismatch")
    task_ids = sorted(record["task_id"] for record in records)
    logicals = sorted(record["logical_key"] for record in records)
    if len(task_ids) != len(set(task_ids)) or len(logicals) != len(set(logicals)):
        raise ValueError("Duplicate task or logical request")
    if manifest["all_task_ids_sha256"] != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
    if manifest["all_logical_keys_sha256"] != digest(json_bytes(logicals)):
        raise ValueError("Logical request inventory hash mismatch")
    return manifest


def _history_inventory(paths):
    hashes, task_ids, logicals = [], set(), set()
    for path in paths:
        path = _regular(path, "History manifest")
        value = sha(path)
        prior = verify_manifest(path, value)
        hashes.append(value)
        task_ids.update(row["task_id"] for row in prior["records"])
        logicals.update(row["logical_key"] for row in prior["records"])
    if len(hashes) != len(set(hashes)):
        raise ValueError("Duplicate history manifest")
    return sorted(hashes), task_ids, logicals


def _cross_epoch_blockers(db, records, epoch):
    logical_to_task = {}
    other_epochs = [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT epoch FROM jobs WHERE epoch<>?", (epoch,)
        )
    ]
    for record in records:
        logical = record["logical_key"]
        for other_epoch in other_epochs:
            logical_to_task[digest(json_bytes([logical, other_epoch]))] = logical
    blocked = set()
    ids = list(logical_to_task)
    for offset in range(0, len(ids), SQLITE_BATCH):
        batch = ids[offset : offset + SQLITE_BATCH]
        marks = ",".join("?" for _ in batch)
        for (task_id,) in db.execute(
            f"SELECT id FROM jobs WHERE id IN ({marks})", batch
        ):
            blocked.add(logical_to_task[task_id])
    return blocked


def _choose_pair_keys(keys, count):
    cohorts = {}
    for key in keys:
        cohorts.setdefault((key[2], key[1]), []).append(key)
    selected = []
    for cohort in sorted(cohorts, reverse=True):
        buckets = {
            market: iter(
                sorted(
                    (k for k in cohorts[cohort] if k[3].endswith("." + market)),
                    key=lambda x: x[3],
                )
            )
            for market in MARKETS
        }
        while len(selected) < count:
            added = False
            for market in MARKETS:
                value = next(buckets[market], None)
                if value is not None:
                    selected.append(value)
                    added = True
                    if len(selected) == count:
                        break
            if not added:
                break
        if len(selected) == count:
            break
    return selected


def prepare(
    root,
    output,
    epoch,
    release_id,
    release_manifest_sha256,
    *,
    pair_count=MAX_PAIRS,
    history_manifests=(),
):
    if not isinstance(epoch, str) or not re.fullmatch(r"(?:[0-9]{8}|history)", epoch):
        raise ValueError("Epoch must be YYYYMMDD or history")
    if type(pair_count) is not int or not 1 <= pair_count <= MAX_PAIRS:
        raise ValueError("pair_count must be between 1 and 180")
    match = RELEASE_RE.fullmatch(str(release_id))
    if not match or match.group(1) != _hash(
        release_manifest_sha256, "release manifest"
    ):
        raise ValueError("Release ID must derive from its manifest SHA-256")
    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output.is_symlink()
        or output == root
        or root in output.parents
    ):
        raise ValueError("Output must be a new file outside authority")
    manifest_path = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(manifest_path) != release_manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    history_hashes, old_tasks, old_logicals = _history_inventory(history_manifests)
    records_by_api = {api: {} for api in APIS}
    with _read_lock(root):
        pointer_path = _regular(root / "CURRENT.json", "Current pointer")
        pointer_bytes = pointer_path.read_bytes()
        if json.loads(pointer_bytes) != {
            "manifest_sha256": release_manifest_sha256,
            "release_id": release_id,
        }:
            raise ValueError("Explicit release is not CURRENT")
        config_sha = sha(_regular(root / "pipeline-config.json", "Pipeline config"))
        db_path = _regular(root / "pipeline.sqlite", "Pipeline database")
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=0)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA busy_timeout=0")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            limit = pair_count * CANDIDATE_MULTIPLIER
            for api in APIS:
                for market in MARKETS:
                    rows = db.execute(
                        "SELECT j.id,j.logical_key,j.epoch,j.priority,j.group_name,j.state,j.tries,j.result,j.job,"
                        "(SELECT COUNT(*) FROM attempts a WHERE a.job_id=j.id) attempts "
                        "FROM jobs j INDEXED BY jobs_ready_api_history "
                        "WHERE j.epoch=? AND j.group_name=? AND j.state='pending' AND j.tries=0 "
                        "AND j.result IS NULL AND json_extract(j.job,'$.api_name')=? "
                        "AND json_extract(j.job,'$.params.ts_code') GLOB ? "
                        "ORDER BY json_extract(j.job,'$.params.end_date') DESC,"
                        "json_extract(j.job,'$.params.start_date') DESC,"
                        "json_extract(j.job,'$.params.ts_code'),j.id LIMIT ?",
                        (epoch, GROUP, api, "*." + market, limit),
                    ).fetchall()
                    for row in rows:
                        record = {
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
                        try:
                            _, key = _validate_record(record)
                        except ValueError:
                            continue
                        if (
                            record["task_id"] in old_tasks
                            or record["logical_key"] in old_logicals
                        ):
                            continue
                        records_by_api[api][key] = record
            candidate_records = [
                record for rows in records_by_api.values() for record in rows.values()
            ]
            blocked = _cross_epoch_blockers(db, candidate_records, epoch)
        finally:
            db.close()
        if pointer_path.read_bytes() != pointer_bytes:
            raise RuntimeError("CURRENT changed during frozen selection")
    eligible = set.intersection(*(set(records_by_api[api]) for api in APIS))
    eligible = {
        key
        for key in eligible
        if all(records_by_api[api][key]["logical_key"] not in blocked for api in APIS)
    }
    chosen = _choose_pair_keys(eligible, pair_count)
    if len(chosen) != pair_count:
        raise ValueError(f"Only {len(chosen)} complete pristine pairs are eligible")
    records = [records_by_api[api][key] for key in chosen for api in APIS]
    records.sort(key=lambda row: row["task_id"])
    task_ids = sorted(row["task_id"] for row in records)
    logicals = sorted(row["logical_key"] for row in records)
    pair_keys = [list(key) for key in sorted(chosen)]
    manifest = {
        "schema_version": 1,
        "kind": "top10_holders_exact_batch",
        "source": {
            "release_id": release_id,
            "release_manifest_sha256": release_manifest_sha256,
            "current_pointer_sha256": digest(pointer_bytes),
            "authority_config_sha256": config_sha,
            "code_sha256": code_sha256(),
            "epoch": epoch,
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "attempts": 0,
            "selection": SELECTION,
            "eligible_pairs": len(eligible),
            "history_manifest_sha256": history_hashes,
        },
        "selected": {
            "pair_count": len(chosen),
            "pair_keys_sha256": digest(json_bytes(pair_keys)),
            "min_end_date": min(key[2] for key in chosen),
            "max_end_date": max(key[2] for key in chosen),
        },
        "api_counts": dict(
            sorted(Counter(row["job"]["api_name"] for row in records).items())
        ),
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "all_logical_keys_sha256": digest(json_bytes(logicals)),
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
    parser.add_argument("--epoch", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--release-manifest-sha256", required=True)
    parser.add_argument("--pair-count", type=int, default=MAX_PAIRS)
    parser.add_argument("--history-manifest", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.output,
        args.epoch,
        args.release_id,
        args.release_manifest_sha256,
        pair_count=args.pair_count,
        history_manifests=args.history_manifest,
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "pairs": result["selected"]["pair_count"],
                "api_counts": result["api_counts"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "all_logical_keys_sha256": result["all_logical_keys_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
