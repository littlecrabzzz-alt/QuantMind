#!/usr/bin/env python3
"""Reviewable 15-request realtime/auction probe; plan-only by default. No publish or enable.
Run as a repository script; dry-run has no executable slot or mutable database access.
"""

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import signal
import sys
import sysconfig
import time

import math
import sqlite3
from datetime import date, datetime, timezone

MAX_REQUESTS = 15
MAX_SECONDS = 120
APIS = (
    "stk_auction",
    "rt_etf_sz_iopv",
    "rt_idx_k",
    "rt_idx_min",
    "rt_sw_k",
    "rt_fut_min",
    "rt_k",
    "rt_etf_k",
    "rt_idx_min_daily",
    "rt_fut_min_daily",
)
REQUIRED_PARENT_COMMIT = "2abcd7f"
_VALID_REQUESTS = set()
REPO = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def seed_requests(root, seeds_path, expected_sha):
    """Only frozen actual source rows; values are not accepted on assertion alone."""
    from datetime import datetime, timezone, timedelta
    from backend.shared.tushare_pipeline import manifest_at
    from backend.shared.tushare_realtime_extra_contracts import CODE_PATTERNS

    if seeds_path.is_symlink() or seeds_path.stat().st_size > 1024 * 1024:
        raise ValueError("Unsafe/oversized seed recipe")
    body = seeds_path.read_bytes()
    if (
        seeds_path.is_symlink()
        or len(body) > 1024 * 1024
        or hashlib.sha256(body).hexdigest() != expected_sha
    ):
        raise ValueError("Invalid frozen seed recipe")
    recipe = json.loads(body)
    if (
        set(recipe) != {"release_id", "sources", "calendar"}
        or set(recipe["sources"]) != {"stock", "etf", "index", "sw", "future"}
        or set(recipe["calendar"])
        != {"observation", "recent", "history_start", "history_end"}
    ):
        raise ValueError("Unexpected seed recipe keys")
    if any(
        set(choice) != {"observation", "value"} for choice in recipe["sources"].values()
    ):
        raise ValueError("Unexpected source recipe keys")
    manifest = manifest_at(root, recipe["release_id"])
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()

    def checked(name):
        if not re.fullmatch(r"(objects|observations)/[a-f0-9]{32,64}\.json", name):
            raise ValueError("Invalid source path")
        path = root / name
        expected = manifest["files"][name]
        if (
            path.is_symlink()
            or path.parent.is_symlink()
            or path.stat().st_size > 32 * 1024 * 1024
        ):
            raise ValueError("Unsafe/oversized source file")
        raw = path.read_bytes()
        if (
            len(raw) != expected["bytes"]
            or hashlib.sha256(raw).hexdigest() != expected["sha256"]
        ):
            raise ValueError("Source is outside fixed verified evidence")
        return json.loads(raw)

    allowed = {
        "stock": ("stock_basic", "ts_code", "stocks"),
        "etf": ("etf_basic", "ts_code", "etfs"),
        "index": ("index_basic", "ts_code", "indexes"),
        "sw": ("index_classify", "index_code", "sw_indexes"),
        "future": ("fut_basic", "ts_code", "minute_futures"),
    }
    values = {}
    for family, (api, field, pattern) in allowed.items():
        choice = recipe["sources"][family]
        obs = checked("observations/" + choice["observation"])
        if obs["request"]["api_name"] != api:
            raise ValueError("Seed source API mismatch")
        source = checked("objects/" + obs["object_sha256"] + ".json")
        if source.get("code") != 0:
            raise ValueError("Seed response was not successful")
        data = source["data"]
        if len(data["items"]) > 50000:
            raise ValueError("Seed row audit bound")
        rows = [dict(zip(data["fields"], r, strict=True)) for r in data["items"]]
        code = choice["value"]
        if not isinstance(code, str) or not re.fullmatch(CODE_PATTERNS[pattern], code):
            raise ValueError("Seed code not in reviewed source namespace")
        matched = [r for r in rows if r.get(field) == code]
        if not matched:
            raise ValueError("Seed not present in actual source response")
        if family == "stock" and obs["request"]["params"].get("list_status") != "L":
            raise ValueError("Choose a source from a current-listed stock observation")
        if family == "etf" and not code.endswith(".SZ"):
            raise ValueError("This bounded probe uses one actual Shenzhen ETF")
        if family == "future":
            if code.split(".")[0].endswith(("8888", "9999")):
                raise ValueError("No guessed continuous contract")

            def active(row):
                try:
                    return (
                        datetime.strptime(row["list_date"], "%Y%m%d").date()
                        <= today
                        <= datetime.strptime(row["delist_date"], "%Y%m%d").date()
                    )
                except (KeyError, ValueError, TypeError):
                    return False

            if not any(active(row) for row in matched):
                raise ValueError("Actual contract activity dates are unverified")
        values[family] = code
    calendar = recipe["calendar"]
    obs = checked("observations/" + calendar["observation"])
    if obs["request"]["api_name"] != "trade_cal" or obs["request"]["params"].get(
        "exchange"
    ) not in ("SSE", "SZSE"):
        raise ValueError("Auction dates require actual exchange-calendar rows")
    source = checked("objects/" + obs["object_sha256"] + ".json")
    if source.get("code") != 0:
        raise ValueError("Calendar source failed")
    data = source["data"]
    if len(data["items"]) > 50000:
        raise ValueError("Calendar row bound")
    open_days = {
        r.get("cal_date")
        for row in data["items"]
        for r in [dict(zip(data["fields"], row, strict=True))]
        if r.get("is_open") in (1, "1")
    }
    recent, first, last = (
        calendar[k] for k in ("recent", "history_start", "history_end")
    )
    for value in (recent, first, last):
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[0-9]{8}", value)
            or value not in open_days
        ):
            raise ValueError("Auction date missing actual open-calendar evidence")
    rday, left, right = [
        datetime.strptime(v, "%Y%m%d").date() for v in (recent, first, last)
    ]
    if (
        not today - timedelta(days=14) <= rday < today
        or not date(2025, 1, 1) <= left <= right < rday - timedelta(days=7)
        or (right - left).days > 3
    ):
        raise ValueError("Auction sample dates exceed narrow reviewed scope")
    planned = []
    for variant in ({}, {"ts_type": "STK"}, {"ts_type": "ETF"}):
        code = values["etf"] if variant.get("ts_type") == "ETF" else values["stock"]
        planned.append(
            ("stk_auction", {"trade_date": recent, "ts_code": code, **variant})
        )
        planned.append(
            (
                "stk_auction",
                {"start_date": first, "end_date": last, "ts_code": code, **variant},
            )
        )
    for api, params in (
        ("rt_etf_sz_iopv", {"ts_code": values["etf"]}),
        ("rt_idx_k", {"ts_code": values["index"]}),
        ("rt_idx_min", {"ts_code": values["index"], "freq": "1MIN"}),
        ("rt_sw_k", {"ts_code": values["sw"]}),
        ("rt_fut_min", {"ts_code": values["future"], "freq": "1MIN"}),
        ("rt_k", {"ts_code": values["stock"]}),
        ("rt_etf_k", {"ts_code": values["etf"]}),
        ("rt_idx_min_daily", {"ts_code": values["index"], "freq": "1MIN"}),
        ("rt_fut_min_daily", {"ts_code": values["future"], "freq": "1MIN"}),
    ):
        planned.append((api, params))
    assert len(planned) == MAX_REQUESTS and {a for a, _ in planned} == set(APIS)
    _VALID_REQUESTS.clear()
    _VALID_REQUESTS.update(canonical((a, p)) for a, p in planned)
    return planned, recipe


