#!/usr/bin/env python3
"""Retire covered legacy factor_value history days; never call the supplier."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

API = "factor_value"
GROUP = "factor_library"
RANGE_STATES = ("pending", "split_pending", "done")


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


def migrate(pipeline, *, apply=False):
    """Atomically supersede only history days covered by a usable range job."""
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
        for table in ("factor_month_coverage", "factor_daily_candidates"):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        db.execute(
            "CREATE TEMP TABLE factor_month_coverage ("
            "job_id TEXT PRIMARY KEY,ts_code TEXT NOT NULL,start_date TEXT NOT NULL,"
            "end_date TEXT NOT NULL,state TEXT NOT NULL) WITHOUT ROWID"
        )
        placeholders = ",".join("?" for _ in RANGE_STATES)
        db.execute(
            "INSERT INTO factor_month_coverage "
            "SELECT id,json_extract(job,'$.params.ts_code'),"
            "json_extract(job,'$.params.start_date'),"
            "json_extract(job,'$.params.end_date'),state "
            "FROM jobs INDEXED BY jobs_partition_lookup "
            "WHERE epoch='history' AND json_extract(job,'$.api_name')=? "
            f"AND state IN ({placeholders}) "
            "AND json_type(job,'$.params.ts_code')='text' "
            "AND json_type(job,'$.params.start_date')='text' "
            "AND json_type(job,'$.params.end_date')='text' "
            "AND json_type(job,'$.params.trade_date') IS NULL "
            "AND length(json_extract(job,'$.params.start_date'))=8 "
            "AND length(json_extract(job,'$.params.end_date'))=8 "
            "AND json_extract(job,'$.params.start_date') "
            "NOT GLOB '*[^0-9]*' "
            "AND json_extract(job,'$.params.end_date') "
            "NOT GLOB '*[^0-9]*' "
            "AND json_extract(job,'$.params.start_date') "
            "<= json_extract(job,'$.params.end_date')",
            (API, *RANGE_STATES),
        )
        db.execute(
            "CREATE INDEX factor_month_coverage_lookup "
            "ON factor_month_coverage(ts_code,start_date,end_date)"
        )
        range_jobs = _count(db, "SELECT count(*) FROM factor_month_coverage")
        split_daily = _count(
            db,
            "SELECT count(*) FROM jobs INDEXED BY jobs_group_pending "
            "WHERE state='split_pending' AND group_name=? AND epoch='history' "
            "AND json_extract(job,'$.api_name')=? "
            "AND json_type(job,'$.params.trade_date')='text'",
            (GROUP, API),
        )
        if split_daily:
            raise ValueError("Legacy split_pending factor days require separate review")
        old_open = _count(
            db,
            "SELECT count(*) FROM jobs INDEXED BY jobs_ready_api_history "
            "WHERE state='pending' AND group_name=? "
            "AND json_extract(job,'$.api_name')=? AND epoch='history' "
            "AND json_type(job,'$.params.trade_date')='text'",
            (GROUP, API),
        )
        db.execute(
            "CREATE TEMP TABLE factor_daily_candidates ("
            "job_id TEXT PRIMARY KEY,range_id TEXT NOT NULL) WITHOUT ROWID"
        )
        db.execute(
            "INSERT OR IGNORE INTO factor_daily_candidates "
            "SELECT day.id,month.job_id FROM jobs AS day "
            "INDEXED BY jobs_ready_api_history "
            "JOIN factor_month_coverage AS month "
            "ON month.ts_code=json_extract(day.job,'$.params.ts_code') "
            "AND month.start_date<=json_extract(day.job,'$.params.trade_date') "
            "AND month.end_date>=json_extract(day.job,'$.params.trade_date') "
            "JOIN jobs AS range_job ON range_job.id=month.job_id "
            "WHERE day.state='pending' AND day.group_name=? "
            "AND json_extract(day.job,'$.api_name')=? AND day.epoch='history' "
            "AND json_type(day.job,'$.params.trade_date')='text' "
            "AND length(json_extract(day.job,'$.params.trade_date'))=8 "
            "AND json_extract(day.job,'$.params.trade_date') "
            "NOT GLOB '*[^0-9]*' "
            "AND json_extract(day.job,'$.fields')="
            "json_extract(range_job.job,'$.fields') "
            "AND json_extract(day.job,'$.row_cap')="
            "json_extract(range_job.job,'$.row_cap')",
            (GROUP, API),
        )
        covered = _count(db, "SELECT count(*) FROM factor_daily_candidates")
        uncovered = old_open - covered
        if uncovered:
            raise ValueError(
                f"{uncovered} legacy factor days lack matching usable range coverage"
            )
        external = _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id IN (SELECT job_id FROM factor_daily_candidates) "
            "AND parent.state='split_pending'",
        )
        if external:
            raise ValueError("Covered factor days are shared by active split parents")
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM factor_daily_candidates)",
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM factor_daily_candidates) AND state='pending'"
        ).rowcount
        if superseded != old_open:
            raise ValueError("Not every covered legacy factor day was retired exactly once")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during queue-only retirement")
        if _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL") != results_before:
            raise ValueError("Result-bearing job count changed during queue-only retirement")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "api": API,
            "eligible_range_jobs": range_jobs,
            "old_open_history_days": old_open,
            "covered_history_days": covered,
            "uncovered_history_days": uncovered,
            "superseded_history_days": superseded,
            "candidate_attempts_preserved": candidate_attempts,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "recent_daily_jobs_action": "unchanged",
            "completed_daily_jobs_action": "unchanged",
            "range_jobs_action": "unchanged",
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
    path = Path(root) / ("factor-daily-retirement-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".factor-daily-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
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
