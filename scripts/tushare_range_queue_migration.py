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
from backend.shared.tushare_pipeline import (  # noqa: E402
    Pipeline,
    RANGE_REPLACEMENT_GAP,
    contract_for,
)
from backend.shared.tushare_supplement_contracts import (  # noqa: E402
    iter_supplement_jobs,
)

SUPPORTED = ("moneyflow_dc", "dc_member")
OPEN = ("pending", "split_pending")
GAP = RANGE_REPLACEMENT_GAP
REPLACEMENT_ID_FIELDS = {"moneyflow_dc": "ts_code", "dc_member": "con_code"}
USABLE_REPLACEMENT_STATES = {
    "pending",
    "split_pending",
    "done",
    "empty",
    "quality",
    "resolved",
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


def repair_reconciled_gaps(
    pipeline,
    expected_total,
    *,
    expected_retired_edges=0,
    replacement_counts=None,
    apply=False,
):
    """Restore the durable range-replacement marker after legacy reconciliation."""
    for value, label in (
        (expected_total, "replacement parent"),
        (expected_retired_edges, "retired edge"),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Expected {label} count must be an integer")
        if value < 0:
            raise ValueError(f"Expected {label} count cannot be negative")
    replacement_counts = {} if replacement_counts is None else replacement_counts
    if not isinstance(replacement_counts, dict) or any(
        api not in SUPPORTED
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        for api, count in replacement_counts.items()
    ):
        raise ValueError("Invalid replacement inventory counts")
    db = pipeline.db
    rows = db.execute("""
        SELECT split.parent_id,parent.state,parent.tries,parent.result,
               split.status,split.gap,split.evidence
        FROM partition_splits AS split
        JOIN jobs AS parent ON parent.id=split.parent_id
        WHERE parent.state='blocked'
          AND json_extract(parent.job,'$.api_name') IN ('moneyflow_dc','dc_member')
          AND json_type(parent.job,'$.params.trade_date')='text'
          AND json_extract(parent.result,'$.status')='possibly_truncated'
          AND split.method='identifier_fanout'
          AND split.coverage_proven=0
          AND NOT EXISTS (
              SELECT 1 FROM partition_children AS edge
              LEFT JOIN jobs AS child ON child.id=edge.child_id
              WHERE edge.parent_id=split.parent_id
                AND COALESCE(child.state,'')<>'superseded'
          )
        ORDER BY split.parent_id
    """).fetchall()
    if len(rows) != expected_total:
        raise ValueError(
            f"Expected {expected_total} replacement parents, found {len(rows)}"
        )
    ids = [row["parent_id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    child_rows = (
        db.execute(
            f"SELECT edge.parent_id,child.* FROM partition_children AS edge "
            f"JOIN jobs AS child ON child.id=edge.child_id "
            f"WHERE edge.parent_id IN ({placeholders}) ORDER BY edge.parent_id,child.id",
            ids,
        ).fetchall()
        if ids
        else []
    )
    children_by_parent = {parent_id: [] for parent_id in ids}
    for child in child_rows:
        if child["state"] != "superseded":
            raise ValueError("Replacement parent still has a live child")
        children_by_parent[child["parent_id"]].append(child)
    inventories = {}
    effective_retired_edges = 0
    for row in rows:
        evidence = json.loads(row["evidence"])
        children = children_by_parent[row["parent_id"]]
        recorded_edges = evidence.get("retired_child_edges", 0)
        if (
            isinstance(recorded_edges, bool)
            or not isinstance(recorded_edges, int)
            or recorded_edges < 0
            or children and recorded_edges
        ):
            raise ValueError("Conflicting retired child evidence")
        retired_edges = len(children) or recorded_edges
        effective_retired_edges += retired_edges
        if not retired_edges:
            continue
        job = json.loads(
            db.execute(
                "SELECT job FROM jobs WHERE id=?", (row["parent_id"],)
            ).fetchone()[0]
        )
        api = job["api_name"]
        trade_date = job["params"].get("trade_date")
        expected = replacement_counts.get(api)
        if expected is None or not isinstance(trade_date, str):
            raise ValueError("Retired children require reviewed replacement coverage")
        key = (api, trade_date)
        if key in inventories:
            continue
        identity_field = REPLACEMENT_ID_FIELDS[api]
        replacements = db.execute(
            "SELECT id,state,job FROM jobs INDEXED BY jobs_partition_lookup "
            "WHERE epoch='history' AND json_extract(job,'$.api_name')=? "
            "AND json_extract(job,'$.params.start_date')<=? "
            "AND json_extract(job,'$.params.end_date')>=?",
            (api, trade_date, trade_date),
        ).fetchall()
        codes = set()
        states = {}
        parent_contract = {key: value for key, value in job.items() if key != "params"}
        replacement_ids = []
        for replacement in replacements:
            replacement_job = json.loads(replacement["job"])
            params = replacement_job.get("params")
            if (
                not isinstance(params, dict)
                or set(params) != {identity_field, "start_date", "end_date"}
                or not isinstance(params[identity_field], str)
                or {
                    key: value
                    for key, value in replacement_job.items()
                    if key != "params"
                }
                != parent_contract
                or replacement["state"] not in USABLE_REPLACEMENT_STATES
            ):
                raise ValueError("Replacement range does not match reviewed contract")
            codes.add(params[identity_field])
            states[replacement["state"]] = states.get(replacement["state"], 0) + 1
            replacement_ids.append(replacement["id"])
        if len(replacements) != expected or len(codes) != expected:
            raise ValueError(
                f"Expected {expected} unique {api} replacements, found "
                f"{len(replacements)} jobs and {len(codes)} codes"
            )
        replacement_placeholders = ",".join("?" for _ in replacement_ids)
        if db.execute(
            f"SELECT 1 FROM partition_children WHERE child_id IN "
            f"({replacement_placeholders}) LIMIT 1",
            replacement_ids,
        ).fetchone():
            raise ValueError("Replacement ranges must be independent roots")
        inventories[key] = {
            "api": api,
            "trade_date": trade_date,
            "identity_field": identity_field,
            "jobs": len(replacements),
            "codes": len(codes),
            "states": dict(sorted(states.items())),
        }
    if effective_retired_edges != expected_retired_edges:
        raise ValueError(
            f"Expected {expected_retired_edges} retired child edges, found "
            f"{effective_retired_edges}"
        )
    before_jobs = {
        row["parent_id"]: (row["state"], row["tries"], row["result"])
        for row in rows
    }
    protected_ids = ids + [child["id"] for child in child_rows]
    protected_placeholders = ",".join("?" for _ in protected_ids)
    before_children = {
        child["id"]: (child["state"], child["tries"], child["result"])
        for child in child_rows
    }
    before_attempts = (
        dict(
            db.execute(
                f"SELECT job_id,count(*) FROM attempts WHERE job_id IN ({protected_placeholders}) "
                "GROUP BY job_id",
                protected_ids,
            )
        )
        if protected_ids
        else {}
    )
    changed = 0
    removed_edges = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for row in rows:
            evidence = json.loads(row["evidence"])
            children = children_by_parent[row["parent_id"]]
            marker = evidence.get("replacement_gap")
            if marker not in (None, GAP):
                raise ValueError("Conflicting replacement gap marker")
            needs_update = (
                marker != GAP or row["status"] != "blocked" or row["gap"] != GAP
            )
            if needs_update:
                evidence["replacement_gap"] = GAP
                if children:
                    job = json.loads(
                        db.execute(
                            "SELECT job FROM jobs WHERE id=?", (row["parent_id"],)
                        ).fetchone()[0]
                    )
                    api = job["api_name"]
                    trade_date = job["params"]["trade_date"]
                    inventory = inventories[(api, trade_date)]
                    evidence.update(
                        {
                            "replacement_epoch": "history",
                            "replacement_identity_field": inventory["identity_field"],
                            "replacement_jobs": inventory["jobs"],
                            "replacement_trade_date": trade_date,
                            "retired_child_edges": len(children),
                        }
                    )
                db.execute(
                    "UPDATE partition_splits SET evidence=?,status='blocked',gap=? "
                    "WHERE parent_id=?",
                    (json.dumps(evidence, sort_keys=True), GAP, row["parent_id"]),
                )
                changed += 1
            elif children:
                raise ValueError("Retired child evidence is not idempotent")
        if child_rows:
            removed_edges = db.execute(
                f"DELETE FROM partition_children WHERE parent_id IN ({placeholders})",
                ids,
            ).rowcount
            if removed_edges != len(child_rows):
                raise ValueError("Retired child edge count changed")
        after_jobs = {
            row["id"]: (row["state"], row["tries"], row["result"])
            for row in db.execute(
                f"SELECT id,state,tries,result FROM jobs WHERE id IN ({placeholders})",
                ids,
            )
        } if ids else {}
        after_attempts = (
            dict(
                db.execute(
                    f"SELECT job_id,count(*) FROM attempts WHERE job_id IN ({protected_placeholders}) "
                    "GROUP BY job_id",
                    protected_ids,
                )
            )
            if protected_ids
            else {}
        )
        after_children = (
            {
                child["id"]: (child["state"], child["tries"], child["result"])
                for child in db.execute(
                    f"SELECT id,state,tries,result FROM jobs WHERE id IN "
                    f"({','.join('?' for _ in before_children)})",
                    list(before_children),
                )
            }
            if before_children
            else {}
        )
        if (
            after_jobs != before_jobs
            or after_children != before_children
            or after_attempts != before_attempts
        ):
            raise ValueError("Range replacement source evidence changed")
        if apply:
            db.commit()
        else:
            db.rollback()
    except BaseException:
        db.rollback()
        raise
    return {
        "status": (
            "applied"
            if apply and (changed or removed_edges)
            else "no_action"
            if apply
            else "planned_rollback"
        ),
        "replacement_parents": len(rows),
        "restored_markers": changed,
        "removed_retired_child_edges": removed_edges,
        "retired_child_edges": effective_retired_edges,
        "replacement_inventories": list(inventories.values()),
        "preserved_result_jobs": sum(row["result"] is not None for row in rows),
        "preserved_attempts": sum(before_attempts.values()),
        "upstream_calls": 0,
    }


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
            "UPDATE partition_splits SET status='blocked',gap=?,"
            "evidence=json_set(evidence,'$.replacement_gap',?) WHERE parent_id IN "
            "(SELECT id FROM old_range_migration_parents)",
            (GAP, GAP),
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
