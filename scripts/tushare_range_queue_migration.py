#!/usr/bin/env python3
"""Replace open per-day fanouts with reviewed stock-range jobs; no source calls."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
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

from backend.shared.tushare_dc_extra_contracts import iter_dc_extra_jobs  # noqa: E402
from backend.shared.tushare_pipeline import Pipeline, contract_for  # noqa: E402
from backend.shared.tushare_supplement_contracts import (  # noqa: E402
    iter_supplement_jobs,
)

SUPPORTED = ("moneyflow_dc", "dc_member")
OPEN = ("pending", "split_pending")
GAP = "replaced_by_stock_range_plan_v1"


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


def stock_codes(value):
    if not isinstance(value, list):
        raise ValueError("Stock input must be one JSON list")
    codes = set()
    for item in value:
        code = item.get("ts_code") if isinstance(item, dict) else item
        if not isinstance(code, str) or not re.fullmatch(
            r"T?[0-9]{6}\.(SH|SZ|BJ)", code
        ):
            raise ValueError("Invalid stock identifier")
        codes.add(code)
    if not codes:
        raise ValueError("At least one retained stock identifier is required")
    return sorted(codes)


def planned_jobs(config, today, codes, apis):
    identifiers = {"stocks": codes}
    for api in apis:
        if api == "moneyflow_dc":
            selected = {
                **config,
                "supplement_apis": [api],
                "planning_epoch": today.strftime("%Y%m%d"),
            }
            yield from iter_supplement_jobs(selected, today, identifiers)
        elif api == "dc_member":
            selected = {
                **config,
                "dc_extra_apis": [api],
                "planning_epoch": today.strftime("%Y%m%d"),
            }
            yield from iter_dc_extra_jobs(selected, today, identifiers)
        else:
            raise ValueError("Unsupported range migration API")


def _count(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _capture_open_daily(db, apis):
    """Materialize only target daily jobs through the existing queue indexes."""
    for api in apis:
        group = contract_for(api).get("group", "rrg")
        db.execute(
            "INSERT OR IGNORE INTO old_range_migration_open "
            "SELECT id FROM jobs INDEXED BY jobs_ready_api_history "
            "WHERE state='pending' AND group_name=? "
            "AND json_extract(job,'$.api_name')=? "
            "AND json_extract(job,'$.params.trade_date') IS NOT NULL",
            (group, api),
        )
        # split_pending is a small parent set and is covered by the state/group
        # index. It is intentionally separate from the pending-only index.
        db.execute(
            "INSERT OR IGNORE INTO old_range_migration_open "
            "SELECT id FROM jobs INDEXED BY jobs_group_pending "
            "WHERE state='split_pending' AND group_name=? "
            "AND json_extract(job,'$.api_name')=? "
            "AND json_extract(job,'$.params.trade_date') IS NOT NULL",
            (group, api),
        )


def migrate(pipeline, config, today, codes, apis, *, apply=False):
    """Apply one atomic queue replacement while preserving results and attempts."""
    apis = tuple(dict.fromkeys(apis))
    if not apis or any(api not in SUPPORTED for api in apis):
        raise ValueError("Select moneyflow_dc and/or dc_member")
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    attempts_before = _count(db, "SELECT count(*) FROM attempts")
    results_before = _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL")
    try:
        # The authority queue is multi-gigabyte. Keep the one-time candidate
        # B-tree and hot index pages in bounded memory instead of repeatedly
        # seeking through an APFS clone. Durability remains FULL below.
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-524288")
        db.execute("PRAGMA mmap_size=4294967296")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        for table in (
            "old_range_migration_open",
            "old_range_migration_parents",
        ):
            db.execute("DROP TABLE IF EXISTS temp." + table)
        planned_ids = set()
        invalid_planned_ids = set()
        inserted = 0
        for job in planned_jobs(config, today, codes, apis):
            before = db.total_changes
            job_id = pipeline.enqueue(
                job["api_name"],
                job["params"],
                job["priority"],
                job["epoch"],
                reuse_recent_open=job["epoch"] != "history",
            )
            planned_ids.add(job_id)
            changed = db.total_changes - before
            inserted += changed
            # Newly inserted jobs have a known valid state and range requests
            # cannot be selected by the trade_date retirement below. Only an
            # ignored/reused identity needs a point lookup. This avoids 65k
            # random reads through the multi-gigabyte jobs primary key.
            if not changed:
                state = db.execute(
                    "SELECT state FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if state is None or state["state"] in ("superseded", "blocked"):
                    invalid_planned_ids.add(job_id)
        db.execute(
            "CREATE TEMP TABLE old_range_migration_open "
            "(id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        _capture_open_daily(db, apis)
        old_open = _count(db, "SELECT count(*) FROM old_range_migration_open")
        db.execute(
            "CREATE TEMP TABLE old_range_migration_parents "
            "(id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        db.execute(
            "INSERT INTO old_range_migration_parents "
            "SELECT old.id FROM old_range_migration_open AS old "
            "JOIN partition_splits AS split ON split.parent_id=old.id"
        )
        parents = _count(db, "SELECT count(*) FROM old_range_migration_parents")
        external = _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "WHERE edge.child_id IN (SELECT id FROM old_range_migration_open) "
            "AND parent.state='split_pending' "
            "AND edge.parent_id NOT IN (SELECT id FROM old_range_migration_open)",
        )
        if external:
            raise ValueError("Old daily jobs are shared by active external parents")
        edges = _count(
            db,
            "SELECT count(*) FROM partition_children WHERE parent_id IN "
            "(SELECT id FROM old_range_migration_parents)",
        )
        db.execute(
            "DELETE FROM partition_children WHERE parent_id IN "
            "(SELECT id FROM old_range_migration_parents)"
        )
        blocked_parents = db.execute(
            "UPDATE jobs SET state='blocked' WHERE id IN "
            "(SELECT id FROM old_range_migration_parents) "
            "AND state IN ('pending','split_pending')"
        ).rowcount
        db.execute(
            "UPDATE partition_splits SET status='blocked',gap=? WHERE parent_id IN "
            "(SELECT id FROM old_range_migration_parents)",
            (GAP,),
        )
        superseded = db.execute(
            "UPDATE jobs SET state='superseded' WHERE id IN "
            "(SELECT id FROM old_range_migration_open) "
            "AND id NOT IN (SELECT id FROM old_range_migration_parents) "
            "AND state IN ('pending','split_pending')"
        ).rowcount
        remaining = _count(
            db,
            "SELECT count(*) FROM jobs WHERE id IN "
            "(SELECT id FROM old_range_migration_open) "
            "AND state IN ('pending','split_pending')",
        )
        if remaining:
            raise ValueError("Open daily jobs remained after range replacement")
        if _count(db, "SELECT count(*) FROM attempts") != attempts_before:
            raise ValueError("Attempt ledger changed during queue-only migration")
        if _count(db, "SELECT count(*) FROM jobs WHERE result IS NOT NULL") != results_before:
            raise ValueError("Result-bearing job count changed during migration")
        if blocked_parents + superseded != old_open:
            raise ValueError("Not every selected open daily job was retired exactly once")
        if _count(
            db,
            "SELECT count(*) FROM partition_children AS edge "
            "JOIN jobs AS parent ON parent.id=edge.parent_id "
            "JOIN jobs AS child ON child.id=edge.child_id "
            "WHERE parent.state='split_pending' "
            "AND child.state IN ('blocked','superseded') "
            "AND child.id IN (SELECT id FROM old_range_migration_open)",
        ):
            raise ValueError("Active split parent references a child retired here")
        if invalid_planned_ids:
            raise ValueError("Planned range job missing or retired")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "today": today.strftime("%Y%m%d"),
            "apis": list(apis),
            "stock_codes": len(codes),
            "stock_codes_sha256": _sha(_encoded(codes)),
            "planned_range_jobs": len(planned_ids),
            "inserted_range_jobs": inserted,
            "old_open_daily_jobs": old_open,
            "old_partition_parents": parents,
            "blocked_result_parents": blocked_parents,
            "superseded_open_children": superseded,
            "removed_partition_edges": edges,
            "attempts_preserved": attempts_before,
            "result_jobs_preserved": results_before,
            "active_parent_retired_child_refs": 0,
            # A whole-database quick_check on the 12+ GiB authority queue is an
            # offline copy check. Running it here would hold the write
            # transaction and archive-worker lock for about an extra hour.
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
    name = "range-queue-migration-v1." + _sha(body) + ".json"
    path = Path(root) / name
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".range-queue-", dir=root)
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
    parser.add_argument("--stocks", type=Path, required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--api", action="append", choices=SUPPORTED, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    today = datetime.strptime(args.today, "%Y%m%d").date()
    config = json.loads(_regular(root / "pipeline-config.json", "Config").read_bytes())
    catalog = json.loads(_regular(args.catalog, "Catalog").read_bytes())
    codes = stock_codes(json.loads(_regular(args.stocks, "Stocks").read_bytes()))
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    with ExitStack() as stack:
        locks = []
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        pipeline = Pipeline(root, catalog)
        stack.callback(pipeline.close)
        report = migrate(
            pipeline, config, today, codes, args.api, apply=args.apply
        )
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
