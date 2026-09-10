#!/usr/bin/env python3
"""Prepare deterministic Pipeline jobs from an offline RRG ETF audit."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_cross_asset_extra_contracts import (  # noqa: E402
    validate_cross_asset_request,
)
from backend.shared.tushare_pipeline import Pipeline  # noqa: E402
from backend.shared.tushare_rrg_contracts import INPUT_FIELDS  # noqa: E402

POLICY = {
    "fund_div": {
        "gate": "requires_terminal_receipt",
        "priority": 25,
        "epoch": "history",
    },
    "etf_limit": {
        "gate": "collection_candidate",
        "priority": 55,
        "epoch": "history",
    },
    "fund_daily": {
        "gate": "diagnostic_refresh_only",
        "priority": 65,
        "epoch": "history",
    },
}
DEFAULT_APIS = ("fund_div", "etf_limit")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("Invalid date")
    from datetime import datetime

    datetime.strptime(value, "%Y%m%d")
    return value


def validate_candidate(row):
    if not isinstance(row, dict) or set(row) != {
        "api_name",
        "params",
        "gate",
        "reason",
    }:
        raise ValueError("Invalid collection candidate shape")
    api, params = row["api_name"], row["params"]
    if api not in POLICY or row["gate"] != POLICY[api]["gate"]:
        raise ValueError("Collection candidate is not approved by preparation policy")
    if not isinstance(params, dict):
        raise ValueError("Candidate params must be an object")
    if api == "fund_div":
        if set(params) != {"ts_code"} or not re.fullmatch(
            r"[0-9]{6,7}\.(SH|SZ)", str(params.get("ts_code", ""))
        ):
            raise ValueError("Invalid fund_div ETF request")
    elif api == "etf_limit":
        if set(params) != {"start_date", "end_date"}:
            raise ValueError("ETF limit preparation accepts monthly windows only")
        validate_cross_asset_request(api, params)
    else:
        if set(params) != {"ts_code", "start_date", "end_date"}:
            raise ValueError("Invalid fund_daily diagnostic request")
        if set(params) - set(INPUT_FIELDS[api]) or not re.fullmatch(
            r"[0-9]{6,7}\.(SH|SZ)", str(params.get("ts_code", ""))
        ):
            raise ValueError("Invalid fund_daily diagnostic request")
        if _date(params["start_date"]) > _date(params["end_date"]):
            raise ValueError("Reversed diagnostic window")
    return api, params


def validate_dormant(row):
    if not isinstance(row, dict) or set(row) != {
        "api_name",
        "params",
        "gate",
        "reason",
    }:
        raise ValueError("Invalid dormant collection candidate shape")
    api, params = row["api_name"], row["params"]
    if (
        api not in ("etf_sh_cons", "etf_sz_cons")
        or row["gate"] != "blocked_until_authoritative_etf_mapping"
        or not isinstance(params, dict)
        or set(params) != {"ts_code", "start_date", "end_date"}
        or not re.fullmatch(r"[0-9]{6,7}\.(SH|SZ)", str(params.get("ts_code", "")))
        or _date(params["start_date"]) > _date(params["end_date"])
    ):
        raise ValueError("Invalid dormant PCF candidate")
    return api, params


def _source(audit_report, report_sha256):
    report = Path(audit_report).resolve()
    folder = report.parent
    if report.name != "report.json" or sha(report) != report_sha256:
        raise ValueError("Audit report hash mismatch")
    manifest_path, plan_path = folder / "manifest.json", folder / "collection-plan.jsonl"
    manifest = json.loads(manifest_path.read_bytes())
    payload = json.loads(report.read_bytes())
    if (
        payload.get("status") != "blocked_data"
        or payload.get("upstream_calls") != 0
        or payload.get("credentials_accessed") is not False
        or manifest.get("release_id") != payload.get("release_id")
        or manifest.get("status") != "blocked_data"
        or manifest.get("files", {}).get(report.name, {}).get("sha256")
        != report_sha256
        or manifest.get("files", {}).get(plan_path.name, {}).get("sha256")
        != sha(plan_path)
    ):
        raise ValueError("Audit source is not a verified offline blocked-data plan")
    return payload, plan_path, sha(plan_path)


def _output_guard(output, source):
    output, source = Path(output).resolve(), Path(source).resolve()
    if (
        output.exists()
        or output == REPO
        or REPO in output.parents
        or output == source
        or source in output.parents
        or any((parent / ".git").exists() for parent in (output, *output.parents))
    ):
        raise ValueError("Output must be new and outside source/repository trees")
    return output


def _write_shards(output, jobs, shard_size):
    folder = output / "shards"
    folder.mkdir(parents=True)
    inventory = []
    number = 0
    for api in DEFAULT_APIS + ("fund_daily",):
        selected = [row for row in jobs if row["api_name"] == api]
        for offset in range(0, len(selected), shard_size):
            number += 1
            chunk = selected[offset : offset + shard_size]
            path = folder / f"{number:04d}-{api}.jsonl"
            with path.open("w") as target:
                for row in chunk:
                    target.write(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    )
            inventory.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "api_name": api,
                    "rows": len(chunk),
                    "first_task_id": chunk[0]["task_id"],
                    "last_task_id": chunk[-1]["task_id"],
                    "bytes": path.stat().st_size,
                    "sha256": sha(path),
                }
            )
    return inventory


def _prepare(audit_report, report_sha256, output, shard_size, include_diagnostics):
    if type(shard_size) is not int or not 1 <= shard_size <= 1000:
        raise ValueError("Shard size must be between 1 and 1000")
    report, plan_path, plan_sha = _source(audit_report, report_sha256)
    output = _output_guard(output, plan_path.parent)
    selected_apis = set(DEFAULT_APIS)
    if include_diagnostics:
        selected_apis.add("fund_daily")

    candidates, source_counts, excluded_counts, seen = [], {}, {}, set()
    with plan_path.open() as source:
        for line_number, line in enumerate(source, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid collection plan JSONL") from exc
            api = row.get("api_name") if isinstance(row, dict) else None
            source_counts[api] = source_counts.get(api, 0) + 1
            if api in POLICY:
                api, params = validate_candidate(row)
            else:
                api, params = validate_dormant(row)
            if api not in selected_apis:
                excluded_counts[api] = excluded_counts.get(api, 0) + 1
                continue
            identity = json.dumps([api, params], ensure_ascii=False, sort_keys=True)
            if identity in seen:
                raise ValueError("Duplicate selected collection candidate")
            seen.add(identity)
            candidates.append((api, params, line_number))
    if sum(source_counts.values()) != report.get("collection_plan", {}).get("jobs"):
        raise ValueError("Collection plan row count does not match audit report")

    catalog = json.loads((REPO / "config/tushare-catalog.json").read_bytes())
    materialized = []
    with tempfile.TemporaryDirectory(prefix="rrg-acquisition-identity-") as temporary:
        pipeline = Pipeline(temporary, catalog)
        try:
            for api, params, line_number in candidates:
                policy = POLICY[api]
                task_id = pipeline.enqueue(
                    api, params, priority=policy["priority"], epoch=policy["epoch"]
                )
                saved = pipeline.db.execute(
                    "SELECT logical_key,epoch,job,priority,state,group_name FROM jobs WHERE id=?",
                    (task_id,),
                ).fetchone()
                if saved is None or saved["state"] != "pending":
                    raise ValueError("Isolated Pipeline did not materialize a pending job")
                materialized.append(
                    {
                        "task_id": task_id,
                        "logical_key": saved["logical_key"],
                        "epoch": saved["epoch"],
                        "priority": saved["priority"],
                        "group_name": saved["group_name"],
                        "api_name": api,
                        "params": params,
                        "job": json.loads(saved["job"]),
                        "source_plan_line": line_number,
                    }
                )
        finally:
            pipeline.close()
    if len({row["task_id"] for row in materialized}) != len(materialized):
        raise ValueError("Pipeline task identity collision")
    materialized.sort(
        key=lambda row: (
            (*DEFAULT_APIS, "fund_daily").index(row["api_name"]),
            json.dumps(row["params"], sort_keys=True),
        )
    )

    output.mkdir(parents=True)
    shards = _write_shards(output, materialized, shard_size)
    counts = {
        api: sum(row["api_name"] == api for row in materialized)
        for api in DEFAULT_APIS + ("fund_daily",)
        if any(row["api_name"] == api for row in materialized)
    }
    batch = {
        "schema_version": 1,
        "status": "prepared_not_enqueued",
        "source": {
            "release_id": report["release_id"],
            "audit_report_sha256": report_sha256,
            "collection_plan_sha256": plan_sha,
            "window": report["window"],
        },
        "selection": {
            "apis": [api for api in DEFAULT_APIS + ("fund_daily",) if api in selected_apis],
            "include_price_diagnostics": include_diagnostics,
            "source_counts": source_counts,
            "excluded_counts": excluded_counts,
            "prepared_counts": counts,
            "prepared_jobs": len(materialized),
            "shard_size": shard_size,
        },
        "identity": {
            "implementation": "backend.shared.tushare_pipeline.Pipeline.enqueue",
            "epoch_by_api": {api: POLICY[api]["epoch"] for api in counts},
            "idempotent_reentry": "same contract, params and epoch produce the same task_id",
        },
        "terminal_receipt_semantics": {
            "fund_div": "Pipeline empty is evidence of a completed request for that ETF and epoch; it is not proof that dividends never existed or cannot be revised",
            "etf_limit": "Empty is request evidence only; rows or emptiness do not prove suspension, opening-auction execution or PIT availability",
            "fund_daily": "Diagnostic zero rows remain unclassified and must never be filled or relabelled as suspension",
        },
        "activation": {
            "automatically_enqueued": False,
            "production_accessed": False,
            "credentials_accessed": False,
            "upstream_calls": 0,
            "apply_entry_implemented": False,
            "required_next_step": "review shards, then use a separately authorized authority-side Pipeline.enqueue importer",
        },
        "shards": shards,
    }
    (output / "batch-manifest.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n"
    )
    return batch


def prepare(*args, **kwargs):
    """Prohibit network and secret access while preparing an inert batch."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline acquisition preparation"))
            )
        return _prepare(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-size", type=int, default=250)
    parser.add_argument("--include-price-diagnostics", action="store_true")
    args = parser.parse_args()
    result = prepare(
        args.audit_report,
        args.report_sha256,
        args.output,
        args.shard_size,
        args.include_price_diagnostics,
    )
    print(json.dumps({"status": result["status"], **result["selection"]}, indent=2))


if __name__ == "__main__":
    main()
