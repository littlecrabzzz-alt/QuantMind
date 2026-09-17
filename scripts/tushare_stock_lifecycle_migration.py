#!/usr/bin/env python3
"""Retire pending pre-listing stock jobs and clip crossing ranges; no source calls."""

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

from backend.shared.tushare_pipeline import (  # noqa: E402
    Pipeline,
    STOCK_IDENTIFIER_SOURCE_APIS,
    contract_for,
)
from backend.shared.tushare_stock_lifecycle import stock_list_dates  # noqa: E402

SUPPORTED = ("factor_value", "cyq_perf", "cyq_chips")
USABLE_REPLACEMENT_STATES = {
    "pending",
    "split_pending",
    "done",
    "empty",
    "quality",
    "permission_blocked",
}


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


def _candidate_sql(state):
    index = (
        "jobs_ready_api_history" if state == "pending" else "jobs_group_pending"
    )
    return (
        "SELECT job.id,json_extract(job.job,'$.api_name'),"
        "CASE WHEN json_type(job.job,'$.params.trade_date')='text' THEN 'prelist_day' "
        "WHEN json_extract(job.job,'$.params.end_date')<life.list_date "
        "THEN 'prelist_range' ELSE 'crossing_range' END "
        f"FROM jobs AS job INDEXED BY {index} "
        "JOIN stock_lifecycle_bounds AS life "
        "ON life.ts_code=json_extract(job.job,'$.params.ts_code') "
        f"WHERE job.state='{state}' AND job.group_name=? "
        "AND json_extract(job.job,'$.api_name')=? AND ("
        "(json_type(job.job,'$.params.trade_date')='text' "
        "AND length(json_extract(job.job,'$.params.trade_date'))=8 "
        "AND json_extract(job.job,'$.params.trade_date') NOT GLOB '*[^0-9]*' "
        "AND json_extract(job.job,'$.params.trade_date')<life.list_date) OR "
        "(json_type(job.job,'$.params.start_date')='text' "
        "AND json_type(job.job,'$.params.end_date')='text' "
        "AND length(json_extract(job.job,'$.params.start_date'))=8 "
        "AND length(json_extract(job.job,'$.params.end_date'))=8 "
        "AND json_extract(job.job,'$.params.start_date') NOT GLOB '*[^0-9]*' "
        "AND json_extract(job.job,'$.params.end_date') NOT GLOB '*[^0-9]*' "
        "AND json_extract(job.job,'$.params.start_date')<life.list_date))"
    )


def migrate(pipeline, lifecycles=None, *, apply=False):
    """Apply one atomic listing-bound migration while preserving evidence."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    if lifecycles is None:
        lifecycles = pipeline.identifiers(
            _source_apis=STOCK_IDENTIFIER_SOURCE_APIS, _use_cache=False
        ).get("stock_lifecycles", [])
    list_dates = stock_list_dates({"stock_lifecycles": lifecycles})
    attempts_before = _count(db, "SELECT count(*) FROM attempts")
    results_before = _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
    try:
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-262144")
        db.execute("PRAGMA mmap_size=4294967296")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        for table in ("stock_lifecycle_bounds", "stock_lifecycle_candidates"):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        db.execute(
            "CREATE TEMP TABLE stock_lifecycle_bounds ("
            "ts_code TEXT PRIMARY KEY,list_date TEXT NOT NULL) WITHOUT ROWID"
        )
        db.executemany(
            "INSERT INTO stock_lifecycle_bounds VALUES(?,?)",
            sorted(list_dates.items()),
        )
        db.execute(
            "CREATE TEMP TABLE stock_lifecycle_candidates ("
            "job_id TEXT PRIMARY KEY,api TEXT NOT NULL,kind TEXT NOT NULL) WITHOUT ROWID"
        )
        per_api = {}
        for api in SUPPORTED:
            group = contract_for(api).get("group", "rrg")
            db.execute(
                "INSERT INTO stock_lifecycle_candidates "
                + _candidate_sql("pending"),
                (group, api),
            )
            split_candidates = _count(
                db,
                "SELECT count(*) FROM (" + _candidate_sql("split_pending") + ")",
                (group, api),
            )
            if split_candidates:
                raise ValueError(
                    f"{api} has split_pending jobs that require listing-date clipping"
                )
            counts = {
                row["kind"]: row["count"]
                for row in db.execute(
                    "SELECT kind,count(*) AS count FROM stock_lifecycle_candidates "
                    "WHERE api=? GROUP BY kind",
                    (api,),
                )
            }
            unknown = _count(
                db,
                "SELECT count(*) FROM jobs AS job INDEXED BY jobs_ready_api_history "
                "LEFT JOIN stock_lifecycle_bounds AS life "
                "ON life.ts_code=json_extract(job.job,'$.params.ts_code') "
                "WHERE job.state='pending' AND job.group_name=? "
                "AND json_extract(job.job,'$.api_name')=? AND life.ts_code IS NULL",
                (group, api),
            )
            per_api[api] = {
                "prelist_days": counts.get("prelist_day", 0),
                "prelist_ranges": counts.get("prelist_range", 0),
                "crossing_ranges": counts.get("crossing_range", 0),
                "unknown_lifecycle_pending_preserved": unknown,
            }
        external = _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id IN "
            "(SELECT job_id FROM stock_lifecycle_candidates) "
            "AND parent.state='split_pending'",
        )
        if external:
            raise ValueError("Listing-date candidates are shared by active split parents")
        replacements = set()
        inserted = 0
        reused = 0
        crossing = db.execute(
            "SELECT job.id,job.job,job.priority,job.epoch,life.list_date "
            "FROM stock_lifecycle_candidates AS candidate "
            "JOIN jobs AS job ON job.id=candidate.job_id "
            "JOIN stock_lifecycle_bounds AS life "
            "ON life.ts_code=json_extract(job.job,'$.params.ts_code') "
            "WHERE candidate.kind='crossing_range' ORDER BY job.rowid"
        ).fetchall()
        for row in crossing:
            original = json.loads(row["job"])
            params = {**original["params"], "start_date": row["list_date"]}
            before = db.total_changes
            replacement = pipeline.enqueue(
                original["api_name"], params, row["priority"], row["epoch"]
            )
            changed = db.total_changes - before
            inserted += int(bool(changed))
            reused += int(not changed)
            state = db.execute(
                "SELECT state FROM jobs WHERE id=?", (replacement,)
            ).fetchone()
            if state is None or state["state"] not in USABLE_REPLACEMENT_STATES:
                raise ValueError("Crossing range replacement is missing or retired")
            replacements.add(replacement)
        candidate_count = _count(
            db, "SELECT count(*) FROM stock_lifecycle_candidates"
        )
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM stock_lifecycle_candidates)",
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM stock_lifecycle_candidates) AND state='pending'"
        ).rowcount
        if superseded != candidate_count:
            raise ValueError("Not every listing-date candidate was retired exactly once")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during queue-only migration")
        if _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL") != results_before:
            raise ValueError("Result-bearing job count changed during migration")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "known_stock_list_dates": len(list_dates),
            "per_api": per_api,
            "candidate_jobs": candidate_count,
            "superseded_jobs": superseded,
            "crossing_replacement_jobs": len(replacements),
            "inserted_replacement_jobs": inserted,
            "reused_replacement_jobs": reused,
            "candidate_attempts_preserved": candidate_attempts,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "completed_jobs_action": "unchanged",
            "unknown_lifecycle_action": "preserved_unbounded",
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
    path = Path(root) / ("stock-lifecycle-migration-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".stock-lifecycle-", dir=root)
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
