#!/usr/bin/env python3
"""Replace open TDX member history days with reviewed month ranges; no source calls."""

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

from backend.shared.tushare_registry import iter_market_member_jobs  # noqa: E402
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402

API = "tdx_member"
GROUP = "market_sentiment"
RANGE_STATES = ("pending", "split_pending", "done", "empty")


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


def _planned_ranges(config, today):
    selected = {
        **config,
        "market_members_apis": [API],
        "planning_epoch": today.strftime("%Y%m%d"),
    }
    for job in iter_market_member_jobs(
        selected,
        today,
        {"tdx_indices": [], "kpl_concepts": []},
    ):
        if job["epoch"] == "history":
            yield job


def migrate(pipeline, config, today, *, apply=False):
    """Atomically retire only exact history days covered by usable ranges."""
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
        for table in (
            "tdx_member_daily_open",
            "tdx_member_range_coverage",
            "tdx_member_daily_covered",
        ):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        db.execute(
            "CREATE TEMP TABLE tdx_member_daily_open ("
            "job_id TEXT PRIMARY KEY,trade_date TEXT NOT NULL,ts_code TEXT) "
            "WITHOUT ROWID"
        )
        rows = db.execute(
            "SELECT id,job FROM jobs INDEXED BY jobs_ready_api_history "
            "WHERE state='pending' AND group_name=? "
            "AND json_extract(job,'$.api_name')=? AND epoch='history' "
            "AND json_type(job,'$.params.trade_date')='text' "
            "AND json_type(job,'$.params.con_code') IS NULL",
            (GROUP, API),
        ).fetchall()
        daily = []
        for row in rows:
            params = json.loads(row["job"])["params"]
            if set(params) not in ({"trade_date"}, {"trade_date", "ts_code"}):
                raise ValueError("Unexpected TDX member history-day request shape")
            trade_date, ts_code = params["trade_date"], params.get("ts_code")
            if (
                not isinstance(trade_date, str)
                or not re.fullmatch(r"[0-9]{8}", trade_date)
                or datetime.strptime(trade_date, "%Y%m%d").strftime("%Y%m%d")
                != trade_date
                or (
                    ts_code is not None
                    and (
                        not isinstance(ts_code, str)
                        or not re.fullmatch(r"[0-9]{6}\.TDX", ts_code)
                    )
                )
            ):
                raise ValueError("Invalid TDX member history-day request")
            daily.append((row["id"], trade_date, ts_code))
        db.executemany("INSERT INTO tdx_member_daily_open VALUES(?,?,?)", daily)
        split_daily = _count(
            db,
            "SELECT count(*) FROM jobs INDEXED BY jobs_group_pending "
            "WHERE state='split_pending' AND group_name=? AND epoch='history' "
            "AND json_extract(job,'$.api_name')=? "
            "AND json_type(job,'$.params.trade_date')='text' "
            "AND json_type(job,'$.params.con_code') IS NULL",
            (GROUP, API),
        )
        if split_daily:
            raise ValueError("Split TDX member history days require separate review")

        planned_ids = []
        inserted = 0
        for job in _planned_ranges(config, today):
            before = db.total_changes
            job_id = pipeline.enqueue(API, job["params"], job["priority"], job["epoch"])
            inserted += db.total_changes - before
            planned_ids.append(job_id)
        if len(planned_ids) != len(set(planned_ids)):
            raise ValueError("TDX member range planner produced duplicate requests")
        db.execute(
            "CREATE TEMP TABLE tdx_member_range_coverage ("
            "job_id TEXT PRIMARY KEY,start_date TEXT NOT NULL,"
            "end_date TEXT NOT NULL) WITHOUT ROWID"
        )
        for job_id in planned_ids:
            row = db.execute(
                "SELECT state,job FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None or row["state"] not in RANGE_STATES:
                raise ValueError("Planned TDX member range is missing or unusable")
            params = json.loads(row["job"])["params"]
            if set(params) != {"start_date", "end_date"}:
                raise ValueError("Unexpected TDX member range request shape")
            db.execute(
                "INSERT INTO tdx_member_range_coverage VALUES(?,?,?)",
                (job_id, params["start_date"], params["end_date"]),
            )

        db.execute(
            "CREATE TEMP TABLE tdx_member_daily_covered ("
            "job_id TEXT PRIMARY KEY,range_id TEXT NOT NULL) WITHOUT ROWID"
        )
        db.execute(
            "INSERT OR IGNORE INTO tdx_member_daily_covered "
            "SELECT day.job_id,span.job_id FROM tdx_member_daily_open AS day "
            "JOIN tdx_member_range_coverage AS span "
            "ON span.start_date<=day.trade_date AND span.end_date>=day.trade_date "
            "JOIN jobs AS day_job ON day_job.id=day.job_id "
            "JOIN jobs AS range_job ON range_job.id=span.job_id "
            "WHERE json_extract(day_job.job,'$.fields')="
            "json_extract(range_job.job,'$.fields') "
            "AND json_extract(day_job.job,'$.row_cap')="
            "json_extract(range_job.job,'$.row_cap')"
        )
        old_open = len(daily)
        covered = _count(db, "SELECT count(*) FROM tdx_member_daily_covered")
        if covered != old_open:
            raise ValueError(
                f"{old_open - covered} TDX member history days lack matching range coverage"
            )
        external = _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id IN (SELECT job_id FROM tdx_member_daily_covered) "
            "AND parent.state='split_pending'",
        )
        if external:
            raise ValueError(
                "Covered TDX member days are shared by active split parents"
            )
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM tdx_member_daily_covered)",
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM tdx_member_daily_covered) AND state='pending'"
        ).rowcount
        if superseded != old_open:
            raise ValueError("Not every covered TDX member history day was retired")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during TDX member queue migration")
        if (
            _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
            != results_before
        ):
            raise ValueError(
                "Result-bearing jobs changed during TDX member queue migration"
            )
        planning_states_reset = db.execute(
            "DELETE FROM planning_state WHERE name='history:market_members'"
        ).rowcount
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "api": API,
            "today": today.strftime("%Y%m%d"),
            "planned_range_jobs": len(planned_ids),
            "inserted_range_jobs": inserted,
            "old_open_history_daily_jobs": old_open,
            "old_open_history_dates": len({item[1] for item in daily}),
            "old_open_history_bulk_jobs": sum(item[2] is None for item in daily),
            "old_open_history_board_jobs": sum(item[2] is not None for item in daily),
            "covered_history_daily_jobs": covered,
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
    path = Path(root) / ("tdx-member-daily-retirement-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".tdx-member-daily-", dir=root)
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
