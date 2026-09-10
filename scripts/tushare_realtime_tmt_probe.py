#!/usr/bin/env python3
"""Bounded realtime/TMT permission, schema and filter probe; dry-run by default."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import signal
import sys
import sysconfig
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import tushare_offcatalog_probe as common  # noqa: E402
from scripts import tushare_realtime_probe as realtime_seed  # noqa: E402

APIS = (
    "rt_min",
    "rt_etf_min",
    "rt_etf_min_daily",
    "tmt_twincome",
    "tmt_twincomedetail",
)
TMT_BASE_REQUESTS = (
    (
        "tmt_twincome",
        {"item": "8", "start_date": "20160201", "end_date": "20180731"},
    ),
    (
        "tmt_twincomedetail",
        {
            "item": "8",
            "symbol": "6156",
            "start_date": "20180701",
            "end_date": "20180731",
        },
    ),
)
FILTER_APIS = {"tmt_twincome", "tmt_twincomedetail"}
MAX_REQUESTS = 7
MAX_SECONDS = 120
REQUIRED_PARENT_COMMIT = "bec7e6aa"
DEPENDENCY_SHA256 = {
    "scripts/tushare_offcatalog_probe.py": (
        "0223e87455e5d519a7ef130e3566d44cc0cb1dd2efef22c351b1aaf70873d2ac"
    ),
    "scripts/tushare_realtime_probe.py": (
        "da5eb7dfb40ba7347a98920e1845a9898caaf7437e9c469ccf94a07607e9933c"
    ),
}
EXPECTED_CONTRACT_SHA256 = (
    "ca31a23b98aaa68ea168f87d280144157fc79d1f4510fbcd4120f238a35464c3"
)
_VALID_BASE_REQUESTS = set()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def dependency_evidence():
    evidence = {}
    for name, expected in DEPENDENCY_SHA256.items():
        actual = hashlib.sha256((REPO / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Reviewed probe dependency changed")
        evidence[name] = actual
    return evidence


def contract_evidence():
    from backend.shared.tushare_offcatalog_contracts import (
        FIELDS as TMT_FIELDS,
        INPUT_FIELDS as TMT_INPUTS,
        OFFCATALOG_CONTRACTS,
    )
    from backend.shared.tushare_realtime_extra_contracts import (
        REALTIME_EXTRA_CONTRACTS,
    )
    from backend.shared.tushare_realtime_replay_contracts import (
        REALTIME_REPLAY_CONTRACTS,
    )
    from backend.shared.tushare_registry import contract_for

    evidence = {}
    specs = {
        "rt_min": REALTIME_EXTRA_CONTRACTS["rt_min"],
        "rt_etf_min": REALTIME_EXTRA_CONTRACTS["rt_etf_min"],
        "rt_etf_min_daily": REALTIME_REPLAY_CONTRACTS["rt_etf_min_daily"],
        "tmt_twincome": OFFCATALOG_CONTRACTS["tmt_twincome"],
        "tmt_twincomedetail": OFFCATALOG_CONTRACTS["tmt_twincomedetail"],
    }
    for api in APIS:
        spec = specs[api]
        runtime = contract_for(api)
        inputs = TMT_INPUTS[api] if api in FILTER_APIS else list(spec["allowed_params"])
        fields = TMT_FIELDS[api] if api in FILTER_APIS else list(spec["fields"])
        expected_group = (
            "offcatalog"
            if api in FILTER_APIS
            else "realtime_replay"
            if api.endswith("_daily")
            else "realtime_extra"
        )
        if (
            runtime.get("group") != expected_group
            or spec.get("default_enabled", False) is not False
            or spec["permission_status"] != "unprobed"
            or list(spec["requested_fields"]) != fields
            or not re.fullmatch(r"[a-f0-9]{64}", spec["source_html_sha256"])
        ):
            raise ValueError("Reviewed realtime/TMT runtime contract drift")
        evidence[api] = {
            "source_url": spec["source_url"],
            "source_html_sha256": spec["source_html_sha256"],
            "input_fields": inputs,
            "requested_fields": fields,
            "row_cap": spec["row_cap"],
            "row_cap_verified": spec["row_cap_verified"],
            "permission_status_before_probe": spec["permission_status"],
            "minimum_points": spec["minimum_points"],
            "history_gap": spec.get("history_gap"),
            "pit_gap": spec.get("pit_gap", spec.get("timing_gap")),
            "saturation_gap": spec["saturation_gap"],
            "default_enabled": spec.get("default_enabled", False),
        }
    digest = hashlib.sha256(canonical(evidence).encode()).hexdigest()
    if EXPECTED_CONTRACT_SHA256 and digest != EXPECTED_CONTRACT_SHA256:
        raise ValueError("Reviewed realtime/TMT contract evidence changed")
    return evidence


def seed_requests(root, seeds_path, expected_sha):
    """Reuse the reviewed actual-source seed validator; select only stock and ETF."""
    dependency_evidence()
    seed_plan, recipe = realtime_seed.seed_requests(root, seeds_path, expected_sha)
    values = {
        api: params["ts_code"]
        for api, params in seed_plan
        if api in ("rt_k", "rt_etf_k")
    }
    if set(values) != {"rt_k", "rt_etf_k"}:
        raise ValueError("Reviewed stock/ETF seeds missing")
    planned = [
        ("rt_min", {"ts_code": values["rt_k"], "freq": "1MIN"}),
        ("rt_etf_min", {"ts_code": values["rt_etf_k"], "freq": "1MIN"}),
        (
            "rt_etf_min_daily",
            {"ts_code": values["rt_etf_k"], "freq": "1MIN"},
        ),
        *TMT_BASE_REQUESTS,
    ]
    _VALID_BASE_REQUESTS.clear()
    _VALID_BASE_REQUESTS.update(canonical((api, params)) for api, params in planned)
    used_evidence = {
        "release_id": recipe["release_id"],
        "sources": {name: recipe["sources"][name] for name in ("stock", "etf")},
    }
    return planned, used_evidence


def _valid_tmt_item(value):
    return isinstance(value, str) and value in {str(item) for item in range(1, 66)}


def validate_request(api, params, *, dynamic=False):
    if api not in APIS:
        raise ValueError("API outside bounded probe")
    if not dynamic:
        if canonical((api, params)) not in _VALID_BASE_REQUESTS:
            raise ValueError("Request outside fixed actual-source probe plan")
        return
    if api not in FILTER_APIS or not _valid_tmt_item(params.get("item")):
        raise ValueError("Invalid response-derived TMT filter")
    if not re.fullmatch(r"[0-9]{8}", str(params.get("date", ""))):
        raise ValueError("Invalid response-derived TMT date")
    expected = {"date", "item"}
    if api == "tmt_twincomedetail":
        expected.add("symbol")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", str(params.get("symbol", ""))):
            raise ValueError("Invalid response-derived TMT symbol")
    if set(params) != expected:
        raise ValueError("Unexpected response-derived TMT fields")


def filter_request(api, rows):
    """Build one exact filter solely from an immediately preceding raw response."""
    if api not in FILTER_APIS or not rows:
        return None
    for row in sorted(rows, key=canonical):
        item, day = str(row.get("item", "")), str(row.get("date", ""))
        params = {"date": day, "item": item}
        if api == "tmt_twincomedetail":
            symbol = str(row.get("symbol", ""))
            params["symbol"] = symbol
        try:
            validate_request(api, params, dynamic=True)
        except ValueError:
            continue
        return params
    return None


def assess_filter(params, base_rows, filtered_rows):
    if filtered_rows is None:
        return {"status": "filter_response_unavailable", "row_count": None}
    matches = all(
        str(row.get(field)) == value
        for row in filtered_rows
        for field, value in params.items()
    )
    base = {canonical(row) for row in base_rows or []}
    subset = all(canonical(row) in base for row in filtered_rows)
    return {
        "status": (
            "filter_match_observed"
            if filtered_rows and matches
            else "empty_filter_unverified"
            if not filtered_rows
            else "filter_mismatch"
        ),
        "row_count": len(filtered_rows),
        "all_rows_match_requested_filter": matches,
        "returned_rows_subset_of_base_observation": subset,
    }


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
    for name in ("row_count", "rate_limit_requests", "rate_limit_window_seconds"):
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
    if result.get("api_name") in APIS:
        out["api_name"] = result["api_name"]
    if result.get("rate_limit_api") in APIS:
        out["rate_limit_api"] = result["rate_limit_api"]
    for name in ("object_sha256", "observation_sha256"):
        if re.fullmatch(r"[a-f0-9]{64}", str(result.get(name, ""))):
            out[name] = result[name]
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


class ProbeDeadline(Exception):
    pass


def collect(pipeline, config, client, token_getter, args):
    from backend.shared.tushare_intake import capture_sample, utc_now
    from backend.shared.tushare_pipeline import atomic_json

    if args.report.exists():
        raise ValueError("Fresh bounded report required")
    if config.get("rate_policy") != "tiered_v1":
        raise ValueError("Reviewed tiered_v1 policy is required")
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
            "dependency_sha256": dependency_evidence(),
            "seeds_sha256": args.seeds_sha256,
            "source_seeds": args.source_seeds,
            "contract_evidence": contracts,
            "base_requests": [
                {"api_name": api, "params": params}
                for api, params in args.planned_requests
            ],
            "dynamic_filter_apis": sorted(FILTER_APIS),
            "per_api_max_requests": {
                api: 2 if api in FILTER_APIS else 1 for api in APIS
            },
            "frequencies_tested": ["1MIN"],
            "realtime_scope": "current_only_actual_fixed_source_codes",
            "tmt_scope": "official item8 examples; aggregate <=30 months; detail one month; exact followups from raw rows",
            "automatic_activation_permitted": False,
            "configuration_changed": False,
            "enable_performed": False,
            "history_complete": False,
            "pit_verified": False,
            "publication_required": True,
            "required_parent_commit": REQUIRED_PARENT_COMMIT,
        }
        atomic_json(args.report, report)
        return report

    def expire(signum, frame):
        raise ProbeDeadline()

    def request(api, params, phase, dynamic=False):
        nonlocal calls, stop, token
        if calls >= MAX_REQUESTS or time.monotonic() + 1 >= deadline:
            stop = "request_limit" if calls >= MAX_REQUESTS else "total_deadline"
            return None, None
        validate_request(api, params, dynamic=dynamic)
        key, row = common.reserve_probe(pipeline, api, params, args.epoch)
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
        account, rpm, interval = common.resolved_gates(pipeline.db, api, config)
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
        rows = common.source_rows(pipeline.root, result)
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
                (api + ":", utc_now(), "finite_realtime_tmt_probe_denied"),
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
        for api, params in args.planned_requests:
            result, rows = request(api, params, "base")
            if stop:
                break
            if api not in FILTER_APIS or result is None:
                continue
            followup = filter_request(api, rows)
            if not followup:
                reports[-1]["filter_followup"] = "not_planned_no_valid_source_row"
                checkpoint()
                continue
            filtered_result, filtered_rows = request(
                api, followup, "actual_row_filter", dynamic=True
            )
            if filtered_result is not None:
                reports[-1]["filter_assessment"] = assess_filter(
                    followup, rows, filtered_rows
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
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.helper_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not 15 <= args.seconds <= MAX_SECONDS:
        parser.error("invalid finite deadline")
    if args.repo.resolve() != REPO.resolve():
        parser.error("repo must be the checkout containing this reviewed helper")
    sys.path[:0] = [str(REPO), sysconfig.get_paths()["purelib"]]
    contracts = contract_evidence()
    planned, source_seeds = seed_requests(args.root, args.seeds, args.seeds_sha256)
    for api, params in planned:
        validate_request(api, params)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "actual_upstream_calls": 0,
                    "base_requests": planned,
                    "dynamic_filter_apis": sorted(FILTER_APIS),
                    "max_requests": MAX_REQUESTS,
                    "deadline_seconds": args.seconds,
                    "helper_sha256": args.helper_sha256,
                    "dependency_sha256": dependency_evidence(),
                    "source_seeds": source_seeds,
                    "contract_evidence": contracts,
                    "authority_accessed_read_only_for_fixed_seeds": True,
                    "token_accessed": False,
                }
            )
        )
        return
    if args.expected_helper_sha256 != args.helper_sha256:
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
        common.require_schema6(db_path)
        pipeline = Pipeline(
            ROOT, json.loads((args.repo / "config/tushare-catalog.json").read_bytes())
        )
        try:
            config = json.loads((ROOT / "pipeline-config.json").read_bytes())
            args.epoch = "snapshot-" + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ"
            )
            args.planned_requests = planned
            args.source_seeds = source_seeds
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
