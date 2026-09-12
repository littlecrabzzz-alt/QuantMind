#!/usr/bin/env python3
"""Prepare, inspect, or execute one private p_list/p_get snapshot batch."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, contextmanager, ExitStack
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared import runtime_secrets  # noqa: E402
from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared import tushare_portfolio_read_contracts as portfolio  # noqa: E402
from backend.shared import tushare_registry as registry  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402
from scripts import run_tushare_fund_nav_batch as exact_runner  # noqa: E402

PRIVATE_DIR = "private-portfolio-batches"
STAGE_APIS = {"list": "p_list", "members": "p_get"}
MAX_REQUESTS = {"list": 1, "members": 30}
MAX_SECONDS = 90
MIN_FREE_BYTES = 100 * 2**30
HASH = re.compile(r"[a-f0-9]{64}")
RELEASE = re.compile(r"data-[a-f0-9]{64}")
SNAPSHOT = re.compile(r"[0-9]{8}T[0-9]{6}Z")
BOUNDARIES = {
    "account_private": True,
    "snapshot_history_complete": False,
    "deleted_or_intermediate_revisions_complete": False,
    "atomic_list_member_snapshot_proven": False,
    "saturated_list_or_member_complete": False,
    "upstream_writes": False,
    "release_published": False,
}


def sha(path):
    return digest(Path(path).read_bytes())


def code_sha256():
    paths = (
        Path(__file__).resolve(),
        Path(pipeline_module.__file__).resolve(),
        Path(portfolio.__file__).resolve(),
        Path(registry.__file__).resolve(),
        REPO / "backend/shared/tushare_intake.py",
        Path(exact_runner.__file__).resolve(),
        REPO / "config/tushare-catalog.json",
    )
    return digest(json_bytes([sha(path) for path in paths]))


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _private_dir(root, *, create=False):
    root = Path(root).resolve()
    target = root / PRIVATE_DIR
    if target.is_symlink():
        raise ValueError("Private batch directory must not be a symlink")
    if create and not target.exists():
        target.mkdir(mode=0o700)
    if not target.is_dir() or stat.S_IMODE(target.stat().st_mode) != 0o700:
        raise ValueError("Private batch directory must have mode 0700")
    return target


def _private_path(root, path, *, output=False):
    directory = _private_dir(root, create=output)
    requested = Path(path)
    if requested.exists() and requested.is_symlink():
        raise ValueError("Private artifact must not be a symlink")
    resolved = requested.resolve()
    if resolved.parent != directory or resolved.suffix != ".json":
        raise ValueError(
            "Private artifacts must stay in the authority private directory"
        )
    if output and resolved.exists():
        raise ValueError("Private artifact is create-only")
    if not output:
        _regular(resolved, "Private artifact")
        if stat.S_IMODE(resolved.stat().st_mode) != 0o600:
            raise ValueError("Private artifact must have mode 0600")
    return resolved


def _write_private(root, path, value):
    target = _private_path(root, path, output=True)
    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        raw = json_bytes(value)
        view = memoryview(raw)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, target, follow_symlinks=False)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return target


@contextmanager
def _lock(root, exclusive):
    lock_path = _regular(Path(root) / "pipeline.lock", "Pipeline lock")
    flags = os.O_RDWR if exclusive else os.O_RDONLY
    descriptor = os.open(lock_path, flags | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+" if exclusive else "rb") as lock:
        fcntl.flock(
            lock,
            (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB,
        )
        yield


def _release(root, release_id, manifest_sha256):
    if not RELEASE.fullmatch(str(release_id)) or not HASH.fullmatch(
        str(manifest_sha256)
    ):
        raise ValueError("Invalid fixed release pin")
    pointer = _regular(Path(root) / "CURRENT.json", "CURRENT pointer")
    expected = {
        "manifest_sha256": manifest_sha256,
        "release_id": release_id,
    }
    if json.loads(pointer.read_bytes()) != expected:
        raise ValueError("Pinned release is no longer CURRENT")
    manifest = _regular(
        Path(root) / "releases" / release_id / "manifest.json", "Release manifest"
    )
    if sha(manifest) != manifest_sha256 or release_id != "data-" + manifest_sha256:
        raise ValueError("Fixed release manifest mismatch")
    return sha(pointer)


def _config(root, expected_sha256, snapshot_epoch):
    if not HASH.fullmatch(str(expected_sha256)):
        raise ValueError("Invalid authority config pin")
    path = _regular(Path(root) / "pipeline-config.json", "Pipeline config")
    raw = path.read_bytes()
    if digest(raw) != expected_sha256:
        raise ValueError("Authority config hash mismatch")
    config = json.loads(raw)
    if config.get("enable_portfolio_read") is not True:
        raise ValueError("Portfolio reads are not explicitly enabled")
    selected = config.get("portfolio_read_apis", ["p_list", "p_get"])
    if not isinstance(selected, list) or not {"p_list", "p_get"}.issubset(selected):
        raise ValueError("Both portfolio read APIs must be enabled")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if (
        portfolio.portfolio_read_snapshot_epoch(config, today)
        != "snapshot-" + snapshot_epoch
    ):
        raise ValueError("Configured portfolio snapshot epoch mismatch")
    return raw, config


def _job_record(api, params, snapshot_epoch):
    spec = contract_for(api)
    fields = sorted(set(spec["extra_fields"]) | set(spec["required_fields"]))
    job = {
        "api_name": api,
        "params": params,
        "fields": ",".join(fields),
        "row_cap": spec["row_cap"],
        "required_fields": spec["required_fields"],
        "nullable_fields": spec["nullable_fields"],
        "positive_fields": spec["positive_fields"],
    }
    logical = digest(json_bytes(job))
    epoch = "snapshot-" + snapshot_epoch
    return {
        "task_id": digest(json_bytes([logical, epoch])),
        "logical_key": logical,
        "epoch": epoch,
        "priority": 10 if api == "p_list" else 20,
        "group_name": "portfolio_read",
        "job": job,
    }


def _request_sha(record):
    job = record["job"]
    return digest(json_bytes([job["api_name"], job["params"], job["fields"]]))


def _validate_record(record, stage, snapshot_epoch):
    api = STAGE_APIS[stage]
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "job",
    }:
        raise ValueError("Invalid private task record")
    job = record.get("job")
    params = job.get("params") if isinstance(job, dict) else None
    if (
        not isinstance(params, dict)
        or (api == "p_list" and params != {})
        or (
            api == "p_get"
            and (
                set(params) != {"name"}
                or not isinstance(params["name"], str)
                or not params["name"].strip()
            )
        )
    ):
        raise ValueError("Invalid private task parameters")
    expected = _job_record(api, params, snapshot_epoch)
    if record != expected:
        raise ValueError("Private task identity mismatch")
    return record


def _authority_row(db, record):
    rows = db.execute(
        "SELECT id,logical_key,epoch,job,priority,group_name,state,tries,result "
        "FROM jobs INDEXED BY jobs_partition_lookup WHERE epoch=? "
        "AND json_extract(job,'$.api_name')=? AND logical_key=?",
        (record["epoch"], record["job"]["api_name"], record["logical_key"]),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("Same-epoch request identity is ambiguous")
    if not rows:
        return None, 0
    row = rows[0]
    actual = {
        "task_id": row["id"],
        "logical_key": row["logical_key"],
        "epoch": row["epoch"],
        "priority": row["priority"],
        "group_name": row["group_name"],
        "job": json.loads(row["job"]),
    }
    if actual != record:
        raise ValueError("Same-epoch authority task identity changed")
    attempts = db.execute(
        "SELECT COUNT(*) FROM attempts WHERE job_id=?", (record["task_id"],)
    ).fetchone()[0]
    return row, attempts


def _require_pristine(db, records):
    for record in records:
        row, attempts = _authority_row(db, record)
        if row is not None and (
            row["state"] != "pending"
            or row["tries"] != 0
            or row["result"] is not None
            or attempts != 0
        ):
            raise ValueError("Same-epoch request has prior execution evidence")


def _verified_list(db, root, record):
    row, attempt_count = _authority_row(db, record)
    if row is None or row["state"] not in ("done", "empty"):
        raise ValueError("Verified list observation is not terminal")
    if row["tries"] != 1 or attempt_count != 1 or row["result"] is None:
        raise ValueError("Verified list observation must have exactly one attempt")
    result = json.loads(row["result"])
    attempt = db.execute(
        "SELECT attempt,result FROM attempts WHERE job_id=?", (record["task_id"],)
    ).fetchone()
    if attempt["attempt"] != 1 or json.loads(attempt["result"]) != result:
        raise ValueError("List attempt and terminal result disagree")
    expected_status = "sample_ok" if row["state"] == "done" else "empty_unverified"
    observation_name = result.get("observation") if isinstance(result, dict) else None
    observation_sha = (
        result.get("observation_sha256") if isinstance(result, dict) else None
    )
    object_sha = result.get("object_sha256") if isinstance(result, dict) else None
    if (
        result.get("api_name") != "p_list"
        or result.get("status") != expected_status
        or result.get("http_status") != 200
        or result.get("response_complete") is not True
        or result.get("response_format") != "json"
        or result.get("field_coverage") != "complete_for_explicit_request"
        or result.get("supplier_has_more") is True
        or result.get("missing_fields") not in (None, [])
        or not re.fullmatch(r"[a-f0-9]{32}\.json", str(observation_name or ""))
        or not HASH.fullmatch(str(observation_sha or ""))
        or not HASH.fullmatch(str(object_sha or ""))
    ):
        raise ValueError("List result is not verified complete response evidence")
    observation_path = _regular(
        Path(root) / "observations" / observation_name, "List observation"
    )
    object_path = _regular(Path(root) / "objects" / f"{object_sha}.json", "List object")
    if (
        observation_path.resolve().parent != Path(root).resolve() / "observations"
        or object_path.resolve().parent != Path(root).resolve() / "objects"
    ):
        raise ValueError("List evidence escaped authority")
    observation_raw, object_raw = (
        observation_path.read_bytes(),
        object_path.read_bytes(),
    )
    if digest(observation_raw) != observation_sha or digest(object_raw) != object_sha:
        raise ValueError("List immutable evidence checksum mismatch")
    observation, payload = json.loads(observation_raw), json.loads(object_raw)
    request = {key: record["job"][key] for key in ("api_name", "params", "fields")}
    assessment = (
        observation.get("assessment") if isinstance(observation, dict) else None
    )
    for key in (
        "status",
        "http_status",
        "response_complete",
        "response_format",
        "field_coverage",
        "row_count",
        "supplier_has_more",
        "missing_fields",
    ):
        if not isinstance(assessment, dict) or assessment.get(key) != result.get(key):
            raise ValueError("List observation assessment mismatch")
    data = payload.get("data") if isinstance(payload, dict) else None
    fields = data.get("fields") if isinstance(data, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if (
        not isinstance(observation, dict)
        or not isinstance(payload, dict)
        or observation.get("request") != request
        or observation.get("object_sha256") != object_sha
        or payload.get("code") != 0
        or not isinstance(fields, list)
        or any(not isinstance(field, str) or not field for field in fields)
        or len(fields) != len(set(fields))
        or not set(record["job"]["fields"].split(",")).issubset(fields)
        or not isinstance(items, list)
        or any(not isinstance(item, list) or len(item) != len(fields) for item in items)
        or len(items) != result.get("row_count")
    ):
        raise ValueError("List response object mismatch")
    try:
        rows = [dict(zip(fields, item, strict=True)) for item in items]
    except (TypeError, ValueError) as exc:
        raise ValueError("List response row shape mismatch") from exc
    observed = {
        "portfolio_read_list": {
            "api_name": "p_list",
            "params": {},
            "epoch": record["epoch"],
            "status": row["state"],
            "rows": [{key: item.get(key) for key in ("id", "name")} for item in rows],
        }
    }
    names, _ = portfolio._observed_names(observed, record["epoch"])
    if len(names) > MAX_REQUESTS["members"]:
        raise ValueError("Observed portfolio count exceeds one-shot member limit")
    return names, {
        "task_id": record["task_id"],
        "result_sha256": digest(json_bytes(result)),
        "observation_sha256": observation_sha,
        "object_sha256": object_sha,
        "rows": len(rows),
    }


def _manifest(stage, source, records):
    task_ids = sorted(record["task_id"] for record in records)
    requests = sorted(_request_sha(record) for record in records)
    return {
        "schema_version": 1,
        "kind": "portfolio_read_private_exact_batch",
        "stage": stage,
        "source": source,
        "api_counts": {STAGE_APIS[stage]: len(records)},
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "all_request_signatures_sha256": digest(json_bytes(requests)),
        "boundaries": BOUNDARIES,
        "records": records,
    }


def verify_manifest(root, path, manifest_sha256):
    path = _private_path(root, path)
    if not HASH.fullmatch(str(manifest_sha256)) or sha(path) != manifest_sha256:
        raise ValueError("Private batch manifest hash mismatch")
    manifest = json.loads(path.read_bytes())
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "kind",
            "stage",
            "source",
            "api_counts",
            "all_task_ids_sha256",
            "all_request_signatures_sha256",
            "boundaries",
            "records",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "portfolio_read_private_exact_batch"
        or manifest.get("stage") not in STAGE_APIS
        or manifest.get("boundaries") != BOUNDARIES
        or not isinstance(manifest.get("source"), dict)
        or not isinstance(manifest.get("records"), list)
    ):
        raise ValueError("Invalid private batch manifest")
    stage, source, records = manifest["stage"], manifest["source"], manifest["records"]
    count = len(records)
    if (stage == "list" and count != 1) or not 0 <= count <= MAX_REQUESTS[stage]:
        raise ValueError("Invalid private batch size")
    required_source = {
        "release_id",
        "release_manifest_sha256",
        "current_pointer_sha256",
        "authority_config_sha256",
        "authority_marker_sha256",
        "code_sha256",
        "snapshot_epoch",
        "p_list_evidence",
        "source_receipt_sha256",
    }
    if set(source) != required_source:
        raise ValueError("Invalid private batch source")
    hashes = (
        source.get("release_manifest_sha256"),
        source.get("current_pointer_sha256"),
        source.get("authority_marker_sha256"),
        source.get("authority_config_sha256"),
        source.get("code_sha256"),
    )
    if (
        not RELEASE.fullmatch(str(source.get("release_id", "")))
        or not SNAPSHOT.fullmatch(str(source.get("snapshot_epoch", "")))
        or not all(HASH.fullmatch(str(value or "")) for value in hashes)
        or (stage == "list") != (source.get("p_list_evidence") is None)
        or (stage == "list") != (source.get("source_receipt_sha256") is None)
    ):
        raise ValueError("Invalid private batch pins")
    if stage == "members":
        evidence = source["p_list_evidence"]
        if (
            not isinstance(evidence, dict)
            or set(evidence)
            != {
                "task_id",
                "result_sha256",
                "observation_sha256",
                "object_sha256",
                "rows",
            }
            or not all(
                HASH.fullmatch(str(evidence.get(key, "")))
                for key in (
                    "task_id",
                    "result_sha256",
                    "observation_sha256",
                    "object_sha256",
                )
            )
            or type(evidence.get("rows")) is not int
            or not 0 <= evidence["rows"] <= MAX_REQUESTS["members"]
            or not HASH.fullmatch(str(source.get("source_receipt_sha256", "")))
        ):
            raise ValueError("Invalid list evidence pin")
    validated = [
        _validate_record(record, stage, source["snapshot_epoch"]) for record in records
    ]
    task_ids = sorted(record["task_id"] for record in validated)
    requests = sorted(_request_sha(record) for record in validated)
    if len(task_ids) != len(set(task_ids)) or len(requests) != len(set(requests)):
        raise ValueError("Duplicate private batch identity")
    if (
        manifest.get("api_counts") != {STAGE_APIS[stage]: count}
        or manifest.get("all_task_ids_sha256") != digest(json_bytes(task_ids))
        or manifest.get("all_request_signatures_sha256") != digest(json_bytes(requests))
    ):
        raise ValueError("Private batch inventory hash mismatch")
    return manifest


def _verify_receipt(root, path, receipt_sha256, manifest_path, manifest):
    path = _private_path(root, path)
    if not HASH.fullmatch(str(receipt_sha256)) or sha(path) != receipt_sha256:
        raise ValueError("Source receipt hash mismatch")
    receipt = json.loads(path.read_bytes())
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("kind") != "portfolio_read_private_exact_receipt"
        or receipt.get("stage") != "list"
        or receipt.get("status") != "exact_batch_executed"
        or receipt.get("batch_manifest_sha256")
        != sha(_private_path(root, manifest_path))
        or receipt.get("all_task_ids_sha256") != manifest["all_task_ids_sha256"]
        or receipt.get("all_request_signatures_sha256")
        != manifest["all_request_signatures_sha256"]
        or receipt.get("release_id") != manifest["source"]["release_id"]
        or receipt.get("release_manifest_sha256")
        != manifest["source"]["release_manifest_sha256"]
        or receipt.get("authority_config_sha256")
        != manifest["source"]["authority_config_sha256"]
        or receipt.get("code_sha256") != manifest["source"]["code_sha256"]
        or receipt.get("snapshot_epoch") != manifest["source"]["snapshot_epoch"]
        or receipt.get("upstream_calls") != 1
        or receipt.get("attempted_by_api") != {"p_list": 1}
        or receipt.get("after_states") not in ({"done": 1}, {"empty": 1})
    ):
        raise ValueError("Source list receipt is not a successful one-shot read")
    return receipt


def prepare_manifest(
    root,
    output,
    *,
    stage,
    release_id,
    release_manifest_sha256,
    authority_config_sha256,
    code_sha256_pin,
    snapshot_epoch,
    source_manifest=None,
    source_manifest_sha256=None,
    source_receipt=None,
    source_receipt_sha256=None,
):
    if stage not in STAGE_APIS or not SNAPSHOT.fullmatch(str(snapshot_epoch)):
        raise ValueError("Invalid private batch stage or snapshot epoch")
    if code_sha256_pin != code_sha256():
        raise ValueError("Explicit code hash mismatch")
    requested_root = Path(root)
    if requested_root.is_symlink():
        raise ValueError("Authority root must not be a symlink")
    root = requested_root.resolve()
    with _lock(root, exclusive=False):
        output = _private_path(root, output, output=True)
        _regular(root / "ENABLED", "Enable marker")
        pointer_sha = _release(root, release_id, release_manifest_sha256)
        _, _ = _config(root, authority_config_sha256, snapshot_epoch)
        marker_sha = sha(root / "ENABLED")
        database = _regular(root / "pipeline.sqlite", "Pipeline database")
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
            if stage == "list":
                records = [_job_record("p_list", {}, snapshot_epoch)]
                _require_pristine(db, records)
                evidence = receipt_sha = None
            else:
                if not all(
                    value is not None
                    for value in (
                        source_manifest,
                        source_manifest_sha256,
                        source_receipt,
                        source_receipt_sha256,
                    )
                ):
                    raise ValueError(
                        "Member preparation requires pinned list artifacts"
                    )
                list_manifest = verify_manifest(
                    root, source_manifest, source_manifest_sha256
                )
                if (
                    list_manifest["stage"] != "list"
                    or list_manifest["source"]["snapshot_epoch"] != snapshot_epoch
                    or list_manifest["source"]["release_id"] != release_id
                    or list_manifest["source"]["authority_config_sha256"]
                    != authority_config_sha256
                    or list_manifest["source"]["code_sha256"] != code_sha256_pin
                ):
                    raise ValueError("List manifest pins do not match member batch")
                _verify_receipt(
                    root,
                    source_receipt,
                    source_receipt_sha256,
                    source_manifest,
                    list_manifest,
                )
                names, evidence = _verified_list(db, root, list_manifest["records"][0])
                records = [
                    _job_record("p_get", {"name": name}, snapshot_epoch)
                    for name in names
                ]
                _require_pristine(db, records)
                receipt_sha = source_receipt_sha256
        source = {
            "release_id": release_id,
            "release_manifest_sha256": release_manifest_sha256,
            "current_pointer_sha256": pointer_sha,
            "authority_config_sha256": authority_config_sha256,
            "authority_marker_sha256": marker_sha,
            "code_sha256": code_sha256_pin,
            "snapshot_epoch": snapshot_epoch,
            "p_list_evidence": evidence,
            "source_receipt_sha256": receipt_sha,
        }
        manifest = _manifest(stage, source, records)
        _write_private(root, output, manifest)
    return manifest


def _state_counts(pipeline):
    return dict(
        pipeline.db.execute(
            "SELECT j.state,COUNT(*) FROM exact_task_scope s "
            "JOIN jobs j ON j.id=s.task_id GROUP BY j.state ORDER BY j.state"
        )
    )


def _attempt_counts(pipeline):
    return Counter(
        dict(
            pipeline.db.execute(
                "SELECT json_extract(j.job,'$.api_name'),COUNT(a.attempt) "
                "FROM exact_task_scope s JOIN jobs j ON j.id=s.task_id "
                "LEFT JOIN attempts a ON a.job_id=j.id GROUP BY 1"
            )
        )
    )


def _execution_config(config, api):
    result = dict(config)
    rates = dict(result.get("api_requests_per_minute", {}))
    configured = rates.get(api)
    if configured is not None and (
        type(configured) is not int or not 1 <= configured <= 500
    ):
        raise ValueError("Invalid configured private API rate")
    rates[api] = min(configured or 30, 30)
    result["api_requests_per_minute"] = rates
    return result


def _verify_execution_state(db, root, manifest):
    records = manifest["records"]
    _require_pristine(db, records)
    if manifest["stage"] == "members":
        source_record = _job_record("p_list", {}, manifest["source"]["snapshot_epoch"])
        _, evidence = _verified_list(db, root, source_record)
        if evidence != manifest["source"]["p_list_evidence"]:
            raise ValueError("Pinned list evidence changed before member execution")


def _receipt(manifest_sha256, manifest, before, after, attempted, run):
    jobs = len(manifest["records"])
    if not jobs:
        status = "verified_empty_list_no_member_calls"
    elif sum(attempted.values()) == jobs:
        status = "exact_batch_executed"
    else:
        status = "exact_batch_incomplete"
    receipt = {
        "schema_version": 1,
        "kind": "portfolio_read_private_exact_receipt",
        "status": status,
        "stage": manifest["stage"],
        "batch_manifest_sha256": manifest_sha256,
        "all_task_ids_sha256": manifest["all_task_ids_sha256"],
        "all_request_signatures_sha256": manifest["all_request_signatures_sha256"],
        "release_id": manifest["source"]["release_id"],
        "release_manifest_sha256": manifest["source"]["release_manifest_sha256"],
        "authority_config_sha256": manifest["source"]["authority_config_sha256"],
        "code_sha256": manifest["source"]["code_sha256"],
        "snapshot_epoch": manifest["source"]["snapshot_epoch"],
        "jobs": jobs,
        "before_states": before,
        "after_states": after,
        "attempted_by_api": attempted,
        "upstream_calls": run["requests"],
        "max_upstream_calls": MAX_REQUESTS[manifest["stage"]],
        "max_seconds": MAX_SECONDS,
        "elapsed_seconds": run["elapsed_seconds"],
        "effective_api_rpm": 30,
        "release_published": False,
        "current_release_switched": False,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    return receipt


def run_batch(
    root,
    manifest_path,
    manifest_sha256,
    *,
    expected_task_ids_sha256=None,
    expected_config_sha256=None,
    expected_code_sha256=None,
    expected_release_id=None,
    expected_release_manifest_sha256=None,
    receipt_path=None,
    execute=False,
):
    root = Path(root).resolve()
    current_code = code_sha256()
    if expected_code_sha256 and expected_code_sha256 != current_code:
        raise ValueError("Explicit code hash mismatch")
    if not execute:
        with ExitStack() as guards:
            for target in (
                "socket.socket.connect",
                "socket.getaddrinfo",
                "backend.shared.tushare_pipeline.get_secret",
                "backend.shared.runtime_secrets.get_secret",
            ):
                guards.enter_context(
                    patch(
                        target, side_effect=AssertionError("Offline private batch plan")
                    )
                )
            verified = verify_manifest(root, manifest_path, manifest_sha256)
        if verified["source"]["code_sha256"] != current_code:
            raise ValueError("Manifest code hash does not match loaded helper")
        return {
            "schema_version": 1,
            "status": "plan_only",
            "stage": verified["stage"],
            "batch_manifest_sha256": manifest_sha256,
            "all_task_ids_sha256": verified["all_task_ids_sha256"],
            "all_request_signatures_sha256": verified["all_request_signatures_sha256"],
            "jobs": len(verified["records"]),
            "max_upstream_calls": MAX_REQUESTS[verified["stage"]],
            "max_seconds": MAX_SECONDS,
            "effective_api_rpm": 30,
            "authority_private_manifest_read_only": True,
            "would_access_authority_database": False,
            "would_access_credentials": False,
            "would_call_upstream": False,
            "would_write": False,
            "would_publish": False,
        }
    expected_hashes = (
        expected_task_ids_sha256,
        expected_config_sha256,
        expected_code_sha256,
        expected_release_manifest_sha256,
    )
    if (
        not all(HASH.fullmatch(str(value or "")) for value in expected_hashes)
        or not RELEASE.fullmatch(str(expected_release_id or ""))
        or receipt_path is None
    ):
        raise ValueError(
            "Execute requires all explicit pins and a private receipt path"
        )
    if root != pipeline_module.ROOT.resolve() or Path(root).is_symlink():
        raise ValueError("Execute root is not the configured authority root")
    pipeline_module.authority()
    manifest_path = _private_path(root, manifest_path)
    receipt_path = _private_path(root, receipt_path, output=True)
    with _lock(root, exclusive=True):
        verified = verify_manifest(root, manifest_path, manifest_sha256)
        source = verified["source"]
        if (
            verified["all_task_ids_sha256"] != expected_task_ids_sha256
            or source["authority_config_sha256"] != expected_config_sha256
            or source["code_sha256"] != expected_code_sha256
            or source["release_id"] != expected_release_id
            or source["release_manifest_sha256"] != expected_release_manifest_sha256
            or source["authority_marker_sha256"]
            != sha(_regular(root / "ENABLED", "Enable marker"))
            or source["current_pointer_sha256"]
            != _release(root, expected_release_id, expected_release_manifest_sha256)
        ):
            raise ValueError("Explicit execution pins do not match private manifest")
        config_raw, config = _config(
            root, expected_config_sha256, source["snapshot_epoch"]
        )
        database = _regular(root / "pipeline.sqlite", "Pipeline database")
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
            _verify_execution_state(db, root, verified)
        if not verified["records"]:
            receipt = _receipt(
                manifest_sha256,
                verified,
                {},
                {},
                {},
                {"requests": 0, "elapsed_seconds": 0.0},
            )
            _write_private(root, receipt_path, receipt)
            return {key: receipt[key] for key in receipt if key != "receipt_id"} | {
                "receipt_sha256": sha(receipt_path)
            }
        if shutil.disk_usage(root).free < MIN_FREE_BYTES:
            raise ValueError("Insufficient authority disk reserve")
        token = pipeline_module.get_secret("TUSHARE_TOKEN")
        if not token:
            raise ValueError("Tushare token is unavailable before enqueue")
        api = STAGE_APIS[verified["stage"]]
        pointer_before = sha(root / "CURRENT.json")
        with exact_runner._hard_deadline(MAX_SECONDS):
            pipeline = pipeline_module.Pipeline(
                root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
            )
            try:
                _verify_execution_state(pipeline.db, root, verified)
                for record in verified["records"]:
                    actual = pipeline.enqueue(
                        api,
                        record["job"]["params"],
                        record["priority"],
                        record["epoch"],
                    )
                    if actual != record["task_id"]:
                        raise ValueError("Enqueued private task ID changed")
                pipeline.db.commit()
                task_ids = [record["task_id"] for record in verified["records"]]
                pipeline._install_exact_task_scope(task_ids)
                before = _state_counts(pipeline)
                before_attempts = _attempt_counts(pipeline)
                with httpx.Client(
                    trust_env=False,
                    timeout=30,
                    follow_redirects=False,
                ) as client:
                    run = pipeline.run(
                        client,
                        token,
                        _execution_config(config, api),
                        max_requests=MAX_REQUESTS[verified["stage"]],
                        max_seconds=MAX_SECONDS,
                        pause=0,
                        task_ids=task_ids,
                    )
                after = _state_counts(pipeline)
                after_attempts = _attempt_counts(pipeline)
            finally:
                pipeline.close()
        attempted = {
            key: after_attempts[key] - before_attempts[key]
            for key in sorted(after_attempts | before_attempts)
            if after_attempts[key] != before_attempts[key]
        }
        if (
            _regular(root / "pipeline-config.json", "Pipeline config").read_bytes()
            != config_raw
            or sha(root / "CURRENT.json") != pointer_before
            or code_sha256() != expected_code_sha256
        ):
            raise RuntimeError(
                "Authority config, CURRENT or code changed under exact lock"
            )
        receipt = _receipt(manifest_sha256, verified, before, after, attempted, run)
        _write_private(root, receipt_path, receipt)
    return {key: receipt[key] for key in receipt if key != "receipt_id"} | {
        "receipt_sha256": sha(receipt_path)
    }


def _summary(manifest, path):
    return {
        "status": "prepared_not_executed",
        "stage": manifest["stage"],
        "jobs": len(manifest["records"]),
        "manifest_sha256": sha(path),
        "all_task_ids_sha256": manifest["all_task_ids_sha256"],
        "all_request_signatures_sha256": manifest["all_request_signatures_sha256"],
        "private_artifact": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=pipeline_module.ROOT)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=tuple(STAGE_APIS))
    parser.add_argument("--release-id")
    parser.add_argument("--release-manifest-sha256")
    parser.add_argument("--authority-config-sha256")
    parser.add_argument("--code-sha256")
    parser.add_argument("--snapshot-epoch")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--source-manifest-sha256")
    parser.add_argument("--source-receipt", type=Path)
    parser.add_argument("--source-receipt-sha256")
    parser.add_argument("--expected-task-ids-sha256")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.prepare:
        if args.execute or args.manifest_sha256:
            raise ValueError("Prepare and run modes are separate")
        result = prepare_manifest(
            args.root,
            args.manifest,
            stage=args.stage,
            release_id=args.release_id,
            release_manifest_sha256=args.release_manifest_sha256,
            authority_config_sha256=args.authority_config_sha256,
            code_sha256_pin=args.code_sha256,
            snapshot_epoch=args.snapshot_epoch,
            source_manifest=args.source_manifest,
            source_manifest_sha256=args.source_manifest_sha256,
            source_receipt=args.source_receipt,
            source_receipt_sha256=args.source_receipt_sha256,
        )
        print(json.dumps(_summary(result, args.manifest), sort_keys=True))
        return
    if not args.manifest_sha256:
        raise ValueError("Plan or execute requires manifest SHA-256")
    result = run_batch(
        args.root,
        args.manifest,
        args.manifest_sha256,
        expected_task_ids_sha256=args.expected_task_ids_sha256,
        expected_config_sha256=args.authority_config_sha256,
        expected_code_sha256=args.code_sha256,
        expected_release_id=args.release_id,
        expected_release_manifest_sha256=args.release_manifest_sha256,
        receipt_path=args.receipt,
        execute=args.execute,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
