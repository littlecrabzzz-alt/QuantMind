#!/usr/bin/env python3
"""Retire impossible pre-start asset jobs; preserve results and split graphs."""

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

from backend.shared.tushare_pipeline import Pipeline, contract_for  # noqa: E402
from backend.shared.tushare_stock_lifecycle import (  # noqa: E402
    asset_start_dates,
    stock_list_dates,
)

SUPPORTED = {
    "index_daily": ("index_lifecycles", "ts_code"),
    "index_weight": ("index_lifecycles", "index_code"),
    "fund_nav": ("fund_lifecycles", "ts_code"),
    "weekly": ("stock_lifecycles", "ts_code"),
    "monthly": ("stock_lifecycles", "ts_code"),
    "index_weekly": ("index_lifecycles", "ts_code"),
    "index_monthly": ("index_lifecycles", "ts_code"),
}
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


def _candidate_sql(api, state):
    if api not in SUPPORTED or state not in ("pending", "split_pending"):
        raise ValueError("Unsupported lifecycle migration selection")
    family, code_field = SUPPORTED[api]
    index = "jobs_ready_api_history" if state == "pending" else "jobs_group_pending"
    code = f"json_extract(job.job,'$.params.{code_field}')"
    trade_date = "json_extract(job.job,'$.params.trade_date')"
    start_date = "json_extract(job.job,'$.params.start_date')"
    end_date = "json_extract(job.job,'$.params.end_date')"
    return (
        "SELECT job.id,? AS api,life.start_date,"
        f"CASE WHEN json_type(job.job,'$.params.trade_date')='text' "
        "THEN 'prestart_day' "
        f"WHEN {end_date}<life.start_date THEN 'prestart_range' "
        "ELSE 'crossing_range' END AS kind "
        f"FROM jobs AS job INDEXED BY {index} "
        "JOIN asset_lifecycle_bounds AS life "
        f"ON life.family=? AND life.ts_code={code} "
        f"WHERE job.state='{state}' AND job.group_name=? "
        "AND json_extract(job.job,'$.api_name')=? AND ("
        "(json_type(job.job,'$.params.trade_date')='text' "
        f"AND length({trade_date})=8 AND {trade_date} NOT GLOB '*[^0-9]*' "
        f"AND {trade_date}<life.start_date) OR "
        "(json_type(job.job,'$.params.start_date')='text' "
        "AND json_type(job.job,'$.params.end_date')='text' "
        f"AND length({start_date})=8 AND length({end_date})=8 "
        f"AND {start_date} NOT GLOB '*[^0-9]*' "
        f"AND {end_date} NOT GLOB '*[^0-9]*' "
        f"AND {start_date}<life.start_date))"
    )


def _selection_params(api):
    family, _ = SUPPORTED[api]
    return api, family, contract_for(api).get("group", "rrg"), api


def _bounds(identifiers):
    stock = stock_list_dates(identifiers)
    indexes = asset_start_dates(identifiers, "index_lifecycles")
    funds = asset_start_dates(identifiers, "fund_lifecycles")
    return {
        "stock_lifecycles": stock,
        "index_lifecycles": indexes,
        "fund_lifecycles": funds,
    }


