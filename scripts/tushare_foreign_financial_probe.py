#!/usr/bin/env python3
"""Probe eight HK/US financial permissions once; dry-run by default."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import sysconfig


APIS = (
    "hk_income",
    "hk_balancesheet",
    "hk_cashflow",
    "hk_fina_indicator",
    "us_income",
    "us_balancesheet",
    "us_cashflow",
    "us_fina_indicator",
)
SEEDS = {"hk": "00700.HK", "us": "AAPL"}
WINDOW = {"start_date": "20240101", "end_date": "20241231"}
MAX_REQUESTS = len(APIS)
MAX_SECONDS = 120
REPO = Path(__file__).resolve().parents[1]
SAFE_STATUSES = {
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


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def planned_requests():
    return [
        {
            "api_name": api,
            "params": {
                "ts_code": SEEDS["hk" if api.startswith("hk_") else "us"],
                **WINDOW,
            },
        }
        for api in APIS
    ]


def contract_evidence():
    from backend.shared.tushare_foreign_financial_contracts import (
        FOREIGN_FINANCIAL_CONTRACTS,
        INPUT_FIELDS,
    )
    from backend.shared.tushare_registry import contract_for

    evidence = {}
    for request in planned_requests():
        api, params = request["api_name"], request["params"]
        spec = FOREIGN_FINANCIAL_CONTRACTS.get(api)
        if (
            not spec
            or contract_for(api).get("group") != "foreign_financial"
            or spec.get("permission_status") != "unprobed"
            or spec.get("documented_requests_per_minute") != 500
            or spec.get("requests_per_minute") != 50
            or spec.get("row_cap") not in (200, 10000)
            or spec.get("dependencies")
            != (["hk_stocks"] if api.startswith("hk_") else ["us_stocks"])
            or not set(params).issubset(INPUT_FIELDS[api])
            or not re.fullmatch(
                r"https://tushare\.pro/document/2\?doc_id=[0-9]+",
                str(spec.get("source_url", "")),
            )
        ):
            raise ValueError("Foreign financial contract drift")
        evidence[api] = {
            "source_url": spec["source_url"],
            "dependency": spec["dependencies"][0],
            "row_cap": spec["row_cap"],
            "documented_requests_per_minute": 500,
            "configured_conservative_requests_per_minute": 50,
            "permission_status_before_probe": "unprobed",
        }
    return evidence


def contract_sha256(evidence=None):
    return hashlib.sha256(canonical(evidence or contract_evidence()).encode()).hexdigest()


def safe_result(result):
    result = result if isinstance(result, dict) else {}
    output = {
        "status": (
            result.get("status")
            if result.get("status") in SAFE_STATUSES
            else "invalid_response"
        )
    }
    for name in (
        "row_count",
        "http_status",
        "code",
        "rate_limit_requests",
        "rate_limit_window_seconds",
    ):
        if type(result.get(name)) is int:
            output[name] = result[name]
    for name in (
        "response_complete",
        "supplier_has_more",
        "history_complete",
        "pit_verified",
    ):
        if type(result.get(name)) is bool or result.get(name) is None and name in result:
            output[name] = result[name]
    if result.get("field_coverage") in (
        "complete_for_explicit_request",
        "optional_gap",
        "gap",
        "unverified_default_or_invalid",
    ):
        output["field_coverage"] = result["field_coverage"]
    for name in (
        "requested_missing_fields",
        "optional_requested_missing_fields",
        "unexpected_returned_fields",
    ):
        fields = result.get(name)
        if (
            isinstance(fields, list)
            and len(fields) <= 512
            and all(isinstance(field, str) and re.fullmatch(r"[A-Za-z0-9_]+", field) for field in fields)
        ):
            output[name] = fields
    if result.get("api_name") in APIS:
        output["api_name"] = result["api_name"]
    for name in ("object_sha256", "observation_sha256"):
        if re.fullmatch(r"[a-f0-9]{64}", str(result.get(name, ""))):
            output[name] = result[name]
    if re.fullmatch(r"[a-f0-9]{32}\.json", str(result.get("observation", ""))):
        output["observation"] = result["observation"]
    parquet = result.get("parquet")
    if isinstance(parquet, dict) and re.fullmatch(
        r"parquet/[a-f0-9]{64}\.parquet", str(parquet.get("path", ""))
    ):
        output["parquet"] = {
            name: parquet[name] for name in ("path", "sha256", "bytes")
        }
    if result.get("normalization_error"):
        output["normalization_error"] = "normalization_failed_raw_retained"
    return output


def require_schema6(db_path):
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Existing pipeline schema v6 required")


def seed_evidence(db):
    row = db.execute(
        "SELECT version,result FROM identifier_discovery_cache "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row or row[0] != 4:
        raise ValueError("Identifier discovery cache v4 required")
    identifiers = json.loads(row[1])
    checks = {
        "hk_stocks": SEEDS["hk"] in identifiers.get("hk_stocks", ()),
        "us_stocks": SEEDS["us"] in identifiers.get("us_stocks", ()),
    }
    if not all(checks.values()):
        raise ValueError("Reviewed foreign financial seed is absent from discovery")
    return {
        "identifier_cache_version": 4,
        "hk_stock_count": len(identifiers["hk_stocks"]),
        "us_stock_count": len(identifiers["us_stocks"]),
        "seed_presence": checks,
    }


def reserve_jobs(pipeline, epoch):
    task_ids = []
    for request in planned_requests():
        task_id = pipeline.enqueue(
            request["api_name"], request["params"], priority=-100, epoch=epoch
        )
        task_ids.append(task_id)
        pipeline.db.execute(
            "UPDATE jobs SET state='pending',retry_after=0 WHERE id=?", (task_id,)
        )
    if len(task_ids) != MAX_REQUESTS or len(set(task_ids)) != MAX_REQUESTS:
        raise ValueError("Probe task identity collision")
    pipeline.db.commit()
    return task_ids


def result_rows(pipeline, task_ids):
    rows = []
    for task_id in task_ids:
        row = pipeline.db.execute(
            "SELECT job,state,tries,result FROM jobs WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Probe task disappeared")
        job = json.loads(row["job"])
        rows.append(
            {
                "task_id": task_id,
                "api_name": job["api_name"],
                "params": job["params"],
                "state": row["state"],
                "tries": row["tries"],
                "result": safe_result(json.loads(row["result"]))
                if row["result"]
                else None,
            }
        )
    return rows


def execute(args):
    os.environ["QM_TUSHARE_ARCHIVE_ROOT"] = str(args.root.resolve())
    os.environ["QM_NODE_ROLE"] = "archive"
    sys.path[:0] = [str(REPO), sysconfig.get_paths()["purelib"]]

    import httpx
    from backend.shared.runtime_secrets import get_secret
    from backend.shared.tushare_pipeline import ROOT, Pipeline, atomic_json, authority, utc_now

    authority()
    root = args.root.resolve()
    report_path = args.report.resolve()
    validation = (root / "validation").resolve()
    if root != ROOT.resolve() or not report_path.is_relative_to(validation):
        raise ValueError("Existing archive root and validation report are required")
    if report_path.exists() or report_path.is_symlink():
        raise ValueError("Fresh probe report required")
    validation.mkdir(parents=True, exist_ok=True)
    db_path = root / "pipeline.sqlite"
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("Existing authority queue required")
    for lock_name in (".archive-worker.lock", "pipeline.lock"):
        lock_path = root / lock_name
        if lock_path.is_symlink() or not lock_path.is_file():
            raise ValueError("Existing authority locks required")

    with (root / ".archive-worker.lock").open("r+") as worker_lock:
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (root / "pipeline.lock").open("r+") as pipeline_lock:
            fcntl.flock(pipeline_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require_schema6(db_path)
            config = json.loads((root / "pipeline-config.json").read_bytes())
            if (
                config.get("rate_policy") != "tiered_v1"
                or config.get("enable_foreign_financial") is not False
                or config.get("foreign_financial_apis") != []
            ):
                raise ValueError("Reviewed disabled foreign financial config required")
            catalog = json.loads(
                (args.repo / "config/tushare-catalog.json").read_bytes()
            )
            pipeline = Pipeline(root, catalog)
            try:
                seeds = seed_evidence(pipeline.db)
                epoch = "permission-foreign-financial-" + datetime.now(
                    timezone.utc
                ).strftime("%Y%m%dT%H%M%S%fZ")
                task_ids = reserve_jobs(pipeline, epoch)
                probe_config = {
                    **config,
                    "acquisition_pipeline_depth": 1,
                    "acquisition_capture_execution": "thread",
                    "acquisition_capture_workers": 1,
                }
                token = get_secret("TUSHARE_TOKEN")
                if not token:
                    raise ValueError("Missing provider credential")
                with httpx.Client(
                    trust_env=False, timeout=20, follow_redirects=False
                ) as client:
                    run = pipeline.run(
                        client,
                        token,
                        probe_config,
                        max_requests=MAX_REQUESTS,
                        max_seconds=args.seconds,
                        pause=0,
                        task_ids=task_ids,
                    )
                token = None
                rows = result_rows(pipeline, task_ids)
                statuses = {
                    row["api_name"]: (
                        row["result"]["status"] if row["result"] else row["state"]
                    )
                    for row in rows
                }
                available = sorted(
                    api
                    for api in APIS
                    if (
                        pipeline.db.execute(
                            "SELECT status FROM capability WHERE scope=?", (api + ":",)
                        ).fetchone()
                        or (None,)
                    )[0]
                    == "available"
                )
                activation_candidates = sorted(
                    api
                    for api, status in statuses.items()
                    if status in ("sample_ok", "empty_unverified")
                )
                report = {
                    "schema_version": 1,
                    "authority_schema_version": 6,
                    "probe": "foreign_financial_permissions",
                    "epoch": epoch,
                    "completed_at": utc_now(),
                    "helper_sha256": args.helper_sha256,
                    "contract_sha256": args.contract_sha256,
                    "contract_evidence": args.contracts,
                    "seed_evidence": seeds,
                    "max_requests": MAX_REQUESTS,
                    "deadline_seconds": args.seconds,
                    "actual_upstream_calls": run["requests"],
                    "exact_task_scope": run.get("exact_task_scope") is True,
                    "results": rows,
                    "permission_available_apis": available,
                    "activation_candidates": activation_candidates,
                    "automatic_activation_permitted": False,
                    "configuration_changed": False,
                    "full_history_planned": False,
                    "secret_persisted": False,
                }
                atomic_json(report_path, report)
            finally:
                pipeline.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "Library/Application Support/QuantMind/tushare",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--seconds", type=int, default=MAX_SECONDS)
    parser.add_argument("--expected-helper-sha256")
    parser.add_argument("--expected-contract-sha256")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.helper_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not 15 <= args.seconds <= MAX_SECONDS:
        parser.error("invalid finite deadline")
    if args.repo.resolve() != REPO.resolve():
        parser.error("repo must be the checkout containing this reviewed helper")
    sys.path[:0] = [str(REPO), sysconfig.get_paths()["purelib"]]
    args.contracts = contract_evidence()
    args.contract_sha256 = contract_sha256(args.contracts)
    prepared = {
        "status": "prepared_only",
        "actual_upstream_calls": 0,
        "planned_requests": planned_requests(),
        "max_requests": MAX_REQUESTS,
        "deadline_seconds": args.seconds,
        "helper_sha256": args.helper_sha256,
        "contract_sha256": args.contract_sha256,
        "contract_evidence": args.contracts,
        "token_accessed": False,
        "archive_accessed": False,
        "configuration_changed": False,
        "full_history_planned": False,
    }
    if not args.execute:
        print(json.dumps(prepared))
        return
    if args.report is None:
        parser.error("--report is required with --execute")
    if args.expected_helper_sha256 != args.helper_sha256:
        parser.error("execute requires the reviewed helper SHA256")
    if args.expected_contract_sha256 != args.contract_sha256:
        parser.error("execute requires the reviewed contract SHA256")
    report = execute(args)
    print(
        json.dumps(
            {
                "report": str(args.report),
                "actual_upstream_calls": report["actual_upstream_calls"],
                "statuses": {
                    row["api_name"]: (
                        row["result"]["status"] if row["result"] else row["state"]
                    )
                    for row in report["results"]
                },
                "activation_candidates": report["activation_candidates"],
                "configuration_changed": False,
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
