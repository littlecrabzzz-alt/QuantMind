#!/usr/bin/env python3
"""Bounded off-catalog permission/schema/filter probe; dry-run by default."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import sqlite3
import sys
import sysconfig
import time

APIS = (
    "film_record",
    "teleplay_record",
    "bo_monthly",
    "bo_weekly",
    "bo_daily",
    "bo_cinema",
    "fund_sales_ratio",
    "fund_sales_vol",
)
BASE_REQUESTS = (
    ("film_record", {"start_date": "20181014", "end_date": "20181214"}),
    ("teleplay_record", {"report_date": "201905"}),
    ("bo_monthly", {"date": "20180901"}),
    ("bo_weekly", {"date": "20181008"}),
    ("bo_daily", {"date": "20181014"}),
    ("bo_cinema", {"date": "20181014"}),
    ("fund_sales_ratio", {}),
    ("fund_sales_vol", {}),
)
FILTER_APIS = {"film_record", "teleplay_record", "fund_sales_vol"}
MAX_REQUESTS = len(BASE_REQUESTS) + len(FILTER_APIS)
MAX_SECONDS = 120
REPO = Path(__file__).resolve().parents[1]
EXPECTED_CONTRACT_SHA256 = (
    "175ee44d95ef21b2e7f7c424ac594a44a610aee21f09fd3dd9ce5de40666576a"
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def contract_evidence():
    from backend.shared.tushare_offcatalog_contracts import (
        FIELDS,
        INPUT_FIELDS,
        OFFCATALOG_CONTRACTS,
    )
    from backend.shared.tushare_registry import contract_for

    if not set(APIS).issubset(OFFCATALOG_CONTRACTS) or len(BASE_REQUESTS) != len(APIS):
        raise ValueError("Reviewed off-catalog contract set changed")
    evidence = {}
    for api, params in BASE_REQUESTS:
        spec = OFFCATALOG_CONTRACTS[api]
        if (
            contract_for(api).get("group") != "offcatalog"
            or spec["permission_status"] != "unprobed"
            or not set(params).issubset(INPUT_FIELDS[api])
            or spec["requested_fields"] != FIELDS[api]
            or not re.fullmatch(r"[a-f0-9]{64}", spec["source_html_sha256"])
        ):
            raise ValueError("Off-catalog runtime contract drift")
        evidence[api] = {
            "source_url": spec["source_url"],
            "source_html_sha256": spec["source_html_sha256"],
            "input_fields": INPUT_FIELDS[api],
            "requested_fields": FIELDS[api],
            "row_cap": spec["row_cap"],
            "row_cap_verified": spec["row_cap_verified"],
            "permission_status_before_probe": spec["permission_status"],
            "minimum_points": spec["minimum_points"],
            "history_start": spec["history_start"],
            "history_gap": spec["history_gap"],
            "pit_gap": spec["pit_gap"],
            "saturation_gap": spec["saturation_gap"],
        }
    if (
        EXPECTED_CONTRACT_SHA256
        and hashlib.sha256(canonical(evidence).encode()).hexdigest()
        != EXPECTED_CONTRACT_SHA256
    ):
        raise ValueError("Reviewed off-catalog contract evidence changed")
    return evidence


def safe_result(result):
    statuses = {
        "sample_ok",
        "schema_gap",
        "invalid_values",
        "possibly_truncated",
        "empty_unverified",
        "permission_denied",
        "rate_limited",
        "transport_error",
        "api_error",
        "invalid_response",
    }
    out = {
        "status": result.get("status")
        if result.get("status") in statuses
        else "invalid_response"
    }
    for name in (
        "row_count",
        "rate_limit_requests",
        "rate_limit_window_seconds",
        "http_status",
    ):
        if type(result.get(name)) is int and result[name] >= 0:
            out[name] = result[name]
    for name in (
        "response_complete",
        "supplier_has_more",
        "history_complete",
        "pit_verified",
    ):
        if type(result.get(name)) is bool or name in result and result[name] is None:
            out[name] = result[name]
    if result.get("field_coverage") in (
        "complete_for_explicit_request",
        "gap",
        "unverified_default_or_invalid",
    ):
        out["field_coverage"] = result["field_coverage"]
    for name in ("requested_missing_fields", "unexpected_returned_fields"):
        fields = result.get(name)
        if (
            isinstance(fields, list)
            and len(fields) <= 256
            and all(
                isinstance(field, str) and re.fullmatch(r"[A-Za-z0-9_]+", field)
                for field in fields
            )
        ):
            out[name] = fields
    if result.get("rate_limit_api") in APIS:
        out["rate_limit_api"] = result["rate_limit_api"]
    for name in ("object_sha256", "observation_sha256"):
        if re.fullmatch(r"[a-f0-9]{64}", str(result.get(name, ""))):
            out[name] = result[name]
    if result.get("api_name") in APIS:
        out["api_name"] = result["api_name"]
    if re.fullmatch(r"[a-f0-9]{32}\.json", str(result.get("observation", ""))):
        out["observation"] = result["observation"]
    part = result.get("parquet")
    if isinstance(part, dict) and re.fullmatch(
        r"parquet/[a-f0-9]{64}\.parquet", str(part.get("path", ""))
    ):
        out["parquet"] = {k: part[k] for k in ("path", "sha256", "bytes")}
    if result.get("normalization_error"):
        out["normalization_error"] = "normalization_failed_raw_retained"
    return out


def source_rows(root, result):
    sha = result.get("object_sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", str(sha or "")):
        return None
    path = root / "objects" / (sha + ".json")
    if (
        path.is_symlink()
        or path.parent.is_symlink()
        or path.stat().st_size > 32 * 1024**2
    ):
        raise ValueError("Unsafe probe object")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("Probe object checksum mismatch")
    payload = json.loads(raw)
    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        return None
    fields = payload["data"].get("fields")
    items = payload["data"].get("items")
    if (
        not isinstance(fields, list)
        or not fields
        or len(fields) > 256
        or len(set(fields)) != len(fields)
        or any(
            not isinstance(f, str) or not re.fullmatch(r"[A-Za-z0-9_]+", f)
            for f in fields
        )
        or not isinstance(items, list)
        or len(items) > 50000
        or any(not isinstance(row, list) or len(row) != len(fields) for row in items)
    ):
        raise ValueError("Invalid bounded probe rows")
    return [dict(zip(fields, row, strict=True)) for row in items]


def _text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def filter_request(api, rows):
    """Use only values present in the immediately preceding raw response."""
    if not rows or api not in FILTER_APIS:
        return None
    for row in sorted(rows, key=canonical):
        if api == "film_record":
            value = _text(row.get("ann_date"))
            if value and re.fullmatch(r"[0-9]{8}", value):
                return {"ann_date": value}
        elif api == "teleplay_record":
            month = _text(row.get("report_date"))
            org, name = _text(row.get("org")), _text(row.get("name"))
            if month and re.fullmatch(r"[0-9]{6}", month) and org and name:
                return {"report_date": month, "org": org, "name": name}
        else:
            year = str(row.get("year", ""))
            quarter, name = _text(row.get("quarter")), _text(row.get("inst_name"))
            if (
                re.fullmatch(r"[0-9]{4}", year)
                and quarter
                and re.fullmatch(r"Q[1-4]", quarter)
                and name
            ):
                return {"year": year, "quarter": quarter, "name": name}
    return None


def assess_filter(api, params, base_rows, filtered_rows):
    if filtered_rows is None:
        return {"status": "filter_response_unavailable", "row_count": None}
    mapping = dict(params)
    if api == "fund_sales_vol":
        mapping["inst_name"] = mapping.pop("name")
    matches = all(
        str(row.get(field)) == str(value)
        for row in filtered_rows
        for field, value in mapping.items()
    )
    base = {canonical(row) for row in base_rows or []}
    subset = all(canonical(row) in base for row in filtered_rows)
    return {
        "status": "filter_match_observed"
        if filtered_rows and matches
        else "empty_filter_unverified"
        if not filtered_rows
        else "filter_mismatch",
        "row_count": len(filtered_rows),
        "all_rows_match_requested_filter": matches,
        "returned_rows_subset_of_base_observation": subset,
    }


def assess_base_filter(api, params, rows):
    if not params:
        return {"status": "unfiltered_base_request", "row_count": len(rows or [])}
    if rows is None:
        return {"status": "filter_response_unavailable", "row_count": None}
    if api == "film_record":
        matches = all(
            isinstance(row.get("ann_date"), str)
            and params["start_date"] <= row["ann_date"] <= params["end_date"]
            for row in rows
        )
    else:
        field = "report_date" if api == "teleplay_record" else "date"
        matches = all(str(row.get(field)) == str(params[field]) for row in rows)
    return {
        "status": "filter_match_observed"
        if rows and matches
        else "empty_filter_unverified"
        if not rows
        else "filter_mismatch",
        "row_count": len(rows),
        "all_rows_match_requested_filter": matches,
    }


class DeferredCommit:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, name):
        return getattr(self.db, name)

    def commit(self):
        pass


def reserve_probe(pipeline, api, params, epoch):
    db = pipeline.db
    db.execute("BEGIN IMMEDIATE")
    try:
        mark = db.execute("SELECT COALESCE(max(rowid),0) FROM jobs").fetchone()[0]
        pipeline.db = DeferredCommit(db)
        key = pipeline.enqueue(api, params, -100, epoch)
        pipeline.db = db
        row = db.execute("SELECT rowid,* FROM jobs WHERE id=?", (key,)).fetchone()
        if row["rowid"] > mark and row["state"] == "pending":
            db.execute("UPDATE jobs SET state='probe_prepared' WHERE id=?", (key,))
        db.commit()
        return key, db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
    except BaseException:
        db.rollback()
        raise
    finally:
        pipeline.db = db


def resolved_gates(db, api, config):
    from backend.shared.tushare_rate_policy import (
        POLICY,
        positive_int,
        resolved_api_rate,
    )
    from backend.shared.tushare_registry import contract_for

    if config.get("rate_policy") != POLICY:
        raise ValueError("Reviewed tiered_v1 policy is required")
    account = positive_int(config.get("requests_per_minute"), "account request rate")
    if config.get("rollout_account_rpm") is not None:
        account = min(
            account,
            positive_int(config["rollout_account_rpm"], "rollout account rate"),
        )
    rpm = resolved_api_rate(api, contract_for(api), config, datetime.now(timezone.utc))[
        "rpm"
    ]
    interval = config.get("api_min_interval_seconds", {}).get(api, 0)
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not math.isfinite(interval)
        or not 0 <= interval <= 86400
    ):
        raise ValueError("Invalid minimum interval")
    quota = db.execute(
        "SELECT reason FROM capability WHERE scope=? AND status='rate_limit_observed'",
        ("quota:" + api,),
    ).fetchone()
    if quota:
        observed = json.loads(quota[0])["interval_seconds"]
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(observed)
            or observed < 0
        ):
            raise ValueError("Invalid observed quota interval")
        interval = max(interval, observed)
    return account, rpm, interval


class ProbeDeadline(Exception):
    pass


def collect(pipeline, config, client, token_getter, args):
    from backend.shared.tushare_intake import capture_sample, utc_now
    from backend.shared.tushare_pipeline import atomic_json

    if args.report.exists():
        raise ValueError("Fresh bounded report required")
    contracts = contract_evidence()
    reports, calls, stop, token = [], 0, None, None
    deadline = time.monotonic() + args.seconds

    def checkpoint():
        report = {
            "schema_version": 1,
            "authority_schema_version": 6,
            "epoch": args.epoch,
            "updated_at": utc_now(),
            "actual_upstream_calls": calls,
            "max_requests": MAX_REQUESTS,
            "deadline_seconds": args.seconds,
            "results": reports,
            "stop_reason": stop,
            "helper_sha256": args.helper_sha256,
            "contract_evidence": contracts,
            "base_requests": [
                {"api_name": api, "params": params} for api, params in BASE_REQUESTS
            ],
            "dynamic_filter_apis": sorted(FILTER_APIS),
            "automatic_activation_permitted": False,
            "configuration_changed": False,
            "history_complete": False,
            "pit_verified": False,
            "publication_required": True,
        }
        atomic_json(args.report, report)
        return report

    def expire(signum, frame):
        raise ProbeDeadline()

    def request(api, params, phase):
        nonlocal calls, stop, token
        if calls >= MAX_REQUESTS or time.monotonic() + 1 >= deadline:
            stop = "request_limit" if calls >= MAX_REQUESTS else "total_deadline"
            return None, None
        key, row = reserve_probe(pipeline, api, params, args.epoch)
        prefix = {"api_name": api, "params": params, "phase": phase, "job_id": key}
        if row["state"] != "probe_prepared":
            reports.append(
                {
                    **prefix,
                    "status": "skipped_uncertain_prior_request"
                    if row["state"] == "probe_inflight"
                    else "skipped_existing_nonpending_job",
                }
            )
            checkpoint()
            return None, None
        denied = pipeline.db.execute(
            "SELECT 1 FROM capability WHERE scope IN (?,?) AND status='permission_denied'",
            (api, api + ":"),
        ).fetchone()
        if denied:
            reports.append({**prefix, "status": "skipped_cached_permission_denied"})
            checkpoint()
            return None, None
        gate = (
            pipeline.db.execute(
                "SELECT MAX(next_at) FROM request_gates WHERE scope IN (?,?)",
                ("account", "api:" + api),
            ).fetchone()[0]
            or 0
        )
        delay = max(0, gate - time.time(), row["retry_after"] - time.time())
        if time.monotonic() + delay + 13 >= deadline:
            reports.append({**prefix, "status": "deferred_cached_gate"})
            checkpoint()
            return None, None
        if delay:
            time.sleep(delay)
        account, rpm, interval = resolved_gates(pipeline.db, api, config)
        now = time.time()
        pipeline.db.executemany(
            "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
            [
                ("account", now + 60 / account),
                ("api:" + api, now + max(60 / rpm, interval)),
            ],
        )
        pipeline.db.execute("UPDATE jobs SET state='probe_inflight' WHERE id=?", (key,))
        pipeline.db.commit()
        if token is None:
            token = token_getter()
        if not token:
            raise ValueError("missing provider credential")
        calls += 1
        signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic()))
        try:
            result = capture_sample(
                client, token, json.loads(row["job"]), pipeline.root
            )
        except ProbeDeadline:
            result = {
                "api_name": api,
                "status": "transport_error",
                "response_complete": False,
            }
            stop = "total_deadline"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        if result.get("local_daily_quota") and result.get("upstream_calls") == 0:
            calls -= 1
            pipeline.db.execute(
                "UPDATE jobs SET state='probe_prepared' WHERE id=?", (key,)
            )
            pipeline.db.commit()
            reports.append(
                {**prefix, "status": "deferred_local_daily_quota", "upstream_calls": 0}
            )
            checkpoint()
            return None, None
        rows = source_rows(pipeline.root, result)
        if result.get("row_count", 0):
            try:
                result = pipeline.normalize(result)
            except Exception as exc:
                result["normalization_error"] = type(exc).__name__
        safe = safe_result(result)
        status = safe["status"]
        if status == "permission_denied":
            pipeline.db.execute(
                "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'permission_denied',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                (api + ":", utc_now(), "finite_offcatalog_probe_denied"),
            )
        if status == "rate_limited":
            scoped = safe.get("rate_limit_api") == api
            scope = "api:" + api if scoped else "account"
            cooldown = safe.get("rate_limit_window_seconds", 60) if scoped else 60
            pipeline.db.execute(
                "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                (scope, time.time() + cooldown),
            )
        state = (
            "done"
            if status in ("sample_ok", "possibly_truncated")
            else "empty"
            if status == "empty_unverified"
            else "quality"
            if status in ("schema_gap", "invalid_values")
            or safe.get("normalization_error")
            else "blocked"
        )
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (key, row["tries"] + 1, json.dumps(safe)),
        )
        pipeline.db.execute(
            "UPDATE jobs SET state=?,result=?,tries=tries+1 WHERE id=?",
            (state, json.dumps(safe), key),
        )
        pipeline.db.commit()
        reports.append({**prefix, **safe})
        checkpoint()
        return safe, rows

    previous = signal.signal(signal.SIGALRM, expire)
    try:
        for api, params in BASE_REQUESTS:
            result, rows = request(api, params, "base")
            if stop:
                break
            if result is not None:
                reports[-1]["base_filter_assessment"] = assess_base_filter(
                    api, params, rows
                )
                checkpoint()
            followup = filter_request(api, rows)
            if api not in FILTER_APIS:
                continue
            if not followup:
                reports[-1]["filter_followup"] = "not_planned_no_valid_source_row"
                checkpoint()
                continue
            filtered_result, filtered_rows = request(api, followup, "actual_row_filter")
            if filtered_result is not None:
                reports[-1]["filter_assessment"] = assess_filter(
                    api, followup, rows, filtered_rows
                )
                checkpoint()
            if stop:
                break
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        final = checkpoint()
        token = None
    return final


def require_schema6(db_path):
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("existing authority queue required")
    with sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Expected installed schema6; no migration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--root", type=Path, default=Path("/data/tushare"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    helper_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.helper_sha256 = helper_sha
    if not 15 <= args.seconds <= MAX_SECONDS:
        parser.error("invalid finite deadline")
    if args.repo.resolve() != REPO.resolve():
        parser.error("repo must be the checkout containing this reviewed helper")
    sys.path[:0] = [str(REPO), sysconfig.get_paths()["purelib"]]
    contracts = contract_evidence()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "actual_upstream_calls": 0,
                    "base_requests": BASE_REQUESTS,
                    "dynamic_filter_apis": sorted(FILTER_APIS),
                    "max_requests": MAX_REQUESTS,
                    "deadline_seconds": args.seconds,
                    "helper_sha256": helper_sha,
                    "contract_evidence": contracts,
                    "authority_accessed": False,
                    "token_accessed": False,
                }
            )
        )
        return
    if args.expected_helper_sha256 != helper_sha:
        parser.error("execute requires the reviewed helper SHA256")
    import httpx
    from backend.shared.runtime_secrets import get_secret
    from backend.shared.tushare_pipeline import ROOT, Pipeline, authority

    authority()
    if args.root.resolve() != ROOT.resolve() or ROOT.resolve() != Path("/data/tushare"):
        raise ValueError("existing authority root required")
    if not args.report.resolve().is_relative_to(ROOT / "validation"):
        raise ValueError("probe report must stay under authority validation")
    if args.report.exists():
        raise ValueError("Fresh report required")
    lock_path, db_path = ROOT / "pipeline.lock", ROOT / "pipeline.sqlite"
    if (
        lock_path.is_symlink()
        or db_path.is_symlink()
        or not lock_path.is_file()
        or not db_path.is_file()
    ):
        raise ValueError("existing authority queue required")
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_schema6(db_path)
        pipeline = Pipeline(
            ROOT, json.loads((args.repo / "config/tushare-catalog.json").read_bytes())
        )
        try:
            config = json.loads((ROOT / "pipeline-config.json").read_bytes())
            args.epoch = "probe-offcatalog-" + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ"
            )
            with httpx.Client(
                trust_env=False, timeout=12, follow_redirects=False
            ) as client:
                report = collect(
                    pipeline,
                    config,
                    client,
                    lambda: get_secret("TUSHARE_TOKEN"),
                    args,
                )
        finally:
            pipeline.close()
    print(
        json.dumps(
            {
                "report": str(args.report),
                "actual_upstream_calls": report["actual_upstream_calls"],
                "samples": len(report["results"]),
                "stop_reason": report["stop_reason"],
                "publication_required": True,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