def migrate(pipeline, identifiers=None, *, apply=False):
    """Apply one atomic queue-only migration with no upstream requests."""
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    if identifiers is None:
        identifiers = pipeline.identifiers(_use_cache=False)
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must be a mapping")
    bounds = _bounds(identifiers)
    attempts_before = _count(db, "SELECT count(*) FROM attempts")
    results_before = _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
    try:
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-262144")
        db.execute("PRAGMA mmap_size=4294967296")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        for table in ("asset_lifecycle_bounds", "asset_lifecycle_candidates"):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        db.execute(
            "CREATE TEMP TABLE asset_lifecycle_bounds ("
            "family TEXT NOT NULL,ts_code TEXT NOT NULL,start_date TEXT NOT NULL,"
            "PRIMARY KEY(family,ts_code)) WITHOUT ROWID"
        )
        db.executemany(
            "INSERT INTO asset_lifecycle_bounds VALUES(?,?,?)",
            [
                (family, code, start_date)
                for family, values in bounds.items()
                for code, start_date in sorted(values.items())
            ],
        )
        db.execute(
            "CREATE TEMP TABLE asset_lifecycle_candidates ("
            "job_id TEXT PRIMARY KEY,api TEXT NOT NULL,start_date TEXT NOT NULL,"
            "kind TEXT NOT NULL) WITHOUT ROWID"
        )
        per_api = {}
        for api, (family, code_field) in SUPPORTED.items():
            db.execute(
                "INSERT INTO asset_lifecycle_candidates "
                + _candidate_sql(api, "pending"),
                _selection_params(api),
            )
            counts = {
                row["kind"]: row["count"]
                for row in db.execute(
                    "SELECT kind,count(*) AS count FROM asset_lifecycle_candidates "
                    "WHERE api=? GROUP BY kind",
                    (api,),
                )
            }
            split_pending = _count(
                db,
                "SELECT count(*) FROM (" + _candidate_sql(api, "split_pending") + ")",
                _selection_params(api),
            )
            group = contract_for(api).get("group", "rrg")
            unknown = _count(
                db,
                "SELECT count(*) FROM jobs AS job INDEXED BY jobs_ready_api_history "
                "LEFT JOIN asset_lifecycle_bounds AS life ON life.family=? "
                f"AND life.ts_code=json_extract(job.job,'$.params.{code_field}') "
                "WHERE job.state='pending' AND job.group_name=? "
                "AND json_extract(job.job,'$.api_name')=? AND life.ts_code IS NULL",
                (family, group, api),
            )
            per_api[api] = {
                "prestart_days": counts.get("prestart_day", 0),
                "prestart_ranges": counts.get("prestart_range", 0),
                "crossing_ranges": counts.get("crossing_range", 0),
                "split_pending_candidates_preserved": split_pending,
                "unknown_lifecycle_pending_preserved": unknown,
            }

        preserved_rows = db.execute(
            "SELECT candidate.api,count(DISTINCT candidate.job_id) AS count "
            "FROM asset_lifecycle_candidates AS candidate "
            "JOIN partition_children AS edge ON edge.child_id=candidate.job_id "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE parent.state='split_pending' GROUP BY candidate.api"
        ).fetchall()
        preserved_by_api = {row["api"]: row["count"] for row in preserved_rows}
        for api in SUPPORTED:
            per_api[api]["active_parent_children_preserved"] = preserved_by_api.get(
                api, 0
            )
        db.execute(
            "DELETE FROM asset_lifecycle_candidates WHERE EXISTS ("
            "SELECT 1 FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id=asset_lifecycle_candidates.job_id "
            "AND parent.state='split_pending')"
        )

        replacements = set()
        inserted = 0
        reused = 0
        crossing = db.execute(
            "SELECT job.job,job.priority,job.epoch,candidate.start_date "
            "FROM asset_lifecycle_candidates AS candidate "
            "JOIN jobs AS job ON job.id=candidate.job_id "
            "WHERE candidate.kind='crossing_range' ORDER BY job.rowid"
        ).fetchall()
        for row in crossing:
            original = json.loads(row["job"])
            params = {**original["params"], "start_date": row["start_date"]}
            before = db.total_changes
            replacement = pipeline.enqueue(
                original["api_name"], params, row["priority"], row["epoch"]
            )
            changed = db.total_changes - before
            inserted += int(bool(changed))
            reused += int(not changed)
            saved = db.execute(
                "SELECT state FROM jobs WHERE id=?", (replacement,)
            ).fetchone()
            if saved is None or saved["state"] not in USABLE_REPLACEMENT_STATES:
                raise ValueError("Crossing range replacement is missing or retired")
            replacements.add(replacement)

        candidate_count = _count(db, "SELECT count(*) FROM asset_lifecycle_candidates")
        candidate_attempts = _count(
            db,
            "SELECT count(*) FROM attempts WHERE job_id IN "
            "(SELECT job_id FROM asset_lifecycle_candidates)",
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT job_id FROM asset_lifecycle_candidates) AND state='pending'"
        ).rowcount
        if superseded != candidate_count:
            raise ValueError("Not every lifecycle candidate was retired exactly once")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during queue-only migration")
        if (
            _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
            != results_before
        ):
            raise ValueError("Result-bearing job count changed during migration")

        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "known_starts": {family: len(values) for family, values in bounds.items()},
            "per_api": per_api,
            "candidate_jobs": candidate_count,
            "superseded_jobs": superseded,
            "crossing_replacement_jobs": len(replacements),
            "inserted_replacement_jobs": inserted,
            "reused_replacement_jobs": reused,
            "active_parent_children_preserved": sum(preserved_by_api.values()),
            "split_pending_candidates_preserved": sum(
                values["split_pending_candidates_preserved"]
                for values in per_api.values()
            ),
            "candidate_attempts_preserved": candidate_attempts,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "completed_jobs_action": "unchanged",
            "unknown_lifecycle_action": "preserved_unbounded",
            "active_partition_action": "preserved",
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
    path = Path(root) / ("asset-lifecycle-migration-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".asset-lifecycle-", dir=root)
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
