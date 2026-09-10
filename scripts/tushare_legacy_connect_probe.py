#!/usr/bin/env python3
"""Four-call legacy Connect probe; plan-only by default."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import signal
import sqlite3
import sys
import sysconfig
import time

MAX_REQUESTS = 4
MAX_SECONDS = 120
KNOWN_APIS = {"moneyflow_hsgt", "ggt_daily"}
APIS = KNOWN_APIS | {"ggt_top10"}
REPO = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def seed_requests(root, seeds_path, expected_sha):
    """Build the fixed four requests only from a verified trade-calendar object."""
    if seeds_path.is_symlink() or seeds_path.stat().st_size > 1024 * 1024:
        raise ValueError("Unsafe/oversized seed recipe")
    body = seeds_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_sha:
        raise ValueError("Invalid frozen seed recipe")
    recipe = json.loads(body)
    if set(recipe) != {"release_id", "calendar"} or set(recipe["calendar"]) != {
        "observations",
        "recent_start",
        "recent_end",
        "history_start",
        "history_end",
    }:
        raise ValueError("Unexpected seed recipe keys")
    release_id = recipe["release_id"]
    if not isinstance(release_id, str) or not re.fullmatch(r"data-[a-f0-9]{64}", release_id):
        raise ValueError("Invalid fixed release ID")
    manifest_path = root / "releases" / release_id / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 1024**3:
        raise ValueError("Unsafe/oversized fixed manifest")
    manifest_hash = hashlib.sha256()
    with manifest_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            manifest_hash.update(chunk)
    if manifest_hash.hexdigest() != release_id.removeprefix("data-"):
        raise ValueError("Fixed manifest checksum mismatch")
    manifest_stream = manifest_path.open("rb")
    manifest = mmap.mmap(manifest_stream.fileno(), 0, access=mmap.ACCESS_READ)

    def manifest_entry(name):
        token = json.dumps(name, ensure_ascii=False).encode() + b": "
        offset = manifest.find(token)
        if offset < 0 or manifest.find(token, offset + len(token)) >= 0:
            raise ValueError("Source is absent or ambiguous in fixed manifest")
        sample = manifest[offset + len(token) : offset + len(token) + 512].decode()
        entry, _ = json.JSONDecoder().raw_decode(sample)
        if set(entry) != {"bytes", "sha256"}:
            raise ValueError("Unexpected fixed manifest entry")
        return entry

    def checked(name):
        if not re.fullmatch(r"(objects|observations)/[a-f0-9]{32,64}\.json", name):
            raise ValueError("Invalid source path")
        path = root / name
        expected = manifest_entry(name)
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Unsafe/oversized source file")
        raw = path.read_bytes()
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("Source is outside fixed verified evidence")
        return json.loads(raw)

    try:
        calendar = recipe["calendar"]
        values = [calendar[k] for k in ("recent_start", "recent_end", "history_start", "history_end")]
        if set(calendar["observations"]) != set(values):
            raise ValueError("Every reviewed date requires an explicit calendar observation")
        open_days = set()
        for day, name in calendar["observations"].items():
            obs = checked("observations/" + name)
            if obs["request"]["api_name"] != "trade_cal" or obs["request"]["params"].get("exchange") not in ("SSE", "SZSE"):
                raise ValueError("Connect dates require actual exchange-calendar rows")
            source = checked("objects/" + obs["object_sha256"] + ".json")
            if source.get("code") != 0 or len(source.get("data", {}).get("items", [])) > 50000:
                raise ValueError("Invalid calendar source")
            data = source["data"]
            rows = [dict(zip(data["fields"], row, strict=True)) for row in data["items"]]
            if any(r.get("cal_date") == day and r.get("is_open") in (1, "1") for r in rows):
                open_days.add(day)
        if any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{8}", v) or v not in open_days for v in values):
            raise ValueError("Probe date missing actual open-calendar evidence")
    finally:
        manifest.close()
        manifest_stream.close()
    recent_start, recent_end, history_start, history_end = values
    if not recent_start <= recent_end or not history_start <= history_end < recent_start:
        raise ValueError("Invalid bounded Connect date order")
    if (datetime.strptime(recent_end, "%Y%m%d") - datetime.strptime(recent_start, "%Y%m%d")).days > 7:
        raise ValueError("Recent probe range too wide")
    if (datetime.strptime(history_end, "%Y%m%d") - datetime.strptime(history_start, "%Y%m%d")).days > 7:
        raise ValueError("Historical probe range too wide")
    planned = [
        ("moneyflow_hsgt", {"start_date": recent_start, "end_date": recent_end}),
        ("ggt_daily", {"trade_date": recent_end}),
        ("ggt_daily", {"start_date": history_start, "end_date": history_end}),
        ("ggt_top10", {"trade_date": recent_end}),
    ]
    return planned, recipe


def safe_result(result):
    statuses = {
        "sample_ok", "schema_gap", "invalid_values", "possibly_truncated",
        "empty_unverified", "permission_denied", "rate_limited",
        "transport_error", "api_error", "invalid_response",
    }
    out = {"status": result.get("status") if result.get("status") in statuses else "invalid_response"}
    for name in ("row_count", "rate_limit_requests", "rate_limit_window_seconds"):
        if type(result.get(name)) is int and result[name] >= 0:
            out[name] = result[name]
    for name in ("response_complete", "supplier_has_more", "history_complete", "pit_verified"):
        if type(result.get(name)) is bool or name in result and result[name] is None:
            out[name] = result[name]
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
    if isinstance(part, dict) and re.fullmatch(r"parquet/[a-f0-9]{64}\.parquet", str(part.get("path", ""))):
        out["parquet"] = {k: part[k] for k in ("path", "sha256", "bytes")}
    if result.get("normalization_error"):
        out["normalization_error"] = "normalization_failed_raw_retained"
    return out


class DeferredCommit:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, name):
        return getattr(self.db, name)

    def commit(self):
        pass


def reserve_probe(p, api, params, epoch):
    from backend.shared.tushare_intake import digest, json_bytes

    db = p.db
    db.execute("BEGIN IMMEDIATE")
    try:
        mark = db.execute("SELECT COALESCE(max(rowid),0) FROM jobs").fetchone()[0]
        if api in KNOWN_APIS:
            p.db = DeferredCommit(db)
            key = p.enqueue(api, params, -100, epoch)
            p.db = db
        else:
            job = {"api_name": api, "params": params, "fields": "", "row_cap": 1000,
                   "required_fields": [], "nullable_fields": [], "positive_fields": []}
            logical = digest(json_bytes(job))
            key = digest(json_bytes([logical, epoch]))
            db.execute(
                "INSERT OR IGNORE INTO jobs(id,logical_key,epoch,job,priority,state,group_name) VALUES(?,?,?,?,?,'pending','legacy_connect')",
                (key, logical, epoch, json.dumps(job), -100),
            )
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


def resolved_gates(db, api, config):
    from backend.shared.tushare_rate_policy import POLICY, positive_int
    from backend.shared.tushare_registry import contract_for
    from backend.shared.tushare_rate_policy import resolved_api_rate

    if config.get("rate_policy") != POLICY:
        raise ValueError("Reviewed tiered_v1 policy is required")
    account = positive_int(config.get("requests_per_minute"), "account request rate")
    if config.get("rollout_account_rpm") is not None:
        account = min(account, positive_int(config["rollout_account_rpm"], "rollout account rate"))
    rpm = resolved_api_rate(api, contract_for(api), config, datetime.now(timezone.utc))["rpm"] if api in KNOWN_APIS else 30
    interval = config.get("api_min_interval_seconds", {}).get(api, 0)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 <= interval <= 86400:
        raise ValueError("Invalid minimum interval")
    quota = db.execute(
        "SELECT reason FROM capability WHERE scope=? AND status='rate_limit_observed'", ("quota:" + api,)
    ).fetchone()
    if quota:
        observed = json.loads(quota[0])["interval_seconds"]
        if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed < 0:
            raise ValueError("Invalid observed quota interval")
        interval = max(interval, observed)
    return account, rpm, interval


class ProbeDeadline(Exception):
    pass


def collect(p, config, client, token_getter, args):
    from backend.shared.tushare_intake import capture_sample, utc_now
    from backend.shared.tushare_pipeline import atomic_json

    planned, source_seeds = seed_requests(p.root, args.seeds, args.seeds_sha256)
    if len(planned) != MAX_REQUESTS or args.report.exists():
        raise ValueError("Fresh four-request report required")
    reports, stopped_apis, calls, stop, token = [], set(), 0, None, None
    deadline = time.monotonic() + args.seconds

    def checkpoint():
        report = {
            "epoch": args.epoch, "updated_at": utc_now(), "actual_upstream_calls": calls,
            "max_requests": MAX_REQUESTS, "deadline_seconds": args.seconds,
            "results": reports, "stop_reason": stop, "helper_sha256": args.helper_sha256,
            "planned_requests": [{"api_name": a, "params": b} for a, b in planned],
            "source_seeds": source_seeds, "seeds_sha256": args.seeds_sha256,
            "automatic_activation_permitted": False, "configuration_changed": False,
            "history_complete": False, "pit_verified": False, "publication_required": True,
            "raw_only_apis": ["ggt_top10"],
        }
        atomic_json(args.report, report)
        return report

    def expire(signum, frame):
        raise ProbeDeadline()

    previous = signal.signal(signal.SIGALRM, expire)
    try:
        for api, params in planned:
            if time.monotonic() + 1 >= deadline:
                stop = "total_deadline"
                break
            if api in stopped_apis:
                reports.append({"api_name": api, "params": params, "status": "skipped_same_api_stop"})
                checkpoint()
                continue
            key, row = reserve_probe(p, api, params, args.epoch)
            if row["state"] != "probe_prepared":
                reports.append({"api_name": api, "params": params, "job_id": key,
                                "status": "skipped_uncertain_prior_request" if row["state"] == "probe_inflight" else "skipped_existing_nonpending_job"})
                checkpoint()
                continue
            denied = p.db.execute(
                "SELECT 1 FROM capability WHERE scope IN (?,?) AND status='permission_denied'",
                (api, api + ":"),
            ).fetchone()
            if denied:
                reports.append({"api_name": api, "params": params, "job_id": key,
                                "status": "skipped_cached_permission_denied"})
                checkpoint()
                continue
            gate = p.db.execute(
                "SELECT MAX(next_at) FROM request_gates WHERE scope IN (?,?)", ("account", "api:" + api)
            ).fetchone()[0] or 0
            delay = max(0, gate - time.time(), row["retry_after"] - time.time())
            if time.monotonic() + delay + 13 >= deadline:
                reports.append({"api_name": api, "params": params, "job_id": key, "status": "deferred_cached_gate"})
                checkpoint()
                continue
            if delay:
                time.sleep(delay)
            account, rpm, interval = resolved_gates(p.db, api, config)
            now = time.time()
            p.db.executemany(
                "INSERT INTO request_gates(scope,next_at) VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
                [("account", now + 60 / account), ("api:" + api, now + max(60 / rpm, interval))],
            )
            p.db.execute("UPDATE jobs SET state='probe_inflight' WHERE id=?", (key,))
            p.db.commit()
            if token is None:
                token = token_getter()
            if not token:
                raise ValueError("missing provider credential")
            calls += 1
            signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic()))
            try:
                result = capture_sample(client, token, json.loads(row["job"]), p.root)
            except ProbeDeadline:
                result = {"api_name": api, "status": "transport_error", "response_complete": False}
                stop = "total_deadline"
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            if result.get("local_daily_quota") and result.get("upstream_calls") == 0:
                calls -= 1
                stopped_apis.add(api)
                p.db.execute("UPDATE jobs SET state='probe_prepared' WHERE id=?", (key,))
                p.db.commit()
                reports.append({"api_name": api, "params": params, "job_id": key,
                                "status": "deferred_local_daily_quota", "upstream_calls": 0})
                checkpoint()
                continue
            if result.get("row_count", 0) and api in KNOWN_APIS:
                try:
                    result = p.normalize(result)
                except Exception as exc:
                    result["normalization_error"] = type(exc).__name__
            result = safe_result(result)
            status = result["status"]
            if status in ("permission_denied", "rate_limited"):
                stopped_apis.add(api)
            if status == "permission_denied":
                p.db.execute(
                    "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'permission_denied',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                    (api + ":", utc_now(), "finite_legacy_connect_probe_denied"),
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
                    reason = json.dumps({
                        "interval_seconds": cooldown / result["rate_limit_requests"],
                        "window_seconds": cooldown,
                        "requests": result["rate_limit_requests"],
                    })
                    p.db.execute(
                        "INSERT INTO capability(scope,status,checked_at,reason) VALUES(?,'rate_limit_observed',?,?) ON CONFLICT(scope) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,reason=excluded.reason",
                        ("quota:" + api, utc_now(), reason),
                    )
            state = "done" if status in ("sample_ok", "possibly_truncated") else "empty" if status == "empty_unverified" else "blocked"
            if result.get("normalization_error"):
                state = "quality"
            p.db.execute("INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)", (key, row["tries"] + 1, json.dumps(result)))
            p.db.execute("UPDATE jobs SET state=?,result=?,tries=tries+1 WHERE id=?", (state, json.dumps(result), key))
            p.db.commit()
            reports.append({"api_name": api, "params": params, "job_id": key, **result})
            checkpoint()
            if stop:
                break
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
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.helper_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not 15 <= args.seconds <= MAX_SECONDS:
        parser.error("invalid finite deadline")
    sys.path[:0] = [str(args.repo), sysconfig.get_paths()["purelib"]]
    planned, source_seeds = seed_requests(args.root, args.seeds, args.seeds_sha256)
    if not args.execute:
        print(json.dumps({"status": "prepared_only", "actual_upstream_calls": 0,
                          "planned_requests": planned, "source_seeds": source_seeds,
                          "max_requests": MAX_REQUESTS, "helper_sha256": args.helper_sha256}))
        return
    from backend.shared.tushare_pipeline import ROOT, Pipeline, authority
    from backend.shared.runtime_secrets import get_secret
    import httpx

    authority()
    if args.root.resolve() != ROOT.resolve() or not args.report.resolve().is_relative_to(ROOT / "validation"):
        raise ValueError("existing authority root/report required")
    if args.report.exists():
        raise ValueError("Fresh report required")
    with (ROOT / "pipeline.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with sqlite3.connect("file:" + str(ROOT / "pipeline.sqlite") + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Expected installed schema6; no migration")
        p = Pipeline(ROOT, json.loads((args.repo / "config/tushare-catalog.json").read_bytes()))
        try:
            config = json.loads((ROOT / "pipeline-config.json").read_bytes())
            args.epoch = "probe-legacy-connect-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            with httpx.Client(trust_env=False, timeout=12, follow_redirects=False) as client:
                report = collect(p, config, client, lambda: get_secret("TUSHARE_TOKEN"), args)
        finally:
            p.close()
    print(json.dumps({"report": str(args.report), "actual_upstream_calls": report["actual_upstream_calls"],
                      "samples": len(report["results"]), "stop_reason": report["stop_reason"],
                      "publication_required": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2) from None