def validate_request(api, params):
    if canonical((api, params)) not in _VALID_REQUESTS or api not in APIS:
        raise ValueError("Request not in frozen actual-source probe plan")
    if api != "stk_auction" and set(params) - {"ts_code", "freq"}:
        raise ValueError("Current-only realtime replay has no date_str/history inputs")


def runtime_guard_preflight():
    """Require the parent's same-day superseded-slot fix, not only API imports."""
    from backend.shared.tushare_registry import realtime_dispatch_status

    moment = datetime(2026, 9, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()
    for api in APIS[1:]:
        family = "realtime_replay" if api.endswith("_daily") else "realtime_extra"
        config = {
            "enable_" + family: True,
            family + "_apis": [api],
            family + "_snapshot_epoch": "20260909T080000Z",
        }
        if (
            realtime_dispatch_status(api, "snapshot-20260909T075900Z", config, moment)
            != "snapshot_superseded"
        ):
            raise ValueError("Parent 2abcd7f current-slot guard is required")
        if (
            realtime_dispatch_status(api, "snapshot-20260909T080000Z", config, moment)
            is not None
        ):
            raise ValueError("Current snapshot slot rejected by installed runtime")


def resolved_gates(db, api, config):
    """Same tier resolver, rollout ceiling and observed quota as Pipeline.next_job."""
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
            account, positive_int(config["rollout_account_rpm"], "rollout account rate")
        )
    cap = resolved_api_rate(
        api,
        contract_for(api),
        config,
        datetime.fromtimestamp(time.time(), timezone.utc),
    )
    interval = config.get("api_min_interval_seconds", {}).get(api, 0)
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
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
    return {
        "account_rpm": account,
        "api_rpm": cap["rpm"],
        "minimum_interval_seconds": interval,
    }


