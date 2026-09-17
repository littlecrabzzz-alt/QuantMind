#!/usr/bin/env python3
"""Retire covered legacy requests that current Tushare contracts reject."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from contextlib import ExitStack
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_futures_extra_contracts import (  # noqa: E402
    FUT_INDEX_DAILY_DOCUMENTED_CODES,
)
from backend.shared.tushare_pipeline import Pipeline, contract_for, utc_now  # noqa: E402

FACTOR_APIS = ("idx_factor_pro", "fund_factor_pro", "cb_factor_pro")
FUTURES_API = "fut_index_daily"
SUPPORTED = (*FACTOR_APIS, FUTURES_API)
USABLE_REPLACEMENT_STATES = (
    "pending",
    "split_pending",
    "done",
    "empty",
    "quality",
    "permission_blocked",
)


def _encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _count(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _day(value):
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("Invalid retirement date")
    parsed = datetime.strptime(value, "%Y%m%d").date()
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("Non-canonical retirement date")
    return parsed


def _candidate(row, api):
    job = json.loads(row["job"])
    if job.get("api_name") != api:
        raise ValueError("Candidate API mismatch")
    params = job.get("params")
    if api in FACTOR_APIS:
        if not isinstance(params, dict) or set(params) != {"start_date", "end_date"}:
            return None
        start, end = _day(params["start_date"]), _day(params["end_date"])
        kind = "factor_range_without_selector"
    else:
        if not isinstance(params, dict) or set(params) != {"trade_date"}:
            return None
        start = end = _day(params["trade_date"])
        kind = "futures_day_without_code"
    if start > end:
        raise ValueError("Reversed retirement range")
    result = json.loads(row["result"]) if row["result"] else None
    if result is not None and (
        result.get("api_name") != api
        or result.get("status") != "api_error"
        or result.get("code") != 50101
    ):
        raise ValueError("Candidate has non-contract-blocking result")
    fields = job.get("fields")
    row_cap = job.get("row_cap")
    if not isinstance(fields, str) or not fields or not isinstance(row_cap, int):
        raise ValueError("Candidate has invalid request projection")
    return {
        "job_id": row["id"],
        "api": api,
        "epoch": row["epoch"],
        "start": start,
        "end": end,
        "fields": fields,
        "row_cap": row_cap,
        "kind": kind,
    }


def _candidates(db):
    candidates = []
    for api in SUPPORTED:
        group = contract_for(api).get("group", "rrg")
        rows = db.execute(
            "SELECT id,epoch,job,result FROM jobs INDEXED BY jobs_pending "
            "WHERE state='blocked' AND json_extract(job,'$.api_name')=? "
            "AND group_name=? ORDER BY rowid",
            (api, group),
        )
        for row in rows:
            candidate = _candidate(row, api)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _factor_replacements(db, epochs):
    replacements = {}
    placeholders = ",".join("?" for _ in USABLE_REPLACEMENT_STATES)
    for api in FACTOR_APIS:
        for epoch in epochs:
            rows = db.execute(
                "SELECT id,job,state FROM jobs INDEXED BY jobs_partition_lookup "
                "WHERE epoch=? AND json_extract(job,'$.api_name')=? "
                f"AND state IN ({placeholders}) ORDER BY rowid",
                (epoch, api, *USABLE_REPLACEMENT_STATES),
            )
            for row in rows:
                job = json.loads(row["job"])
                params = job.get("params")
                if not isinstance(params, dict) or set(params) != {"trade_date"}:
                    continue
                key = (
                    api,
                    _day(params["trade_date"]),
                    job.get("fields"),
                    job.get("row_cap"),
                )
                replacements.setdefault(key, row["id"])
    return replacements


def _merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return (
        tuple(start for start, _ in merged),
        tuple(end for _, end in merged),
    )


def _futures_replacements(db, epochs):
    documented = set(FUT_INDEX_DAILY_DOCUMENTED_CODES)
    by_key = {}
    job_ids = set()
    placeholders = ",".join("?" for _ in USABLE_REPLACEMENT_STATES)
    for epoch in epochs:
        rows = db.execute(
            "SELECT id,job,state FROM jobs INDEXED BY jobs_partition_lookup "
            "WHERE epoch=? AND json_extract(job,'$.api_name')=? "
            f"AND state IN ({placeholders}) ORDER BY rowid",
            (epoch, FUTURES_API, *USABLE_REPLACEMENT_STATES),
        )
        for row in rows:
            job = json.loads(row["job"])
            params = job.get("params")
            if not isinstance(params, dict) or set(params) != {
                "ts_code",
                "start_date",
                "end_date",
            }:
                continue
            code = params["ts_code"]
            if code not in documented:
                continue
            start, end = _day(params["start_date"]), _day(params["end_date"])
            if start > end:
                raise ValueError("Reversed futures replacement range")
            key = (code, job.get("fields"), job.get("row_cap"))
            by_key.setdefault(key, []).append((start, end))
            job_ids.add(row["id"])
    merged = {key: _merge_intervals(value) for key, value in by_key.items()}
    return merged, job_ids


def _covered(coverage, day):
    starts, ends = coverage
    offset = bisect_right(starts, day) - 1
    return offset >= 0 and ends[offset] >= day


def migrate(pipeline, *, apply=False):
    """Prove corrected queue coverage, then retire only exact rejected shapes."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    attempts_before = _count(db, "SELECT count(*) FROM attempts")
    results_before = _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
    try:
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-262144")
        db.execute("PRAGMA mmap_size=4294967296")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DROP TABLE IF EXISTS temp.invalid_request_candidates")
        db.execute(
            "CREATE TEMP TABLE invalid_request_candidates ("
            "job_id TEXT PRIMARY KEY,api TEXT NOT NULL,kind TEXT NOT NULL) WITHOUT ROWID"
        )
        candidates = _candidates(db)
        replacement_epochs = sorted(
            {"history", *(item["epoch"] for item in candidates)}
        )
        db.executemany(
            "INSERT INTO invalid_request_candidates VALUES(?,?,?)",
            [(item["job_id"], item["api"], item["kind"]) for item in candidates],
        )
        active_parent_children = _count(
            db,
            "SELECT count(DISTINCT candidate.job_id) "
            "FROM invalid_request_candidates AS candidate "
            "JOIN partition_children AS edge ON edge.child_id=candidate.job_id "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE parent.state='split_pending'",
        )
        if active_parent_children:
            raise ValueError("Invalid requests are shared by active split parents")

        factor_replacements = _factor_replacements(db, replacement_epochs)
        futures_replacements, futures_job_ids = _futures_replacements(
            db, replacement_epochs
        )
        missing = []
        required_factor_days = 0
        required_futures_pairs = 0
        used_factor_jobs = set()
        for item in candidates:
            if item["api"] in FACTOR_APIS:
                day = item["start"]
                while day <= item["end"]:
                    required_factor_days += 1
                    key = (item["api"], day, item["fields"], item["row_cap"])
                    replacement = factor_replacements.get(key)
                    if replacement is None:
                        missing.append(
                            (item["job_id"], item["api"], day.strftime("%Y%m%d"))
                        )
                    else:
                        used_factor_jobs.add(replacement)
                    day += timedelta(days=1)
            else:
                for code in FUT_INDEX_DAILY_DOCUMENTED_CODES:
                    required_futures_pairs += 1
                    key = (code, item["fields"], item["row_cap"])
                    coverage = futures_replacements.get(key, ((), ()))
                    if not _covered(coverage, item["start"]):
                        missing.append((item["job_id"], item["api"], code))
        if missing:
            sample = ", ".join("/".join(value) for value in missing[:3])
            raise ValueError(
                f"{len(missing)} invalid-request coverage units lack usable replacements: {sample}"
            )

        per_api = {
            api: sum(item["api"] == api for item in candidates) for api in SUPPORTED
        }
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM invalid_request_candidates)",
        )
        checked_at = utc_now()
        capability_rows = []
        for item in candidates:
            requirement = (
                (item["end"] - item["start"]).days + 1
                if item["api"] in FACTOR_APIS
                else len(FUT_INDEX_DAILY_DOCUMENTED_CODES)
            )
            capability_rows.append(
                (
                    "dispatch:" + item["job_id"],
                    "request_contract_superseded",
                    checked_at,
                    json.dumps(
                        {
                            "api_name": item["api"],
                            "reason": "legacy request shape rejected by current contract",
                            "invalid_shape": item["kind"],
                            "coverage_proven": True,
                            "coverage_units": requirement,
                            "coverage_basis": "all_market_calendar_days"
                            if item["api"] in FACTOR_APIS
                            else "documented_futures_index_codes",
                            "source_attempts_preserved": True,
                            "upstream_calls": 0,
                        },
                        sort_keys=True,
                    ),
                )
            )
        db.executemany(
            "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
            "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,"
            "checked_at=excluded.checked_at,reason=excluded.reason",
            capability_rows,
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM invalid_request_candidates) AND state='blocked'"
        ).rowcount
        if superseded != len(candidates):
            raise ValueError(
                "Not every covered invalid request was retired exactly once"
            )
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during invalid-request retirement")
        if (
            _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
            != results_before
        ):
            raise ValueError("Result-bearing job count changed during retirement")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "candidate_jobs": len(candidates),
            "candidate_jobs_by_api": per_api,
            "candidate_epochs": sorted({item["epoch"] for item in candidates}),
            "replacement_epochs": replacement_epochs,
            "superseded_jobs": superseded,
            "required_factor_day_coverage": required_factor_days,
            "required_futures_code_day_coverage": required_futures_pairs,
            "documented_futures_codes": len(FUT_INDEX_DAILY_DOCUMENTED_CODES),
            "factor_replacement_jobs_used": len(used_factor_jobs),
            "futures_replacement_jobs_available": len(futures_job_ids),
            "missing_coverage_units": len(missing),
            "active_parent_children": active_parent_children,
            "capability_evidence_rows": len(capability_rows),
            "candidate_attempts_preserved": candidate_attempts,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "replacement_jobs_action": "unchanged",
            "source_results_action": "unchanged",
            "database_quick_check": "required_on_post_commit_consistent_copy",
            "upstream_calls": 0,
        }
        if apply:
            db.commit()
        else:
            db.rollback()
        return report
    except BaseException:
        db.rollback()
        raise


def _write_receipt(root, report):
    body = _encoded(report) + b"\n"
    path = Path(root) / ("invalid-request-retirement-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".invalid-request-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = json.loads(_regular(args.catalog, "Catalog").read_bytes())
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    with ExitStack() as stack:
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pipeline = Pipeline(root, catalog)
        stack.callback(pipeline.close)
        report = migrate(pipeline, apply=args.apply)
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
