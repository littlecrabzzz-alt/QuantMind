#!/usr/bin/env python3
"""Freeze 60 common open-day tasks for six core A-share market APIs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402


ALLOWED_APIS = (
    "daily",
    "adj_factor",
    "daily_basic",
    "stk_limit",
    "suspend_d",
    "moneyflow",
)
GROUP = "structured"
EXCHANGE = "SSE"
DAYS_PER_API = 60
MAX_BATCH_JOBS = len(ALLOWED_APIS) * DAYS_PER_API
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
PARQUET_RE = re.compile(r"parquet/([a-f0-9]{64})\.parquet")


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


def _current_release(root, release_id, manifest_sha256):
    pointer = json.loads(
        _regular(root / "CURRENT.json", "Current pointer").read_bytes()
    )
    if pointer != {
        "manifest_sha256": manifest_sha256,
        "release_id": release_id,
    }:
        raise ValueError("Explicit release is not the current fixed release")


def calendar_evidence(root, release_id, manifest_sha256):
    """Verify the fixed manifest and every published trade_cal Parquet file."""
    root = Path(root).resolve()
    match = RELEASE_RE.fullmatch(release_id)
    _hash(manifest_sha256, "release manifest")
    if not match or match.group(1) != manifest_sha256:
        raise ValueError("Release ID must be derived from its manifest SHA-256")
    release_manifest = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(release_manifest) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    manifest = json.loads(release_manifest.read_bytes())
    files = manifest.get("files")
    datasets = manifest.get("datasets")
    if not isinstance(files, dict) or not isinstance(datasets, list):
        raise ValueError("Invalid fixed release manifest")

    refs = {}
    for dataset in datasets:
        if not isinstance(dataset, dict) or dataset.get("api_name") != "trade_cal":
            continue
        path = dataset.get("path")
        path_match = PARQUET_RE.fullmatch(str(path))
        metadata = files.get(path)
        if (
            not path_match
            or not isinstance(metadata, dict)
            or dataset.get("sha256") != path_match.group(1)
            or metadata.get("sha256") != path_match.group(1)
            or dataset.get("bytes") != metadata.get("bytes")
            or type(metadata.get("bytes")) is not int
            or metadata["bytes"] <= 0
        ):
            raise ValueError("Invalid fixed trade_cal file reference")
        refs[path] = {
            "path": path,
            "sha256": path_match.group(1),
            "bytes": metadata["bytes"],
        }
    if not refs:
        raise ValueError("Fixed release has no trade_cal dataset")

    states = defaultdict(set)
    for ref in sorted(refs.values(), key=lambda item: item["path"]):
        path = _regular(root / ref["path"], "Fixed trade_cal Parquet")
        if path.stat().st_size != ref["bytes"] or sha(path) != ref["sha256"]:
            raise ValueError("Fixed trade_cal Parquet hash mismatch")
        table = pq.read_table(path, columns=["cal_date", "exchange", "is_open"])
        for row in table.to_pylist():
            if row.get("exchange") != EXCHANGE:
                continue
            cal_date = str(row.get("cal_date", ""))
            if not re.fullmatch(r"[0-9]{8}", cal_date):
                raise ValueError("Invalid fixed trade_cal date")
            is_open = row.get("is_open")
            if is_open not in (0, 1, False, True):
                raise ValueError("Invalid fixed trade_cal open flag")
            states[cal_date].add(bool(is_open))
    if any(len(values) != 1 for values in states.values()):
        raise ValueError("Fixed trade_cal files disagree")
    open_dates = sorted(day for day, values in states.items() if True in values)
    if not open_dates:
        raise ValueError("Fixed release has no open SSE dates")
    return {
        "api_name": "trade_cal",
        "exchange": EXCHANGE,
        "files": sorted(refs.values(), key=lambda item: item["path"]),
        "open_dates": open_dates,
        "open_dates_sha256": digest(json_bytes(open_dates)),
    }


def _job_api_day(record):
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
    if (
        not isinstance(job, dict)
        or job.get("api_name") not in ALLOWED_APIS
        or not isinstance(params, dict)
        or set(params) != {"trade_date"}
        or not re.fullmatch(r"[0-9]{8}", str(params.get("trade_date", "")))
        or record["group_name"] != GROUP
        or type(record["priority"]) is not int
        or not isinstance(record["epoch"], str)
    ):
        raise ValueError("Batch contains a non-core or non-pristine task")
    return job["api_name"], params["trade_date"]


def _validate_record(record):
    api, day = _job_api_day(record)
    if record["state"] != "pending" or record["tries"] != 0:
        raise ValueError("Batch contains a non-pristine task")
    logical_key = digest(json_bytes(record["job"]))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    return api, day


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "kind",
        "source",
        "calendar",
        "selected",
        "api_counts",
        "all_task_ids_sha256",
        "records",
    }:
        raise ValueError("Invalid batch manifest")
    source = manifest["source"]
    calendar = manifest["calendar"]
    selected = manifest["selected"]
    records = manifest["records"]
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "core_market_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "authority_config_sha256",
            "preparation_sha256",
            "group_name",
            "state",
            "tries",
            "selection",
            "eligible_open_dates",
        }
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or source.get("tries") != 0
        or source.get("selection")
        != "latest_common_pristine_tasks_on_fixed_sse_open_dates"
        or type(source.get("eligible_open_dates")) is not int
        or source["eligible_open_dates"] < DAYS_PER_API
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or RELEASE_RE.fullmatch(source["release_id"]).group(1)
        != source.get("release_manifest_sha256")
    ):
        raise ValueError("Invalid batch source")
    for key in (
        "release_manifest_sha256",
        "authority_config_sha256",
        "preparation_sha256",
    ):
        _hash(source.get(key), key)
    if (
        not isinstance(calendar, dict)
        or set(calendar)
        != {"api_name", "exchange", "files", "open_dates", "open_dates_sha256"}
        or calendar.get("api_name") != "trade_cal"
        or calendar.get("exchange") != EXCHANGE
        or not isinstance(calendar.get("files"), list)
        or not calendar["files"]
        or not isinstance(calendar.get("open_dates"), list)
        or any(not isinstance(day, str) for day in calendar["open_dates"])
        or calendar["open_dates"] != sorted(set(calendar["open_dates"]))
        or any(
            not re.fullmatch(r"[0-9]{8}", str(day)) for day in calendar["open_dates"]
        )
        or calendar.get("open_dates_sha256")
        != digest(json_bytes(calendar["open_dates"]))
    ):
        raise ValueError("Invalid fixed calendar evidence")
    seen_paths = set()
    for ref in calendar["files"]:
        match = (
            PARQUET_RE.fullmatch(str(ref.get("path", "")))
            if isinstance(ref, dict)
            else None
        )
        if (
            not isinstance(ref, dict)
            or set(ref) != {"path", "sha256", "bytes"}
            or not match
            or ref["sha256"] != match.group(1)
            or type(ref["bytes"]) is not int
            or ref["bytes"] <= 0
            or ref["path"] in seen_paths
        ):
            raise ValueError("Invalid calendar file inventory")
        seen_paths.add(ref["path"])
    trade_dates = selected.get("trade_dates") if isinstance(selected, dict) else None
    if (
        set(selected or {})
        != {"trade_dates", "trade_dates_sha256", "min_trade_date", "max_trade_date"}
        or not isinstance(trade_dates, list)
        or len(trade_dates) != DAYS_PER_API
        or any(not isinstance(day, str) for day in trade_dates)
        or trade_dates != sorted(set(trade_dates), reverse=True)
        or any(day not in calendar["open_dates"] for day in trade_dates)
        or selected.get("trade_dates_sha256") != digest(json_bytes(trade_dates))
        or selected.get("min_trade_date") != min(trade_dates)
        or selected.get("max_trade_date") != max(trade_dates)
        or not isinstance(records, list)
        or len(records) != MAX_BATCH_JOBS
    ):
        raise ValueError("Invalid selected trade dates")
    pairs = [_validate_record(record) for record in records]
    counts = Counter(api for api, _day in pairs)
    dates_by_api = defaultdict(set)
    for api, day in pairs:
        dates_by_api[api].add(day)
    expected_counts = dict(sorted((api, DAYS_PER_API) for api in ALLOWED_APIS))
    if (
        manifest.get("api_counts") != expected_counts
        or dict(sorted(counts.items())) != expected_counts
        or any(dates_by_api[api] != set(trade_dates) for api in ALLOWED_APIS)
    ):
        raise ValueError("Batch is not balanced across the six APIs")
    task_ids = sorted(record["task_id"] for record in records)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Duplicate task identity")
    if manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids)):
        raise ValueError("Task inventory hash mismatch")
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


def prepare(root, output, release_id, release_manifest_sha256):
    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output.is_symlink()
        or output == root
        or root in output.parents
    ):
        raise ValueError("Output must not exist or be inside authority")
    _current_release(root, release_id, release_manifest_sha256)
    calendar = calendar_evidence(root, release_id, release_manifest_sha256)
    config_sha256 = sha(_regular(root / "pipeline-config.json", "Pipeline config"))
    database = _regular(root / "pipeline.sqlite", "Pipeline database")

    rows = []
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
                "FROM jobs WHERE group_name=? AND json_extract(job,'$.api_name') "
                f"IN ({placeholders}) ORDER BY json_extract(job,'$.params.trade_date') "
                "DESC,json_extract(job,'$.api_name'),epoch,id",
                (GROUP, *ALLOWED_APIS),
            ).fetchall()
        finally:
            db.close()

    inventory = defaultdict(lambda: defaultdict(list))
    tainted = set()
    for row in rows:
        record = _record(row)
        try:
            api, day = _job_api_day(record)
        except ValueError:
            job = record.get("job")
            if isinstance(job, dict) and job.get("api_name") in ALLOWED_APIS:
                raise
            continue
        key = (api, day)
        if record["state"] == "pending" and record["tries"] == 0:
            inventory[api][day].append(record)
        else:
            tainted.add(key)

    def chosen(api, day):
        if (api, day) in tainted or not inventory[api][day]:
            return None
        return min(
            inventory[api][day],
            key=lambda item: (
                item["epoch"] != "history",
                item["epoch"],
                item["task_id"],
            ),
        )

    open_dates = set(calendar["open_dates"])
    eligible = [
        day
        for day in open_dates
        if all(chosen(api, day) is not None for api in ALLOWED_APIS)
    ]
    selected_dates = sorted(eligible, reverse=True)[:DAYS_PER_API]
    if len(selected_dates) != DAYS_PER_API:
        raise ValueError("Insufficient common pristine tasks on fixed open dates")
    records = [chosen(api, day) for day in selected_dates for api in ALLOWED_APIS]
    task_ids = sorted(record["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "core_market_exact_batch",
        "source": {
            "release_id": release_id,
            "release_manifest_sha256": release_manifest_sha256,
            "authority_config_sha256": config_sha256,
            "preparation_sha256": preparation_sha256(),
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "selection": "latest_common_pristine_tasks_on_fixed_sse_open_dates",
            "eligible_open_dates": len(eligible),
        },
        "calendar": calendar,
        "selected": {
            "trade_dates": selected_dates,
            "trade_dates_sha256": digest(json_bytes(selected_dates)),
            "min_trade_date": min(selected_dates),
            "max_trade_date": max(selected_dates),
        },
        "api_counts": dict(sorted((api, DAYS_PER_API) for api in ALLOWED_APIS)),
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
    args = parser.parse_args()
    result = prepare(
        args.root, args.output, args.release_id, args.release_manifest_sha256
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "selected": result["selected"],
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