def safe_result(result):
    """Report/attempt metadata only; no response body, message, headers or credentials."""
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
    status = result.get("status")
    if status not in statuses:
        status = "invalid_response"
    out = {"status": status}
    for name in ("row_count", "rate_limit_requests", "rate_limit_window_seconds"):
        value = result.get(name)
        if type(value) is int and value >= 0:
            out[name] = value
    for name in (
        "response_complete",
        "supplier_has_more",
        "history_complete",
        "pit_verified",
    ):
        if type(result.get(name)) is bool or name in result and result[name] is None:
            out[name] = result[name]
    for name in ("api_name", "rate_limit_api"):
        if result.get(name) in APIS:
            out[name] = result[name]
    for name in ("object_sha256", "observation_sha256"):
        if re.fullmatch(r"[a-f0-9]{64}", str(result.get(name, ""))):
            out[name] = result[name]
    if re.fullmatch(r"[a-f0-9]{32}\.json", str(result.get("observation", ""))):
        out["observation"] = result["observation"]
    if result.get("normalization_error"):
        out["normalization_error"] = "normalization_failed_raw_retained"
    part = result.get("parquet")
    if (
        isinstance(part, dict)
        and re.fullmatch(r"parquet/[a-f0-9]{64}\.parquet", str(part.get("path", "")))
        and re.fullmatch(r"[a-f0-9]{64}", str(part.get("sha256", "")))
        and type(part.get("bytes")) is int
    ):
        out["parquet"] = {k: part[k] for k in ("path", "sha256", "bytes")}
    # Source field names/counts are re-derived by the fixed verifier from raw;
    # omit arbitrary provider keys/text from this operator-facing report.
    return out


class DeferredCommit:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, name):
        return getattr(self.db, name)

    def commit(self):
        pass


def reserve_probe(p, api, params, epoch):
    """Only newly created jobs enter prepared; no schedulable crash window."""
    db = p.db
    db.execute("BEGIN IMMEDIATE")
    try:
        mark = db.execute("SELECT COALESCE(max(rowid),0) FROM jobs").fetchone()[0]
        p.db = DeferredCommit(db)
        key = p.enqueue(api, params, -100, epoch)
        p.db = db
        row = db.execute("SELECT rowid,* FROM jobs WHERE id=?", (key,)).fetchone()
        if row["rowid"] > mark and row["state"] == "pending":
            db.execute("UPDATE jobs SET state='probe_prepared' WHERE id=?", (key,))
        db.commit()
        return key, db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
    except BaseException:
        db.rollback()
        raise
    finally:
        p.db = db


class ProbeDeadline(Exception):
    pass


