#!/usr/bin/env python3
"""Replace open daily_info/dc_daily history days with complete month ranges."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_dc_extra_contracts import (  # noqa: E402
    DAILY_VARIANTS,
    iter_dc_extra_jobs,
)
from backend.shared.tushare_listing_extra_contracts import (  # noqa: E402
    iter_listing_extra_jobs,
)
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

APIS = ("daily_info", "dc_daily")
GROUPS = {"daily_info": "listing_extra", "dc_daily": "dc_extra"}
PLANNING_STATES = ("history:listing_extra", "history:dc_extra")
USABLE_RANGE_STATES = ("pending", "split_pending", "done", "empty")
DC_VARIANTS = {item["idx_type"] for item in DAILY_VARIANTS}


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


def _planned_ranges(config, today, api):
    selected = {**config, "planning_epoch": today.strftime("%Y%m%d")}
    if api == "daily_info":
        selected["listing_extra_apis"] = [api]
        jobs = iter_listing_extra_jobs(selected, today, {})
    elif api == "dc_daily":
        selected["dc_extra_apis"] = [api]
        jobs = iter_dc_extra_jobs(selected, today, {})
    else:
        raise ValueError("Unsupported low-volume range API")
    for job in jobs:
        if job["epoch"] == "history":
            yield job


def _validate_date(value, label):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]{8}", value)
        or datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") != value
    ):
        raise ValueError(f"Invalid {label}")


def migrate(pipeline, config, today, *, apply=False):
    """Atomically retire only pending exact days covered by one usable range."""
    if not isinstance(today, date):
        raise ValueError("today must be a date")
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
        for table in ("low_volume_daily_open", "low_volume_ranges"):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        db.execute(
            "CREATE TEMP TABLE low_volume_daily_open ("
            "job_id TEXT PRIMARY KEY,api TEXT NOT NULL,trade_date TEXT NOT NULL,"
            "variant TEXT NOT NULL) WITHOUT ROWID"
        )
        daily = []
        by_api = {}
        for api in APIS:
            rows = db.execute(
                "SELECT id,job FROM jobs INDEXED BY jobs_ready_api_history "
                "WHERE state='pending' AND group_name=? AND epoch='history' "
                "AND json_extract(job,'$.api_name')=? "
                "AND json_type(job,'$.params.trade_date')='text'",
                (GROUPS[api], api),
            ).fetchall()
            by_api[api] = len(rows)
            for row in rows:
                params = json.loads(row["job"])["params"]
                expected = {"trade_date"} if api == "daily_info" else {
                    "trade_date",
                    "idx_type",
                }
                if set(params) != expected:
                    raise ValueError(f"Unexpected {api} history-day request shape")
                trade_date = params["trade_date"]
                _validate_date(trade_date, f"{api} trade_date")
                variant = params.get("idx_type", "")
                if api == "dc_daily" and variant not in DC_VARIANTS:
                    raise ValueError("Invalid dc_daily idx_type")
                daily.append((row["id"], api, trade_date, variant))
            split_daily = _count(
                db,
                "SELECT count(*) FROM jobs INDEXED BY jobs_group_pending "
                "WHERE state='split_pending' AND group_name=? AND epoch='history' "
                "AND json_extract(job,'$.api_name')=? "
                "AND json_type(job,'$.params.trade_date')='text'",
                (GROUPS[api], api),
            )
            if split_daily:
                raise ValueError(f"Split {api} history days require separate review")
        db.executemany("INSERT INTO low_volume_daily_open VALUES(?,?,?,?)", daily)

        db.execute(
            "CREATE TEMP TABLE low_volume_ranges ("
            "job_id TEXT PRIMARY KEY,api TEXT NOT NULL,start_date TEXT NOT NULL,"
            "end_date TEXT NOT NULL,variant TEXT NOT NULL) WITHOUT ROWID"
        )
        inserted = 0
        planned_by_api = {}
        for api in APIS:
            planned_by_api[api] = 0
            seen = set()
            for job in _planned_ranges(config, today, api):
                before = db.total_changes
                job_id = pipeline.enqueue(
                    api, job["params"], job["priority"], job["epoch"]
                )
                inserted += db.total_changes - before
                if job_id in seen:
                    raise ValueError(f"{api} range planner produced duplicate requests")
                seen.add(job_id)
                row = db.execute(
                    "SELECT state,job FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row is None or row["state"] not in USABLE_RANGE_STATES:
                    raise ValueError(f"Planned {api} range is missing or unusable")
                params = json.loads(row["job"])["params"]
                expected = {"start_date", "end_date"} if api == "daily_info" else {
                    "start_date",
                    "end_date",
                    "idx_type",
                }
                if set(params) != expected:
                    raise ValueError(f"Unexpected {api} range request shape")
                _validate_date(params["start_date"], f"{api} start_date")
                _validate_date(params["end_date"], f"{api} end_date")
                if params["start_date"] > params["end_date"]:
                    raise ValueError(f"Invalid {api} range order")
                variant = params.get("idx_type", "")
                if api == "dc_daily" and variant not in DC_VARIANTS:
                    raise ValueError("Invalid dc_daily range idx_type")
                db.execute(
                    "INSERT INTO low_volume_ranges VALUES(?,?,?,?,?)",
                    (
                        job_id,
                        api,
                        params["start_date"],
                        params["end_date"],
                        variant,
                    ),
                )
                planned_by_api[api] += 1

        ambiguous = _count(
            db,
            "SELECT count(*) FROM ("
            "SELECT day.job_id,count(range_job.id) AS matches "
            "FROM low_volume_daily_open AS day "
            "LEFT JOIN low_volume_ranges AS span "
            "ON span.api=day.api AND span.variant=day.variant "
            "AND span.start_date<=day.trade_date AND span.end_date>=day.trade_date "
            "LEFT JOIN jobs AS day_job ON day_job.id=day.job_id "
            "LEFT JOIN jobs AS range_job ON range_job.id=span.job_id "
            "AND json_extract(day_job.job,'$.fields')="
            "json_extract(range_job.job,'$.fields') "
            "AND json_extract(day_job.job,'$.row_cap')="
            "json_extract(range_job.job,'$.row_cap') "
            "GROUP BY day.job_id HAVING matches<>1)"
        )
        if ambiguous:
            raise ValueError(
                f"{ambiguous} history days lack one matching range coverage"
            )
        external = _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id IN (SELECT job_id FROM low_volume_daily_open) "
            "AND parent.state='split_pending'",
        )
        if external:
            raise ValueError("Covered history days are shared by active split parents")
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM low_volume_daily_open)",
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM low_volume_daily_open) AND state='pending'"
        ).rowcount
        if superseded != len(daily):
            raise ValueError("Not every covered history day was retired")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during queue migration")
        if (
            _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
            != results_before
        ):
            raise ValueError("Result-bearing jobs changed during queue migration")
        placeholders = ",".join("?" for _ in PLANNING_STATES)
        planning_states_reset = db.execute(
            f"DELETE FROM planning_state WHERE name IN ({placeholders})",
            PLANNING_STATES,
        ).rowcount
        report = {
            "status": "applied" if apply else "snapshot_validation_rollback",
            "schema_version": 1,
            "apis": list(APIS),
            "today": today.strftime("%Y%m%d"),
            "planned_range_jobs": sum(planned_by_api.values()),
            "planned_range_jobs_by_api": planned_by_api,
            "inserted_range_jobs": inserted,
            "old_open_history_daily_jobs": len(daily),
            "old_open_history_daily_jobs_by_api": by_api,
            "covered_history_daily_jobs": len(daily),
            "superseded_history_daily_jobs": superseded,
            "candidate_attempts_preserved": candidate_attempts,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "history_planning_states_reset": planning_states_reset,
            "recent_daily_jobs_action": "unchanged",
            "completed_daily_jobs_action": "unchanged",
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
    path = Path(root) / ("low-volume-daily-retirement-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".low-volume-daily-", dir=root)
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
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = json.loads(_regular(args.catalog, "Catalog").read_bytes())
    config = json.loads(_regular(args.config, "Config").read_bytes())
    today = datetime.strptime(args.today, "%Y%m%d").date()
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    with ExitStack() as stack:
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pipeline = Pipeline(root, catalog)
        stack.callback(pipeline.close)
        report = migrate(pipeline, config, today, apply=args.apply)
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
