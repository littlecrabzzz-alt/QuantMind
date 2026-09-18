#!/usr/bin/env python3
"""Retire truncated unfiltered WZ/GZ jobs covered by terminal date ranges."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_pipeline import Pipeline, authority  # noqa: E402

APIS = ("wz_index", "gz_index")
TERMINAL = {("done", "sample_ok"), ("empty", "empty_unverified")}


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


def _day(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"Invalid {label}")
    parsed = datetime.strptime(value, "%Y%m%d").date()
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"Invalid {label}")
    return parsed


def _configured_start(config, api):
    setting = config.get("other_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("other_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict):
        value = setting.get(api)
    else:
        value = setting
    if value is None:
        value = config.get("history_start")
    if value is None:
        raise ValueError(f"{api} has no explicit history scope")
    return _day(value, f"{api} history start")


def _verify_artifacts(root, result):
    required = ("object_sha256", "observation", "observation_sha256")
    if any(not isinstance(result.get(key), str) for key in required):
        raise ValueError("Result lacks immutable artifact references")
    paths = [
        (root / "objects" / (result["object_sha256"] + ".json"), result["object_sha256"]),
        (root / "observations" / result["observation"], result["observation_sha256"]),
    ]
    parquet = result.get("parquet")
    if parquet is not None:
        if (
            not isinstance(parquet, dict)
            or not isinstance(parquet.get("path"), str)
            or not isinstance(parquet.get("sha256"), str)
        ):
            raise ValueError("Invalid parquet artifact reference")
        path = root / parquet["path"]
        if root not in path.resolve().parents:
            raise ValueError("Parquet artifact escapes archive root")
        paths.append((path, parquet["sha256"]))
    for path, expected in paths:
        if _sha(_regular(path, "Artifact").read_bytes()) != expected:
            raise ValueError("Immutable artifact digest mismatch")
    return len(paths)


def _cover(intervals, first, last):
    """Return a deterministic minimum-prefix cover of every calendar day."""
    cursor = first
    selected = []
    ordered = sorted(intervals, key=lambda item: (item[1], item[2], item[0]))
    position = 0
    while cursor <= last:
        best = None
        while position < len(ordered) and ordered[position][1] <= cursor:
            item = ordered[position]
            if item[2] >= cursor and (best is None or (item[2], item[0]) > (best[2], best[0])):
                best = item
            position += 1
        if best is None:
            raise ValueError(f"Date-range coverage has a gap at {cursor:%Y%m%d}")
        selected.append(best)
        cursor = best[2] + timedelta(days=1)
    return selected


def migrate(pipeline, config, through, *, apply=False):
    if not isinstance(through, date):
        raise ValueError("through must be a date")
    db = pipeline.db
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Expected pipeline schema 6")
    enabled = config.get("other_apis", [])
    if config.get("enable_other") is not True or not isinstance(enabled, list):
        raise ValueError("Other-market collection must be explicitly enabled")
    targets = [api for api in APIS if api in enabled]
    if not targets:
        raise ValueError("No WZ/GZ API is enabled")
    attempts_before = {}
    results_before = {}
    candidates = []
    coverage = {}
    artifacts_checked = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for api in targets:
            start = _configured_start(config, api)
            if start > through:
                raise ValueError("Configured history start is after through")
            rows = db.execute(
                "SELECT id,state,epoch,job,result FROM jobs INDEXED BY jobs_discovery_api "
                "WHERE result IS NOT NULL AND json_extract(job,'$.api_name')=?",
                (api,),
            ).fetchall()
            intervals = []
            for row in rows:
                job = json.loads(row["job"])
                result = json.loads(row["result"])
                params = job.get("params")
                if params == {}:
                    if (
                        row["state"] == "blocked"
                        and result.get("api_name") == api
                        and result.get("status") == "possibly_truncated"
                        and result.get("supplier_has_more") is True
                        and isinstance(result.get("row_count"), int)
                        and result["row_count"] > 0
                    ):
                        candidates.append((api, row, result))
                    continue
                if not isinstance(params, dict) or set(params) != {"start_date", "end_date"}:
                    continue
                if (row["state"], result.get("status")) not in TERMINAL:
                    continue
                if result.get("api_name") != api:
                    raise ValueError("Range result belongs to another API")
                if result.get("supplier_has_more") is not False:
                    continue
                left = _day(params["start_date"], "range start")
                right = _day(params["end_date"], "range end")
                if left > right:
                    raise ValueError("Reversed date range")
                intervals.append((row["id"], left, right, result))
            selected = _cover(intervals, start, through)
            for _job_id, _left, _right, result in selected:
                artifacts_checked += _verify_artifacts(pipeline.root, result)
            coverage[api] = {
                "configured_start": start.strftime("%Y%m%d"),
                "through": through.strftime("%Y%m%d"),
                "range_jobs": len(selected),
                "range_job_ids_sha256": _sha(_encoded(sorted(item[0] for item in selected))),
            }
        for api, row, result in candidates:
            artifacts_checked += _verify_artifacts(pipeline.root, result)
            attempts_before[row["id"]] = db.execute(
                "SELECT count(*) FROM attempts WHERE job_id=?", (row["id"],)
            ).fetchone()[0]
            results_before[row["id"]] = row["result"]
            reason = {
                "api_name": api,
                "reason": "unfiltered request replaced by terminal bounded ranges",
                **coverage[api],
                "coverage_proven": True,
                "earlier_history_absent_proven": False,
                "source_attempts_preserved": True,
                "source_result_preserved": True,
                "upstream_calls": 0,
            }
            db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET status=excluded.status,"
                "checked_at=excluded.checked_at,reason=excluded.reason",
                (
                    "retirement:" + row["id"],
                    "request_contract_superseded",
                    datetime.now(ZoneInfo("UTC")).isoformat(),
                    json.dumps(reason, sort_keys=True),
                ),
            )
            changed = db.execute(
                "UPDATE jobs SET state='superseded' WHERE id=? AND state='blocked'",
                (row["id"],),
            ).rowcount
            if changed != 1:
                raise ValueError("Candidate state changed during retirement")
        for job_id, result_before in results_before.items():
            after = db.execute("SELECT state,result FROM jobs WHERE id=?", (job_id,)).fetchone()
            if after["state"] != "superseded" or after["result"] != result_before:
                raise ValueError("Supplier result changed during retirement")
            attempts_after = db.execute(
                "SELECT count(*) FROM attempts WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            if attempts_after != attempts_before[job_id]:
                raise ValueError("Attempt ledger changed during retirement")
        report = {
            "status": "applied" if apply else "planned_rollback",
            "schema_version": 1,
            "through": through.strftime("%Y%m%d"),
            "apis": targets,
            "coverage": coverage,
            "candidate_jobs": len(candidates),
            "superseded_jobs": len(candidates),
            "candidate_ids_sha256": _sha(_encoded(sorted(results_before))),
            "artifacts_checked": artifacts_checked,
            "source_results_preserved": len(results_before),
            "source_attempts_preserved": sum(attempts_before.values()),
            "earlier_history_absent_proven": False,
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
    path = root / ("other-unfiltered-retirement-v1." + _sha(body) + ".json")
    if path.exists() or path.is_symlink():
        if _regular(path, "Existing receipt").read_bytes() != body:
            raise ValueError("Receipt path collision")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".other-unfiltered-", dir=root)
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
    parser.add_argument("--through", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-script-sha256")
    parser.add_argument("--expected-contract-sha256")
    parser.add_argument("--expected-config-sha256")
    args = parser.parse_args()
    root = args.root.resolve()
    catalog_path = _regular(args.catalog, "Catalog")
    config_path = _regular(root / "pipeline-config.json", "Pipeline config")
    script_sha = _sha(_regular(Path(__file__), "Migration script").read_bytes())
    contract_path = REPO / "backend/shared/tushare_other_contracts.py"
    contract_sha = _sha(_regular(contract_path, "Other contracts").read_bytes())
    config_body = config_path.read_bytes()
    config_sha = _sha(config_body)
    if args.apply:
        expected = (
            args.expected_script_sha256,
            args.expected_contract_sha256,
            args.expected_config_sha256,
        )
        actual = (script_sha, contract_sha, config_sha)
        if any(value is None for value in expected) or expected != actual:
            raise ValueError("Apply requires exact script, contract and config SHA-256 pins")
    if _day(args.through, "through") > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("through cannot be in the future")
    for name in ("pipeline.sqlite", "pipeline.lock", ".archive-worker.lock"):
        _regular(root / name, name)
    os.environ["QM_NODE_ROLE"] = "archive"
    os.environ["QM_TUSHARE_ARCHIVE_ROOT"] = str(root)
    authority()
    with ExitStack() as stack:
        for name in (".archive-worker.lock", "pipeline.lock"):
            handle = stack.enter_context((root / name).open("rb"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pipeline = Pipeline(root, json.loads(catalog_path.read_bytes()))
        stack.callback(pipeline.close)
        report = migrate(
            pipeline,
            json.loads(config_body),
            _day(args.through, "through"),
            apply=args.apply,
        )
        report.update(
            {
                "script_sha256": script_sha,
                "contract_sha256": contract_sha,
                "config_sha256": config_sha,
            }
        )
        if args.apply:
            report["receipt"] = str(_write_receipt(root, report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