def collect(p, config, client, token_getter, args):
    from backend.shared.tushare_intake import capture_sample, utc_now
    from backend.shared.tushare_registry import contract_for
    from backend.shared.tushare_pipeline import atomic_json

    # Reject missing/unknown policy before reserving any probe job.
    from backend.shared.tushare_rate_policy import POLICY

    if config.get("rate_policy") != POLICY:
        raise ValueError("Reviewed tiered_v1 policy is required for execution")
    if not 15 <= args.seconds <= MAX_SECONDS:
        raise ValueError("Invalid finite deadline")
    reports = []
    calls = 0
    stopped_apis = set()
    token = None
    stop = None
    runtime_guard_preflight()
    planned, source_seeds = seed_requests(p.root, args.seeds, args.seeds_sha256)
    if args.report.exists():
        raise ValueError("Fresh report required; no hidden resume")

    deadline = time.monotonic() + args.seconds

    def checkpoint():
        report = {
            "epoch": args.epoch,
            "updated_at": utc_now(),
            "actual_upstream_calls": calls,
            "max_requests": MAX_REQUESTS,
            "call_count_semantics": "HTTP attempts including uncertainty; explicit local no-HTTP guards excluded",
            "deadline_seconds": args.seconds,
            "results": reports,
            "stop_reason": stop,
            "helper_sha256": args.helper_sha256,
            "planned_requests": [{"api_name": a, "params": b} for a, b in planned],
            "unattempted_requests": [
                {"api_name": a, "params": b}
                for a, b in planned
                if not any(r["api_name"] == a and r["params"] == b for r in reports)
            ],
            "source_seeds": source_seeds,
            "seeds_sha256": args.seeds_sha256,
            "automatic_activation_permitted": False,
            "required_parent_commit": REQUIRED_PARENT_COMMIT,
            "per_api_max_requests": {
                api: 6 if api == "stk_auction" else 1 for api in APIS
            },
            "snapshot_slot": args.epoch.removeprefix("snapshot-"),
            "frequencies_tested": ["1MIN"],
            "replay_scope": "current_only",
            "publication_required": True,
            "release_id": None,
            "enable_performed": False,
            "configuration_changed": False,
            "history_complete": False,
            "pit_verified": False,
            "deadline_note": "Network and normalization stop at the total deadline; a final durable checkpoint is still allowed.",
        }
        atomic_json(args.report, report)
        return report

    def expire(signum, frame):
        raise ProbeDeadline("finite probe deadline")

    previous = signal.signal(signal.SIGALRM, expire)
    try:
        for api, params in planned:
            if time.monotonic() + 1 >= deadline:
                stop = "total_deadline"
                break
            validate_request(api, params)
            if api in stopped_apis:
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "status": "skipped_same_api_stop",
                    }
                )
                checkpoint()
                continue
            key, row = reserve_probe(p, api, params, args.epoch)
            if row["result"]:
                if json.loads(row["result"]).get("status") in (
                    "permission_denied",
                    "rate_limited",
                ):
                    stopped_apis.add(api)
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "job_id": key,
                        "cached": True,
                        **safe_result(json.loads(row["result"])),
                    }
                )
                checkpoint()
                continue
            # Known denial is not overridden by an ad hoc capability probe.
            denied = p.db.execute(
                "SELECT 1 FROM capability WHERE scope IN (?,?) AND status='permission_denied'",
                (api, api + ":"),
            ).fetchone()
            if denied:
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "status": "skipped_cached_permission_denied",
                    }
                )
                checkpoint()
                continue
            if row["state"] not in ("probe_prepared",):
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "job_id": key,
                        "status": "skipped_uncertain_prior_request"
                        if row["state"] == "probe_inflight"
                        else "skipped_existing_nonpending_job",
                        "prior_state": row["state"],
                    }
                )
                checkpoint()
                continue
            gate = (
                p.db.execute(
                    "SELECT MAX(next_at) FROM request_gates WHERE scope IN (?,?)",
                    ("account", "api:" + api),
                ).fetchone()[0]
                or 0
            )
            delay = max(0, gate - time.time(), row["retry_after"] - time.time())
            if time.monotonic() + delay + 13 >= deadline:
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "job_id": key,
                        "status": "deferred_cached_gate",
                        "retry_after": gate,
                    }
                )
                checkpoint()
                continue  # Other APIs may remain available.
            if delay:
                time.sleep(delay)
            rates = resolved_gates(p.db, api, config)
            account, rpm, interval = (
                rates["account_rpm"],
                rates["api_rpm"],
                rates["minimum_interval_seconds"],
            )
            now = time.time()
            p.db.executemany(
                "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                [
                    ("account", now + 60 / account),
                    ("api:" + api, now + max(60 / rpm, interval)),
                ],
            )
            p.db.commit()  # Reserve the same durable account/API gates before I/O.
            from backend.shared.tushare_registry import realtime_dispatch_status

            guarded_config = {
                **config,
                "enable_realtime_extra": True,
                "enable_realtime_replay": True,
                "realtime_extra_apis": [
                    a for a in APIS if a != "stk_auction" and not a.endswith("_daily")
                ],
                "realtime_replay_apis": ["rt_idx_min_daily", "rt_fut_min_daily"],
                "realtime_extra_snapshot_epoch": args.epoch.removeprefix("snapshot-"),
                "realtime_replay_snapshot_epoch": args.epoch.removeprefix("snapshot-"),
            }
            rejected = realtime_dispatch_status(
                api, row["epoch"], guarded_config, time.time()
            )
            if rejected:
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "status": rejected,
                        "job_id": key,
                    }
                )
                checkpoint()
                continue
            if token is None:
                token = token_getter()
            if not token:
                raise ValueError("missing provider credential")
            job = json.loads(row["job"])
            required = set(contract_for(api)["required_fields"])
            if not required <= set(job["fields"].split(",")):
                raise ValueError("Missing complete known request fields")
            if calls >= MAX_REQUESTS:
                raise ValueError("Finite call budget exceeded")
            # A request may reach the provider even if capture persistence fails.
            # Preserve uncertainty durably before HTTP; never consume a trial again
            # automatically after an interrupted/unknown prior attempt.
            p.db.execute("UPDATE jobs SET state='probe_inflight' WHERE id=?", (key,))
            p.db.commit()
            calls += 1
            signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic()))
            try:
                result = capture_sample(client, token, job, p.root)
            except ProbeDeadline:
                result = {
                    "api_name": api,
                    "status": "transport_error",
                    "response_complete": False,
                    "probe_error": "deadline_without_complete_capture",
                }
                stop = "total_deadline"
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            if result.get("row_count", 0):
                signal.setitimer(
                    signal.ITIMER_REAL, max(0.01, deadline - time.monotonic())
                )
                try:
                    result = p.normalize(result)
                except ProbeDeadline:
                    result["normalization_error"] = "ProbeDeadline"
                    stop = "deadline_during_normalization_raw_retained"
                except Exception as exc:
                    result["normalization_error"] = type(exc).__name__
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
            if result.get("local_daily_quota") and result.get("upstream_calls") == 0:
                calls -= 1
                stopped_apis.add(api)
                p.db.execute(
                    "UPDATE jobs SET state='probe_prepared' WHERE id=?", (key,)
                )
                p.db.commit()
                reports.append(
                    {
                        "api_name": api,
                        "params": params,
                        "job_id": key,
                        "status": "deferred_local_daily_quota",
                        "upstream_calls": 0,
                    }
                )
                checkpoint()
                continue
            result = safe_result(result)
            status = result["status"]
            if status in ("permission_denied", "rate_limited"):
                stopped_apis.add(api)
            state = (
                "done"
                if status == "sample_ok"
                else "empty"
                if status == "empty_unverified"
                else "blocked"
            )
            if result.get("normalization_error"):
                state = "quality"
            # Never enqueue retries or saturation children from this finite probe.
            p.db.execute(
                "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
                (key, row["tries"] + 1, json.dumps(result)),
            )
            p.db.execute(
                "UPDATE jobs SET state=?,result=?,tries=tries+1 WHERE id=?",
                (state, json.dumps(result), key),
            )
            if status == "permission_denied":
                p.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'permission_denied',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (api + ":", utc_now(), "finite_realtime10_probe_denied"),
                )
            if status == "rate_limited":
                scoped = result.get("rate_limit_api") == api
                scope = "api:" + api if scoped else "account"
                cooldown = result.get("rate_limit_window_seconds", 60) if scoped else 60
                p.db.execute(
                    "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                    (scope, time.time() + cooldown),
                )
                if scoped and result.get("rate_limit_requests"):
                    reason = {
                        "interval_seconds": cooldown / result["rate_limit_requests"],
                        "window_seconds": cooldown,
                        "requests": result["rate_limit_requests"],
                    }
                    p.db.execute(
                        "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'rate_limit_observed',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                        ("quota:" + api, utc_now(), json.dumps(reason)),
                    )
            p.db.commit()
            reports.append(
                {
                    "api_name": api,
                    "params": params,
                    "job_id": key,
                    "cached": False,
                    **result,
                }
            )
            checkpoint()
            if stop:
                break
    except BaseException as exc:
        stop = "probe_interrupted:" + type(exc).__name__
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        final = checkpoint()
        token = None
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--root", type=Path, default=Path("/data/tushare"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--seeds-sha256", required=True)
    parser.add_argument("--seconds", type=int, default=120)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Default: immutable source validation only",
    )
    args = parser.parse_args()
    args.helper_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not 15 <= args.seconds <= MAX_SECONDS:
        parser.error("invalid finite deadline")
    sys.path[:0] = [str(args.repo), sysconfig.get_paths()["purelib"]]
    from backend.shared.tushare_registry import contract_for

    runtime_guard_preflight()
    planned, source_seeds = seed_requests(args.root, args.seeds, args.seeds_sha256)
    for api, params in planned:
        validate_request(api, params)
        if contract_for(api).get("group") not in (
            "realtime_auction",
            "realtime_extra",
            "realtime_replay",
        ):
            parser.error("reviewed realtime runtime is not installed")
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "actual_upstream_calls": 0,
                    "planned_requests": planned,
                    "source_seeds": source_seeds,
                    "max_requests": MAX_REQUESTS,
                    "comparison_selection": "6 dated auction variants plus9 current single-code requests; no retries/fanout/prior day or completeness inference",
                    "helper_sha256": args.helper_sha256,
                    "snapshot_slot": None,
                    "required_parent_commit": REQUIRED_PARENT_COMMIT,
                }
            )
        )
        return
    if args.report.exists():
        raise ValueError(
            "Use a new explicit report for a fresh bounded slot; no overwrite or hidden resume"
        )
    import httpx
    from backend.shared.tushare_pipeline import ROOT, Pipeline, authority
    from backend.shared.runtime_secrets import get_secret

    authority()
    if args.root.resolve() != ROOT.resolve() or args.root.resolve() != Path(
        "/data/tushare"
    ):
        raise ValueError("existing authority root required")
    if not args.report.resolve().is_relative_to(ROOT / "validation"):
        raise ValueError("probe report must stay under authority validation")
    if (
        not (ROOT / "pipeline.lock").is_file()
        or not (ROOT / "pipeline.sqlite").is_file()
    ):
        raise ValueError("existing authority queue required")
    with (ROOT / "pipeline.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with sqlite3.connect(
            "file:" + str(ROOT / "pipeline.sqlite") + "?mode=ro", uri=True
        ) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Expected installed schema6; no migration")
        p = Pipeline(
            ROOT, json.loads((args.repo / "config/tushare-catalog.json").read_bytes())
        )
        try:
            config = json.loads((ROOT / "pipeline-config.json").read_bytes())
            args.epoch = "snapshot-" + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ"
            )
            with httpx.Client(
                trust_env=False, timeout=12, follow_redirects=False
            ) as client:
                report = collect(
                    p, config, client, lambda: get_secret("TUSHARE_TOKEN"), args
                )
        finally:
            p.close()
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
        # Never print exception messages originating in provider/network responses.
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
