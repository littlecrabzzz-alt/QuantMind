#!/usr/bin/env python3
"""Plan or execute one hash-pinned paired fund_nav empty review."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import sys
import threading
import time
from unittest.mock import patch

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_rate_policy import (  # noqa: E402
    enabled as tiered_rate_enabled,
    positive_int,
    resolved_api_rate,
)
from scripts import prepare_tushare_fund_nav_empty_review as preparation  # noqa: E402

MAX_UPSTREAM_REQUESTS = 360
MAX_SECONDS = 90
MIN_FREE_BYTES = 100 * 2**30
INCONCLUSIVE = {
    "transport_error",
    "rate_limited",
    "api_error",
    "permission_denied",
}


def sha(path):
    return digest(Path(path).read_bytes())


def code_sha256():
    files = (
        Path(__file__).resolve(),
        Path(preparation.__file__).resolve(),
        Path(pipeline_module.__file__).resolve(),
        REPO / "backend/shared/tushare_intake.py",
        REPO / "backend/shared/tushare_rate_policy.py",
        REPO / "backend/shared/tushare_market_contracts.py",
        REPO / "config/tushare-catalog.json",
    )
    return digest(json_bytes([sha(path) for path in files]))


def _time(value, label):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid {label}") from exc
    else:
        raise ValueError(f"Invalid {label}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _regular(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _root(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a directory")
    return path.resolve()


def _hash(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"Invalid {label}")
    return value


def _inventory(value, prefix, suffix, label):
    if (
        not isinstance(value, dict)
        or not {"path", "sha256"}.issubset(value)
        or not isinstance(value["path"], str)
        or not value["path"].startswith(prefix)
        or not value["path"].endswith(suffix)
        or "/../" in "/" + value["path"] + "/"
    ):
        raise ValueError(f"Invalid {label}")
    _hash(value["sha256"], label + " hash")
    return value


def verify_manifest(path, expected_sha256):
    path = _regular(path, "Review manifest")
    _hash(expected_sha256, "review manifest hash")
    raw = path.read_bytes()
    if digest(raw) != expected_sha256:
        raise ValueError("Review manifest hash mismatch")
    manifest = json.loads(raw)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "fund_nav_empty_review_plan"
        or manifest.get("source")
        != {"api_name": "fund_nav", "epoch": "history", "state": "empty"}
        or manifest.get("review_round") not in (1, 2)
        or manifest.get("minimum_age_seconds")
        != preparation.MINIMUM_AGE_SECONDS_BY_ROUND.get(manifest.get("review_round"))
        or manifest.get("boundaries") != preparation.BOUNDARIES
        or set(manifest)
        != {
            "schema_version",
            "kind",
            "source",
            "fixed_release",
            "review_round",
            "minimum_age_seconds",
            "as_of",
            "eligible_targets",
            "selected_targets",
            "all_task_ids_sha256",
            "boundaries",
            "records",
        }
    ):
        raise ValueError("Invalid review manifest")
    as_of = _time(manifest["as_of"], "manifest as_of")
    review_round = manifest["review_round"]
    fixed = manifest.get("fixed_release")
    if (
        not isinstance(fixed, dict)
        or set(fixed) != {"release_id", "manifest_sha256"}
        or not re.fullmatch(r"data-[a-f0-9]{64}", str(fixed.get("release_id", "")))
        or fixed.get("manifest_sha256") != fixed["release_id"].removeprefix("data-")
    ):
        raise ValueError("Invalid fixed release identity")
    records = manifest.get("records")
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= MAX_UPSTREAM_REQUESTS // 2
    ):
        raise ValueError("Review manifest must contain 1..180 paired targets")
    if manifest.get("selected_targets") != len(records):
        raise ValueError("Selected target count mismatch")
    if type(manifest.get("eligible_targets")) is not int or manifest[
        "eligible_targets"
    ] < len(records):
        raise ValueError("Eligible target count mismatch")
    task_ids = []
    for record in records:
        record_keys = {
            "target",
            "parent_ids",
            "first_empty",
            "review_round",
            "not_before",
            "control",
        }
        if review_round == 2:
            record_keys.add("round1_valid_empty")
        if not isinstance(record, dict) or set(record) != record_keys:
            raise ValueError("Invalid review record")
        target = record["target"]
        if not isinstance(target, dict) or set(target) != {
            "task_id",
            "logical_key",
            "epoch",
            "priority",
            "group_name",
            "state",
            "tries",
            "job",
            "job_sha256",
        }:
            raise ValueError("Invalid review target")
        job = target["job"]
        preparation._valid_job(job)
        logical = digest(json_bytes(job))
        task_id = digest(json_bytes([logical, "history"]))
        if (
            target["job_sha256"] != logical
            or target["logical_key"] != logical
            or target["task_id"] != task_id
            or target["epoch"] != "history"
            or target["state"] != "empty"
            or type(target["priority"]) is not int
            or type(target["tries"]) is not int
            or target["tries"] < 1
            or not isinstance(target["group_name"], str)
            or record["review_round"] != review_round
        ):
            raise ValueError("Review target identity mismatch")
        if (
            not isinstance(record["parent_ids"], list)
            or record["parent_ids"] != sorted(set(record["parent_ids"]))
            or any(
                not re.fullmatch(r"[a-f0-9]{64}", str(item))
                for item in record["parent_ids"]
            )
        ):
            raise ValueError("Invalid parent inventory")
        first = record["first_empty"]
        if (
            not isinstance(first, dict)
            or set(first) != {"attempt", "observation", "object"}
            or type(first["attempt"]) is not int
            or first["attempt"] < 1
        ):
            raise ValueError("Invalid first empty evidence")
        _inventory(first["observation"], "observations/", ".json", "first observation")
        _inventory(first["object"], "objects/", ".json", "first object")
        _time(first["observation"].get("fetched_at"), "first fetched_at")
        if set(first["observation"]) != {"path", "sha256", "fetched_at"}:
            raise ValueError("Invalid first observation")
        not_before = _time(record["not_before"], "not_before")
        if not_before > as_of:
            raise ValueError("Review timing mismatch")
        if review_round == 1 and not_before != _time(
            first["observation"]["fetched_at"], "first fetched_at"
        ) + timedelta(seconds=preparation.ROUND1_MINIMUM_AGE_SECONDS):
            raise ValueError("Review timing mismatch")
        control = record["control"]
        natural = control.get("natural_key") if isinstance(control, dict) else None
        params = control.get("request_params") if isinstance(control, dict) else None
        if (
            not isinstance(control, dict)
            or set(control)
            != {"natural_key", "request_params", "source_observation", "source_parquet"}
            or not isinstance(natural, dict)
            or set(natural) != {"ts_code", "nav_date", "ann_date"}
            or natural["ts_code"] != job["params"]["ts_code"]
            or not re.fullmatch(r"[0-9]{8}", str(natural["nav_date"]))
            or natural["nav_date"] <= job["params"]["end_date"]
            or params
            != {
                "ts_code": natural["ts_code"],
                "start_date": natural["nav_date"],
                "end_date": natural["nav_date"],
            }
        ):
            raise ValueError("Invalid positive control")
        _inventory(
            control["source_observation"],
            "observations/",
            ".json",
            "control observation",
        )
        _time(control["source_observation"].get("fetched_at"), "control fetched_at")
        if set(control["source_observation"]) != {"path", "sha256", "fetched_at"}:
            raise ValueError("Invalid control observation")
        parquet = control["source_parquet"]
        if (
            not isinstance(parquet, dict)
            or set(parquet) != {"path", "sha256", "bytes"}
            or not re.fullmatch(
                r"parquet/[a-f0-9]{64}\.parquet", str(parquet.get("path", ""))
            )
            or parquet["path"].split("/")[-1].removesuffix(".parquet")
            != parquet.get("sha256")
            or type(parquet.get("bytes")) is not int
            or parquet["bytes"] <= 0
        ):
            raise ValueError("Invalid control parquet")
        _hash(parquet["sha256"], "control parquet hash")
        if review_round == 2:
            pinned = record["round1_valid_empty"]
            if (
                not isinstance(pinned, dict)
                or set(pinned)
                != {
                    "attempt",
                    "manifest_sha256",
                    "fixed_release_id",
                    "request_observation_sha256",
                    "request_object_sha256",
                    "control_observation_sha256",
                    "control_object_sha256",
                    "completed_at",
                }
                or type(pinned["attempt"]) is not int
                or pinned["attempt"] < 1
            ):
                raise ValueError("Invalid round-one evidence pin")
            for key in (
                "manifest_sha256",
                "request_observation_sha256",
                "request_object_sha256",
                "control_observation_sha256",
                "control_object_sha256",
            ):
                _hash(pinned[key], "round-one " + key)
            if not re.fullmatch(r"data-[a-f0-9]{64}", str(pinned["fixed_release_id"])):
                raise ValueError("Invalid round-one fixed release identity")
            if not_before != _time(
                pinned["completed_at"], "round-one completed_at"
            ) + timedelta(seconds=preparation.ROUND2_MINIMUM_AGE_SECONDS):
                raise ValueError("Review timing mismatch")
        task_ids.append(task_id)
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("Duplicate review target")
    _hash(manifest["all_task_ids_sha256"], "task inventory hash")
    if manifest["all_task_ids_sha256"] != digest(json_bytes(sorted(task_ids))):
        raise ValueError("Task inventory hash mismatch")
    return manifest


@contextmanager
def _hard_deadline(seconds):
    if threading.current_thread() is not threading.main_thread() or not hasattr(
        signal, "setitimer"
    ):
        yield
        return
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError("Empty review wall-clock deadline reached")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _verify_sources(
    root, release_root, release_id, manifest_sha256, manifest, pipeline
):
    fixed = preparation._release(release_root, release_id)
    ends = {}
    for record in manifest["records"]:
        params = record["target"]["job"]["params"]
        ends[params["ts_code"]] = max(
            ends.get(params["ts_code"], ""), params["end_date"]
        )
    controls = preparation._controls(release_root, fixed, ends)
    for record in manifest["records"]:
        target = record["target"]
        saved = pipeline.db.execute(
            "SELECT * FROM jobs WHERE id=?", (target["task_id"],)
        ).fetchone()
        if saved is None:
            raise ValueError("Review target is missing from authority")
        actual = {
            "task_id": saved["id"],
            "logical_key": saved["logical_key"],
            "epoch": saved["epoch"],
            "priority": saved["priority"],
            "group_name": saved["group_name"],
            "state": saved["state"],
            "tries": saved["tries"],
            "job": json.loads(saved["job"]),
            "job_sha256": digest(json_bytes(json.loads(saved["job"]))),
        }
        if actual != target or saved["state"] != "empty":
            prior = _previous_reviews(pipeline, target["task_id"])
            recovered = any(
                result["status"] == "review_recovered_data"
                and result["empty_review"].get("manifest_sha256") == manifest_sha256
                for _, result in prior
            )
            stable = all(
                actual[key] == target[key]
                for key in (
                    "task_id",
                    "logical_key",
                    "epoch",
                    "priority",
                    "group_name",
                    "job",
                    "job_sha256",
                )
            )
            if not (recovered and stable and saved["state"] == "done"):
                raise ValueError("Authority target drifted from review manifest")
        attempt = pipeline.db.execute(
            "SELECT result FROM attempts WHERE job_id=? AND attempt=?",
            (target["task_id"], record["first_empty"]["attempt"]),
        ).fetchone()
        evidence = preparation._empty_evidence(
            root, target["job"], json.loads(attempt["result"]) if attempt else None
        )
        if evidence != {
            key: record["first_empty"][key] for key in ("observation", "object")
        }:
            raise ValueError("First empty evidence drifted from review manifest")
        code = target["job"]["params"]["ts_code"]
        if controls.get(code) != record["control"]:
            raise ValueError("Positive control drifted from fixed release")
        if record["review_round"] == 2:
            pinned = record["round1_valid_empty"]
            attempt = pipeline.db.execute(
                "SELECT result FROM attempts WHERE job_id=? AND attempt=?",
                (target["task_id"], pinned["attempt"]),
            ).fetchone()
            evidence = preparation._round1_evidence(
                root,
                release_root,
                target["job"],
                pinned["attempt"],
                json.loads(attempt["result"]) if attempt else None,
            )
            if evidence != pinned:
                raise ValueError("Round-one evidence drifted from review manifest")


def _rate_interval(config):
    resolved = resolved_api_rate(
        "fund_nav", pipeline_module.contract_for("fund_nav"), config
    )
    account = config.get("requests_per_minute", 240)
    if tiered_rate_enabled(config) and config.get("rollout_account_rpm") is not None:
        account = min(
            positive_int(account, "account request rate"),
            positive_int(config["rollout_account_rpm"], "rollout account rate"),
        )
    if type(account) is not int or not 1 <= account <= 500:
        raise ValueError("Invalid account request rate")
    minimum = config.get("api_min_interval_seconds", {}).get("fund_nav", 0)
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, (int, float))
        or not 0 <= minimum <= 86400
    ):
        raise ValueError("Invalid fund_nav request interval")
    return max(60 / account, 60 / resolved["rpm"], minimum)


def _reserve_slot(pipeline, interval, deadline):
    now = time.time()
    gates = dict(
        pipeline.db.execute(
            "SELECT scope,next_at FROM request_gates WHERE scope IN ('account','api:fund_nav')"
        )
    )
    wait = max(0, gates.get("account", 0) - now, gates.get("api:fund_nav", 0) - now)
    if wait >= deadline - time.monotonic():
        raise TimeoutError("No paired review capacity before deadline")
    if wait:
        time.sleep(wait)
    reserved = time.time() + interval
    pipeline.db.executemany(
        "INSERT INTO request_gates(scope,next_at) VALUES(?,?) "
        "ON CONFLICT(scope) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)",
        (("account", reserved), ("api:fund_nav", reserved)),
    )
    pipeline.db.commit()


def _rows(pipeline, result):
    try:
        return pipeline.records(result)
    except (KeyError, TypeError, ValueError):
        return []


def _empty(result):
    return (
        result.get("status") == "empty_unverified"
        and result.get("http_status") == 200
        and result.get("response_complete") is True
        and result.get("response_format") == "json"
        and result.get("field_coverage") == "complete_for_explicit_request"
        and result.get("row_count") == 0
        and result.get("supplier_has_more") is not True
        and result.get("missing_fields") in (None, [])
    )


def _matching_rows(rows, params):
    return bool(rows) and all(
        row.get("ts_code") == params["ts_code"]
        and params["start_date"]
        <= str(row.get("nav_date", "")).replace("-", "")
        <= params["end_date"]
        for row in rows
    )


def _classify(pipeline, record, request_result, control_result):
    request_rows = _rows(pipeline, request_result)
    control_rows = _rows(pipeline, control_result)
    if request_result.get("status") == "sample_ok" and _matching_rows(
        request_rows, record["target"]["job"]["params"]
    ):
        return "review_recovered_data"
    if request_result.get("status") in INCONCLUSIVE:
        return "review_inconclusive"
    if not _empty(request_result):
        return "review_conflict"
    if (
        control_result.get("status") == "sample_ok"
        and control_result.get("http_status") == 200
        and control_result.get("response_complete") is True
        and control_result.get("response_format") == "json"
        and control_result.get("field_coverage") == "complete_for_explicit_request"
        and _matching_rows(control_rows, record["control"]["request_params"])
    ):
        return (
            "round1_valid_empty" if record["review_round"] == 1 else "review_exhausted"
        )
    return "review_inconclusive"


def _previous_reviews(pipeline, task_id, review_round=None):
    reviews = []
    for row in pipeline.db.execute(
        "SELECT attempt,result FROM attempts WHERE job_id=? ORDER BY attempt",
        (task_id,),
    ):
        result = json.loads(row["result"])
        review = result.get("empty_review") if isinstance(result, dict) else None
        if (
            isinstance(review, dict)
            and review.get("schema_version") == 1
            and review.get("review_round") in (1, 2)
            and (review_round is None or review.get("review_round") == review_round)
        ):
            reviews.append((row["attempt"], result))
    return reviews


def _execution_authority(pipeline, manifest, manifest_sha256, fallback):
    pinned = {
        result["empty_review"].get("authority_sha256")
        for record in manifest["records"]
        for _, result in _previous_reviews(pipeline, record["target"]["task_id"])
        if result["empty_review"].get("manifest_sha256") == manifest_sha256
    }
    if not pinned:
        return fallback
    if len(pinned) != 1 or not re.fullmatch(r"[a-f0-9]{64}", str(next(iter(pinned)))):
        raise ValueError("Existing review attempts disagree on authority identity")
    return pinned.pop()


def _fetched_at(root, result):
    name = result.get("observation")
    if not re.fullmatch(r"[a-f0-9]{32}\.json", str(name or "")):
        return datetime.now(timezone.utc)
    observation = json.loads(
        _regular(root / "observations" / name, "Review observation").read_bytes()
    )
    return _time(observation["fetched_at"], "review fetched_at")


def _review_pair(
    pipeline,
    root,
    record,
    client,
    token,
    manifest_sha256,
    authority_sha256,
    release_id,
    now,
    interval,
    deadline,
):
    task_id = record["target"]["task_id"]
    review_round = record["review_round"]
    previous = _previous_reviews(pipeline, task_id, review_round)
    same = [
        result
        for _, result in previous
        if result["empty_review"].get("manifest_sha256") == manifest_sha256
    ]
    if same:
        return same[-1], 0
    terminal = {
        "round1_valid_empty" if review_round == 1 else "review_exhausted",
        "review_conflict",
        "manual_hold",
        "review_recovered_data",
    }
    if any(result["status"] in terminal for _, result in previous):
        raise ValueError("Review target already has a terminal result for this round")
    inconclusive = [
        result for _, result in previous if result["status"] == "review_inconclusive"
    ]
    if inconclusive:
        due = _time(
            inconclusive[-1]["empty_review"]["retry_not_before"], "retry_not_before"
        )
        if now < due:
            raise ValueError("Review retry is not due")

    job = record["target"]["job"]
    control_job = {**job, "params": record["control"]["request_params"]}
    _reserve_slot(pipeline, interval, deadline)
    request_result = pipeline_module.capture_sample(client, token, job, root)
    _reserve_slot(pipeline, interval, deadline)
    control_result = pipeline_module.capture_sample(client, token, control_job, root)
    outcome = _classify(pipeline, record, request_result, control_result)
    if outcome == "review_recovered_data":
        try:
            request_result = pipeline.normalize(request_result)
        except Exception as exc:
            request_result["normalization_error"] = type(exc).__name__
            outcome = "review_conflict"
    if outcome == "review_inconclusive" and len(inconclusive) >= 2:
        outcome = "manual_hold"
    finished = max(_fetched_at(root, request_result), _fetched_at(root, control_result))
    retry_not_before = None
    if outcome == "review_inconclusive":
        retry_not_before = finished + timedelta(hours=1 if not inconclusive else 24)
    attempt = pipeline.db.execute(
        "SELECT COALESCE(MAX(attempt),0)+1 FROM attempts WHERE job_id=?", (task_id,)
    ).fetchone()[0]
    review = {
        "schema_version": 1,
        "kind": "fund_nav_empty_review",
        "review_round": review_round,
        "manifest_sha256": manifest_sha256,
        "authority_sha256": authority_sha256,
        "fixed_release_id": release_id,
        "retry_index": len(inconclusive),
        "retry_not_before": retry_not_before.isoformat() if retry_not_before else None,
        "request_observation_sha256": request_result.get("observation_sha256"),
        "request_object_sha256": request_result.get("object_sha256"),
        "control_observation_sha256": control_result.get("observation_sha256"),
        "control_object_sha256": control_result.get("object_sha256"),
    }
    saved = {
        "api_name": "fund_nav",
        "status": outcome,
        "empty_review": review,
        "request_result": request_result,
        "control_result": control_result,
        "history_complete": False,
        "pit_verified": False,
    }
    try:
        pipeline.db.execute(
            "INSERT INTO attempts(job_id,attempt,result) VALUES(?,?,?)",
            (task_id, attempt, json.dumps(saved)),
        )
        if outcome == "review_recovered_data":
            pipeline.db.execute(
                "UPDATE jobs SET state='done',result=?,tries=tries+1 WHERE id=?",
                (json.dumps(request_result), task_id),
            )
            pipeline.reconcile_partitions(child_id=task_id, deadline=deadline)
        pipeline.db.commit()
    except BaseException:
        pipeline.db.rollback()
        raise
    return saved, 2


def _write_receipt(output, receipt):
    path = Path(output)
    if path.is_symlink() or path.exists():
        raise ValueError("Receipt output must be new")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json_bytes(receipt))
        stream.flush()
        os.fsync(stream.fileno())


def _execute(
    manifest_sha256,
    manifest,
    *,
    root,
    release_root,
    release_id,
    expected_authority_sha256,
    expected_config_sha256,
    expected_code_sha256,
    expected_release_manifest_sha256,
    output,
    max_requests,
    max_seconds,
    now,
):
    root = _root(root, "Authority root")
    release_root = _root(release_root, "Fixed release root")
    if root != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not the configured authority root")
    if release_id != manifest["fixed_release"]["release_id"]:
        raise ValueError("Explicit fixed release ID mismatch")
    if expected_release_manifest_sha256 != manifest["fixed_release"]["manifest_sha256"]:
        raise ValueError("Explicit fixed release manifest hash mismatch")
    pipeline_module.authority()
    _regular(root / "ENABLED", "Authority enable marker")
    if len(manifest["records"]) * 2 > max_requests:
        raise ValueError("Paired review exceeds the explicit request limit")
    if output is None:
        raise ValueError("Execute requires an immutable receipt output")
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError("Receipt output must be new")
    lock_path = root / "pipeline.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe shared pipeline lock")
    descriptor = os.open(
        lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if code_sha256() != expected_code_sha256:
            raise ValueError("Code changed before the shared lock was acquired")
        database = _regular(root / "pipeline.sqlite", "Authority pipeline database")
        if sha(database) != expected_authority_sha256:
            raise ValueError("Explicit authority database hash mismatch")
        config_path = _regular(
            root / "pipeline-config.json", "Authority pipeline config"
        )
        config_raw = config_path.read_bytes()
        if digest(config_raw) != expected_config_sha256:
            raise ValueError("Explicit authority config hash mismatch")
        release_manifest = _regular(
            release_root / "releases" / release_id / "manifest.json",
            "Fixed release manifest",
        )
        if sha(release_manifest) != expected_release_manifest_sha256:
            raise ValueError("Fixed release manifest changed")
        if shutil.disk_usage(root).free < MIN_FREE_BYTES:
            return {
                "status": "blocked_disk_reserve",
                "upstream_calls": 0,
                "receipt_written": False,
            }
        config = json.loads(config_raw)
        interval = _rate_interval(config)
        if interval * max(0, len(manifest["records"]) * 2 - 1) >= max_seconds:
            raise ValueError("Paired review cannot fit the rate and time capacity")
        pipeline = pipeline_module.Pipeline(
            root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        pointer = root / "CURRENT.json"
        pointer_before = sha(_regular(pointer, "Current release pointer"))
        try:
            if pipeline.db.execute("PRAGMA user_version").fetchone()[0] != 6:
                raise ValueError("Authority pipeline schema must already be version 6")
            if now < _time(manifest["as_of"], "manifest as_of"):
                raise ValueError("Execution clock precedes the frozen review plan")
            _verify_sources(
                root,
                release_root,
                release_id,
                manifest_sha256,
                manifest,
                pipeline,
            )
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {
                    "status": "blocked_missing_token",
                    "upstream_calls": 0,
                    "receipt_written": False,
                }
            results, calls = [], 0
            execution_authorities = set()
            execution_authority = _execution_authority(
                pipeline, manifest, manifest_sha256, expected_authority_sha256
            )
            started = time.monotonic()
            deadline = started + max_seconds
            with (
                _hard_deadline(max_seconds),
                httpx.Client(
                    trust_env=False,
                    timeout=min(30, max_seconds),
                    follow_redirects=False,
                ) as client,
            ):
                for record in manifest["records"]:
                    saved, used = _review_pair(
                        pipeline,
                        root,
                        record,
                        client,
                        token,
                        manifest_sha256,
                        execution_authority,
                        release_id,
                        now,
                        interval,
                        deadline,
                    )
                    calls += used
                    execution_authorities.add(saved["empty_review"]["authority_sha256"])
                    results.append(
                        {
                            "task_id": record["target"]["task_id"],
                            "status": saved["status"],
                            "request_observation_sha256": saved["empty_review"][
                                "request_observation_sha256"
                            ],
                            "request_object_sha256": saved["empty_review"][
                                "request_object_sha256"
                            ],
                            "control_observation_sha256": saved["empty_review"][
                                "control_observation_sha256"
                            ],
                            "control_object_sha256": saved["empty_review"][
                                "control_object_sha256"
                            ],
                            "retry_index": saved["empty_review"]["retry_index"],
                            "retry_not_before": saved["empty_review"][
                                "retry_not_before"
                            ],
                        }
                    )
            if (
                _regular(config_path, "Authority pipeline config").read_bytes()
                != config_raw
            ):
                raise RuntimeError("Authority config changed while lock was held")
            if sha(_regular(pointer, "Current release pointer")) != pointer_before:
                raise RuntimeError(
                    "Current release pointer changed during empty review"
                )
            if sha(release_manifest) != expected_release_manifest_sha256:
                raise RuntimeError("Fixed release changed during empty review")
            if code_sha256() != expected_code_sha256:
                raise RuntimeError("Code changed during empty review")
        finally:
            pipeline.close()
    counts = Counter(item["status"] for item in results)
    if len(execution_authorities) != 1:
        raise RuntimeError("Review attempts disagree on their authority snapshot")
    receipt = {
        "schema_version": 1,
        "kind": "fund_nav_empty_review_receipt",
        "status": f"round{manifest['review_round']}_review_executed",
        "review_round": manifest["review_round"],
        "manifest_sha256": manifest_sha256,
        "all_task_ids_sha256": manifest["all_task_ids_sha256"],
        "fixed_release_id": release_id,
        "fixed_release_manifest_sha256": expected_release_manifest_sha256,
        "authority_sha256": execution_authorities.pop(),
        "authority_config_sha256": expected_config_sha256,
        "code_sha256": expected_code_sha256,
        "outcome_counts": dict(sorted(counts.items())),
        "results": results,
        "upstream_calls": calls,
        "max_upstream_calls": max_requests,
        "max_seconds": max_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "operator_precondition": "host_stopped_beat_and_tushare_worker",
        "operator_precondition_verified_by_runner": False,
        "writer_exclusion": "nonblocking_shared_pipeline_lock",
        "task_identity_preserved": True,
        "empty_tasks_not_requeued": True,
        "release_published": False,
        "current_release_switched": False,
        "history_complete": False,
        "pit_verified": False,
    }
    receipt["receipt_id"] = digest(json_bytes(receipt))
    _write_receipt(output, receipt)
    return receipt


def run_review(
    manifest,
    manifest_sha256,
    *,
    root=None,
    release_root=None,
    release_id=None,
    expected_authority_sha256=None,
    expected_config_sha256=None,
    expected_code_sha256=None,
    expected_release_manifest_sha256=None,
    expected_task_ids_sha256=None,
    output=None,
    max_requests=MAX_UPSTREAM_REQUESTS,
    max_seconds=MAX_SECONDS,
    now=None,
    execute=False,
):
    if type(max_requests) is not int or not 2 <= max_requests <= MAX_UPSTREAM_REQUESTS:
        raise ValueError("Upstream request limit must be an integer from 2 to 360")
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise ValueError(
            "Wall-clock limit must be greater than 0 and at most 90 seconds"
        )
    current_code_sha256 = code_sha256()
    if expected_code_sha256 and expected_code_sha256 != current_code_sha256:
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
                        target, side_effect=AssertionError("Offline empty-review plan")
                    )
                )
            verified = verify_manifest(manifest, manifest_sha256)
        return {
            "schema_version": 1,
            "status": "plan_only",
            "review_round": verified["review_round"],
            "manifest_sha256": manifest_sha256,
            "all_task_ids_sha256": verified["all_task_ids_sha256"],
            "code_sha256": current_code_sha256,
            "paired_targets": len(verified["records"]),
            "required_upstream_calls": len(verified["records"]) * 2,
            "max_upstream_calls": max_requests,
            "max_seconds": max_seconds,
            "operator_precondition": "host_must_stop_beat_and_tushare_worker",
            "writer_exclusion": "nonblocking_shared_pipeline_lock",
            "would_access_authority": False,
            "would_access_credentials": False,
            "would_call_upstream": False,
            "would_publish": False,
        }
    values = (
        (expected_authority_sha256, "authority database hash"),
        (expected_config_sha256, "authority config hash"),
        (expected_code_sha256, "code hash"),
        (expected_release_manifest_sha256, "fixed release manifest hash"),
        (expected_task_ids_sha256, "task inventory hash"),
    )
    for value, label in values:
        _hash(value, label)
    verified = verify_manifest(manifest, manifest_sha256)
    if verified["all_task_ids_sha256"] != expected_task_ids_sha256:
        raise ValueError("Explicit task inventory hash mismatch")
    if root is None or release_root is None or release_id is None:
        raise ValueError("Execute requires authority root, fixed release root and ID")
    return _execute(
        manifest_sha256,
        verified,
        root=root,
        release_root=release_root,
        release_id=release_id,
        expected_authority_sha256=expected_authority_sha256,
        expected_config_sha256=expected_config_sha256,
        expected_code_sha256=expected_code_sha256,
        expected_release_manifest_sha256=expected_release_manifest_sha256,
        output=output,
        max_requests=max_requests,
        max_seconds=max_seconds,
        now=_time(now or datetime.now(timezone.utc), "execution time"),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--expected-authority-sha256")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-code-sha256")
    parser.add_argument("--expected-release-manifest-sha256")
    parser.add_argument("--expected-task-ids-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-requests", type=int, default=MAX_UPSTREAM_REQUESTS)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = run_review(
            args.manifest,
            args.manifest_sha256,
            root=args.root,
            release_root=args.release_root,
            release_id=args.release_id,
            expected_authority_sha256=args.expected_authority_sha256,
            expected_config_sha256=args.expected_config_sha256,
            expected_code_sha256=args.expected_code_sha256,
            expected_release_manifest_sha256=args.expected_release_manifest_sha256,
            expected_task_ids_sha256=args.expected_task_ids_sha256,
            output=args.output,
            max_requests=args.max_requests,
            max_seconds=args.max_seconds,
            execute=args.execute,
        )
    except (
        ValueError,
        OSError,
        sqlite3.Error,
        httpx.HTTPError,
        TimeoutError,
    ) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
