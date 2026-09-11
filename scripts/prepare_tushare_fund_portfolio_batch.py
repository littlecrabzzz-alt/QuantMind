#!/usr/bin/env python3
"""Freeze a fair batch of pristine fund_portfolio history leaves."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_pipeline import contract_for  # noqa: E402
from backend.shared.tushare_rate_policy import resolved_api_rate  # noqa: E402


API = "fund_portfolio"
EPOCH = "history"
GROUP = "rrg"
MAX_BATCH_JOBS = 360
SELECTION = "newest_publication_or_period_rounds_interleaved_by_fund"
RELEASE_RE = re.compile(r"data-([a-f0-9]{64})")
CODE_RE = re.compile(r"[A-Za-z0-9]+\.[A-Z]+")
DAY_RE = re.compile(r"[0-9]{8}")
PARAMS = {"ts_code", "symbol", "ann_date", "period", "start_date", "end_date"}
FIELDS = "amount,ann_date,end_date,mkv,stk_float_ratio,stk_mkv_ratio,symbol,ts_code"
CURRENT_REQUIRED_FIELDS = (
    "ts_code",
    "ann_date",
    "end_date",
    "symbol",
    "mkv",
    "amount",
    "stk_mkv_ratio",
    "stk_float_ratio",
)
LEGACY_REQUIRED_FIELDS = ("ts_code", "ann_date", "end_date", "symbol", "mkv")
CURRENT_NULLABLE_FIELDS = (
    "ann_date",
    "amount",
    "stk_mkv_ratio",
    "stk_float_ratio",
)
JOB_KEYS = {
    "api_name",
    "params",
    "fields",
    "row_cap",
    "required_fields",
    "nullable_fields",
    "positive_fields",
}
CONTRACTS = {
    (LEGACY_REQUIRED_FIELDS, ()): "legacy_v1",
    (CURRENT_REQUIRED_FIELDS, CURRENT_NULLABLE_FIELDS): "current_v2",
}
SEMANTIC_DEDUP = {
    "signature_components": ["api_name", "params", "fields"],
    "signature_encoding": "sha256(json_bytes([api_name,params,fields]))",
    "scope": "replay_blockers_all_epochs_and_observed_contract_versions",
    "selection_scope": "history_pending_pristine_leaves",
    "replay_rule": "exclude_signature_if_any_variant_attempted_or_non_pending",
    "winner_rule": "current_contract_then_task_id",
}
BOUNDARIES = {
    "ann_date_is_source_publication_date_not_intraday_known_at": True,
    "period_is_report_period_not_availability_time": True,
    "fetched_at_proves_first_historical_availability": False,
    "split_parent_or_leaf_proves_complete_holdings": False,
    "fund_portfolio_is_complete_daily_exposure_or_pcf": False,
    "history_complete": False,
    "pit_verified": False,
}


def sha(path):
    return digest(Path(path).read_bytes())


def preparation_sha256():
    return sha(Path(__file__).resolve())


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"Invalid {label} SHA-256")
    return value


@contextmanager
def _read_lock(root):
    path = _regular(Path(root) / "pipeline.lock", "Pipeline lock")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def fixed_release_evidence(root, release_id, manifest_sha256):
    root = Path(root).resolve()
    match = RELEASE_RE.fullmatch(str(release_id))
    _hash(manifest_sha256, "release manifest")
    if not match or match.group(1) != manifest_sha256:
        raise ValueError("Release ID must be derived from its manifest SHA-256")
    pointer = json.loads(
        _regular(root / "CURRENT.json", "Current pointer").read_bytes()
    )
    if pointer != {"manifest_sha256": manifest_sha256, "release_id": release_id}:
        raise ValueError("Explicit release is not the current fixed release")
    manifest = _regular(
        root / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(manifest) != manifest_sha256:
        raise ValueError("Release manifest hash mismatch")
    return {"release_id": release_id, "release_manifest_sha256": manifest_sha256}


def rate_gate(config):
    if (
        config.get("rate_policy") != "tiered_v1"
        or config.get("requests_per_minute") != 500
        or config.get("rollout_account_rpm") != 500
    ):
        raise ValueError("fund_portfolio exact batch requires the tiered 500 rpm gate")
    configured = config.get("api_requests_per_minute", {}).get(API)
    resolved = resolved_api_rate(API, contract_for(API), config)
    if (
        type(configured) is not int
        or not 1 <= configured <= 500
        or resolved.get("rpm") != configured
    ):
        raise ValueError("fund_portfolio requires an explicit conservative API rate")
    return {
        "rate_policy": "tiered_v1",
        "account_rpm": 500,
        "rollout_account_rpm": 500,
        "api_rpm": resolved["rpm"],
        "rate_source": resolved["source"],
        "rate_review_required": bool(resolved.get("review_required")),
        "rate_review_reason": resolved.get("review_reason"),
    }


def _record(row):
    return {
        "task_id": row["id"],
        "logical_key": row["logical_key"],
        "epoch": row["epoch"],
        "priority": row["priority"],
        "group_name": row["group_name"],
        "state": row["state"],
        "tries": row["tries"],
        "job": json.loads(row["job"]),
    }


def request_from_job(job):
    params = job.get("params") if isinstance(job, dict) else None
    if (
        not isinstance(job, dict)
        or set(job) != JOB_KEYS
        or job.get("api_name") != API
        or not isinstance(params, dict)
        or not set(params).issubset(PARAMS)
        or not CODE_RE.fullmatch(str(params.get("ts_code", "")))
        or job.get("fields") != FIELDS
        or job.get("row_cap") != 2000
        or job.get("positive_fields") != []
    ):
        raise ValueError("Invalid fund_portfolio request contract")
    contract_key = (
        tuple(job.get("required_fields", ())),
        tuple(job.get("nullable_fields", ())),
    )
    if contract_key not in CONTRACTS:
        raise ValueError("Unknown fund_portfolio request contract version")
    if "symbol" in params and not CODE_RE.fullmatch(str(params["symbol"])):
        raise ValueError("Invalid fund_portfolio symbol")
    for key in ("ann_date", "period", "start_date", "end_date"):
        if key in params and not DAY_RE.fullmatch(str(params[key])):
            raise ValueError("Invalid fund_portfolio date")
    if ("start_date" in params) != ("end_date" in params):
        raise ValueError("fund_portfolio date range must be bounded")
    if "start_date" in params and params["start_date"] > params["end_date"]:
        raise ValueError("Invalid fund_portfolio date range")
    signature = digest(json_bytes([API, params, FIELDS]))
    return {
        "ts_code": params["ts_code"],
        "params": params,
        "contract_version": CONTRACTS[contract_key],
        "request_signature_sha256": signature,
    }


def _request(record):
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "state",
        "tries",
        "job",
    }:
        raise ValueError("Invalid task record")
    if (
        record["epoch"] != EPOCH
        or record["group_name"] != GROUP
        or record["state"] != "pending"
        or record["tries"] != 0
        or type(record["priority"]) is not int
    ):
        raise ValueError("Batch contains a non-pristine fund_portfolio history leaf")
    job = record["job"]
    request = request_from_job(job)
    params = request["params"]
    if not set(params).intersection({"ann_date", "period", "start_date"}):
        raise ValueError("fund_portfolio history task needs a date boundary")
    logical_key = digest(json_bytes(job))
    task_id = digest(json_bytes([logical_key, record["epoch"]]))
    if logical_key != record["logical_key"] or task_id != record["task_id"]:
        raise ValueError("Task identity mismatch")
    known = params.get("ann_date") or params.get("end_date")
    return {
        **request,
        "availability_bound": known or params.get("period") or params["start_date"],
        "availability_kind": "ann_date"
        if "ann_date" in params
        else "end_date_bound"
        if "end_date" in params
        else "period_only",
        "period": params.get("period"),
    }


def _selected(records, reasons):
    requests = [_request(record) for record in records]
    reason_counts = Counter(reasons[record["task_id"]] for record in records)
    request_params = [(item["ts_code"], item["params"]) for item in requests]
    request_params.sort(key=lambda item: (item[0], json_bytes(item[1])))
    signatures = sorted(item["request_signature_sha256"] for item in requests)
    return {
        "jobs": len(records),
        "unique_funds": len({item["ts_code"] for item in requests}),
        "unique_request_signatures": len(set(signatures)),
        "contract_versions": dict(
            sorted(Counter(item["contract_version"] for item in requests).items())
        ),
        "availability_kinds": dict(
            sorted(Counter(item["availability_kind"] for item in requests).items())
        ),
        "availability_bound_min": min(item["availability_bound"] for item in requests),
        "availability_bound_max": max(item["availability_bound"] for item in requests),
        "selection_counts": dict(sorted(reason_counts.items())),
        "request_params_sha256": digest(json_bytes(request_params)),
        "request_signatures_sha256": digest(json_bytes(signatures)),
    }


def verify_manifest(path, manifest_sha256):
    path = _regular(path, "Batch manifest")
    if _hash(manifest_sha256, "batch manifest") != sha(path):
        raise ValueError("Batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "kind",
        "source",
        "api_counts",
        "selected",
        "selection_reasons",
        "semantic_dedup",
        "request_signatures",
        "boundaries",
        "all_task_ids_sha256",
        "all_request_signatures_sha256",
        "records",
    }:
        raise ValueError("Invalid batch manifest")
    source, records = manifest["source"], manifest["records"]
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "fund_portfolio_history_exact_batch"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "authority_config_sha256",
            "preparation_sha256",
            "api_name",
            "epoch",
            "group_name",
            "state",
            "tries",
            "attempts",
            "leaf_only",
            "semantic_request_dedup",
            "selection",
            "rate_gate",
            "eligible_jobs",
            "eligible_variants",
            "eligible_funds",
            "eligible_task_ids_sha256",
            "eligible_request_signatures_sha256",
        }
        or source.get("api_name") != API
        or source.get("epoch") != EPOCH
        or source.get("group_name") != GROUP
        or source.get("state") != "pending"
        or source.get("tries") != 0
        or source.get("attempts") != 0
        or source.get("leaf_only") is not True
        or source.get("semantic_request_dedup") is not True
        or source.get("selection") != SELECTION
        or not isinstance(source.get("eligible_jobs"), int)
        or source["eligible_jobs"] < 1
        or not isinstance(source.get("eligible_variants"), int)
        or source["eligible_variants"] < source["eligible_jobs"]
        or not isinstance(source.get("eligible_funds"), int)
        or source["eligible_funds"] < 1
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_BATCH_JOBS
        or manifest.get("boundaries") != BOUNDARIES
        or not RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or RELEASE_RE.fullmatch(source["release_id"]).group(1)
        != source.get("release_manifest_sha256")
    ):
        raise ValueError("Invalid batch source")
    gate = source.get("rate_gate")
    if (
        not isinstance(gate, dict)
        or set(gate)
        != {
            "rate_policy",
            "account_rpm",
            "rollout_account_rpm",
            "api_rpm",
            "rate_source",
            "rate_review_required",
            "rate_review_reason",
        }
        or gate.get("rate_policy") != "tiered_v1"
        or gate.get("account_rpm") != 500
        or gate.get("rollout_account_rpm") != 500
        or type(gate.get("api_rpm")) is not int
        or not 1 <= gate["api_rpm"] <= 500
        or not isinstance(gate.get("rate_source"), str)
        or not gate["rate_source"]
        or type(gate.get("rate_review_required")) is not bool
        or (
            gate.get("rate_review_reason") is not None
            and not isinstance(gate.get("rate_review_reason"), str)
        )
    ):
        raise ValueError("Invalid fund_portfolio rate gate")
    for key in (
        "release_manifest_sha256",
        "authority_config_sha256",
        "preparation_sha256",
        "eligible_task_ids_sha256",
        "eligible_request_signatures_sha256",
    ):
        _hash(source.get(key), key)
    task_ids = sorted(record["task_id"] for record in records)
    reasons = manifest.get("selection_reasons")
    request_signatures = {
        record["task_id"]: _request(record)["request_signature_sha256"]
        for record in records
    }
    signatures = sorted(request_signatures.values())
    if (
        len(task_ids) != len(set(task_ids))
        or len(signatures) != len(set(signatures))
        or source["eligible_jobs"] < len(records)
        or source["eligible_funds"]
        < manifest.get("selected", {}).get("unique_funds", 0)
        or manifest.get("api_counts") != {API: len(records)}
        or not isinstance(reasons, dict)
        or set(reasons) != set(task_ids)
        or not set(reasons.values()).issubset({"split_child_leaf", "history_leaf"})
        or manifest.get("semantic_dedup") != SEMANTIC_DEDUP
        or manifest.get("request_signatures") != request_signatures
        or manifest.get("selected") != _selected(records, reasons)
        or manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids))
        or manifest.get("all_request_signatures_sha256")
        != digest(json_bytes(signatures))
    ):
        raise ValueError("Batch selection evidence mismatch")
    return manifest


def prepare(root, output, release_id, release_manifest_sha256, jobs=MAX_BATCH_JOBS):
    if type(jobs) is not int or not 1 <= jobs <= MAX_BATCH_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    root, requested_output = Path(root).resolve(), Path(output)
    if requested_output.exists() or requested_output.is_symlink():
        raise ValueError("Output must not exist or be inside authority")
    output = requested_output.resolve()
    if output == root or root in output.parents:
        raise ValueError("Output must not exist or be inside authority")
    with _read_lock(root):
        release = fixed_release_evidence(root, release_id, release_manifest_sha256)
        config_path = _regular(root / "pipeline-config.json", "Pipeline config")
        config_bytes = config_path.read_bytes()
        pinned_rate_gate = rate_gate(json.loads(config_bytes))
        database = _regular(root / "pipeline.sqlite", "Pipeline database")
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Pipeline schema must already be version 6")
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT j.id,j.logical_key,j.epoch,j.job,j.priority,j.group_name,"
                "j.state,j.tries,EXISTS(SELECT 1 FROM partition_children pc "
                "WHERE pc.child_id=j.id) partition_child FROM jobs j "
                "INDEXED BY jobs_ready_api_history WHERE j.epoch=? "
                "AND json_extract(j.job,'$.api_name')=? AND j.group_name=? "
                "AND j.state='pending' AND j.tries=0 "
                "AND NOT EXISTS(SELECT 1 FROM attempts a WHERE a.job_id=j.id) "
                "AND NOT EXISTS(SELECT 1 FROM partition_children pc "
                "WHERE pc.parent_id=j.id) ORDER BY j.id",
                (EPOCH, API, GROUP),
            ).fetchall()
            inventory = db.execute(
                "SELECT j.job,j.state,EXISTS(SELECT 1 FROM attempts a "
                "WHERE a.job_id=j.id) attempted FROM jobs j "
                "WHERE json_extract(j.job,'$.api_name')=? ORDER BY j.id",
                (API,),
            ).fetchall()
        finally:
            db.close()
    blocked_signatures = set()
    for item in inventory:
        request = request_from_job(json.loads(item["job"]))
        signature = request["request_signature_sha256"]
        if item["attempted"] or item["state"] != "pending":
            blocked_signatures.add(signature)
    history_variants = defaultdict(list)
    partition_child = {}
    for row in rows:
        record = _record(row)
        request = _request(record)
        signature = request["request_signature_sha256"]
        if signature in blocked_signatures:
            continue
        history_variants[signature].append((record, request))
        partition_child[record["task_id"]] = bool(row["partition_child"])
    winners = []
    for signature_variants in history_variants.values():
        signature_variants.sort(
            key=lambda item: (
                item[1]["contract_version"] != "current_v2",
                item[0]["task_id"],
            )
        )
        winners.append(signature_variants[0])
    buckets = defaultdict(list)
    for record, request in winners:
        buckets[request["ts_code"]].append((record, request))
    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: (
                not partition_child[item[0]["task_id"]],
                -int(item[1]["availability_bound"]),
                -int(item[1]["period"] or "00000000"),
                item[0]["task_id"],
            )
        )
    candidates = []
    for code, bucket in buckets.items():
        for request_round, (record, request) in enumerate(bucket):
            candidates.append(
                (
                    request_round,
                    not partition_child[record["task_id"]],
                    -int(request["availability_bound"]),
                    -int(request["period"] or "00000000"),
                    code,
                    record["task_id"],
                    record,
                )
            )
    candidates.sort()
    selected = candidates[:jobs]
    if len(selected) != jobs:
        raise ValueError("Insufficient pristine fund_portfolio history leaves")
    records = [item[-1] for item in selected]
    task_ids = sorted(record["task_id"] for record in records)
    eligible_ids = sorted(item[-1]["task_id"] for item in candidates)
    eligible_signatures = sorted(
        _request(item[-1])["request_signature_sha256"] for item in candidates
    )
    request_signatures = {
        record["task_id"]: _request(record)["request_signature_sha256"]
        for record in records
    }
    selected_signatures = sorted(request_signatures.values())
    reasons = {
        record["task_id"]: "split_child_leaf"
        if partition_child[record["task_id"]]
        else "history_leaf"
        for record in records
    }
    manifest = {
        "schema_version": 1,
        "kind": "fund_portfolio_history_exact_batch",
        "source": {
            **release,
            "authority_config_sha256": digest(config_bytes),
            "preparation_sha256": preparation_sha256(),
            "api_name": API,
            "epoch": EPOCH,
            "group_name": GROUP,
            "state": "pending",
            "tries": 0,
            "attempts": 0,
            "leaf_only": True,
            "semantic_request_dedup": True,
            "selection": SELECTION,
            "rate_gate": pinned_rate_gate,
            "eligible_jobs": len(candidates),
            "eligible_variants": sum(
                len(history_variants[signature]) for signature in eligible_signatures
            ),
            "eligible_funds": len(buckets),
            "eligible_task_ids_sha256": digest(json_bytes(eligible_ids)),
            "eligible_request_signatures_sha256": digest(
                json_bytes(eligible_signatures)
            ),
        },
        "api_counts": {API: len(records)},
        "selected": _selected(records, reasons),
        "selection_reasons": reasons,
        "semantic_dedup": SEMANTIC_DEDUP,
        "request_signatures": request_signatures,
        "boundaries": BOUNDARIES,
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "all_request_signatures_sha256": digest(json_bytes(selected_signatures)),
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as target:
        target.write(json_bytes(manifest))
    return verify_manifest(output, sha(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--release-manifest-sha256", required=True)
    parser.add_argument("--jobs", type=int, default=MAX_BATCH_JOBS)
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.output,
        args.release_id,
        args.release_manifest_sha256,
        args.jobs,
    )
    print(
        json.dumps(
            {
                "status": "prepared_not_executed",
                "jobs": len(result["records"]),
                "api_counts": result["api_counts"],
                "selected": result["selected"],
                "manifest_sha256": sha(args.output),
                "all_task_ids_sha256": result["all_task_ids_sha256"],
                "all_request_signatures_sha256": result[
                    "all_request_signatures_sha256"
                ],
                "eligible_task_ids_sha256": result["source"][
                    "eligible_task_ids_sha256"
                ],
                "eligible_request_signatures_sha256": result["source"][
                    "eligible_request_signatures_sha256"
                ],
                "authority_config_sha256": result["source"]["authority_config_sha256"],
                "preparation_sha256": result["source"]["preparation_sha256"],
                "upstream_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
