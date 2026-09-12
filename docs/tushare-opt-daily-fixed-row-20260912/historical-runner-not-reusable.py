#!/usr/bin/env python3
"""Hash-pinned one-call opt_daily evidence runner; plan-only by default."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

import httpx

REPO = Path(__file__).resolve().parents[1]
if not (REPO / "backend").is_dir():
    REPO = Path.cwd()
sys.path.insert(0, str(REPO))

from backend.shared import tushare_pipeline as pipeline_module  # noqa: E402
from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_registry import contract_for  # noqa: E402

API = "opt_daily"
GROUP = "other"
MAX_REQUESTS = 1
MAX_SECONDS = 30
MIN_FREE_BYTES = 100 * 2**30
EXPECTED_CANDIDATE_SHA256 = (
    "e1712d95174459913646f6a8f5b24241d88842a75e02ed865b5f8fa21be7560d"
)
CODE_BASIS_COMMIT = "d61e93d62380afcc221369ebc317a138d0e8cc9a"
CODE_SHA256 = {
    "backend/shared/tushare_pipeline.py": "e086d0b9bdce687149ff2b73f6ccbc4e05a137c9508bb90bab958944153eb518",
    "backend/shared/tushare_rate_policy.py": "83b9e6adc23cb84431a118af652e7a4cf5c5cc25b3f787df1f89d06cc0495fa8",
    "backend/shared/tushare_daily_quota.py": "b367310476d7adc077a41bf35903fd6f3779bbf4b5331c9a495b895aa68b6e75",
    "backend/shared/tushare_registry.py": "17cd7c97752859f783684b1ba93dc4fe138a256a76981cdddfcbbe370039a788",
    "backend/shared/tushare_other_contracts.py": "1d841065a415ceb7869ce4d79f72704c06fd74677b13a42e69c7f060e32bf39b",
    "config/tushare-catalog.json": "f15ffc774000e3bd4b049b130e264a4399e080f100cd73012252250a69cc460b",
}
EXPECTED_CURRENT = {
    "manifest_sha256": "de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0",
    "release_id": "data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0",
}
EXPECTED_CURRENT_SHA256 = (
    "d47619bf57d327539914694cfdeb0724f7474cbdec02d953357f2a7c9a2ea0bc"
)
# Attempt 236094 is independently verified and included in de494. Scanning the
# rowid tail catches every later attempt without touching the old attempts set.
ATTEMPT_WATERMARK = 236094
WATERMARK_JOB_ID = "8d98620659ec90a01a39c40c0ee1aa353cdd18bfaf2a7564a1379c7047ea5209"
WATERMARK_ATTEMPT = 4
MAX_ATTEMPT_TAIL = 10000
SHA_RE = re.compile(r"[a-f0-9]{64}")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def code_pins() -> None:
    for locator, expected in CODE_SHA256.items():
        if sha(regular(REPO / locator, locator)) != expected:
            raise ValueError(f"Pinned d61e93d6 code changed: {locator}")


def verify_candidate(path: Path, expected_sha256: str) -> dict:
    if expected_sha256 != EXPECTED_CANDIDATE_SHA256:
        raise ValueError("Unexpected candidate SHA-256")
    path = regular(path, "candidate")
    if sha(path) != expected_sha256:
        raise ValueError("Candidate SHA-256 mismatch")
    value = json.loads(path.read_bytes())
    candidate = value.get("candidate")
    if (
        value.get("schema_version") != 1
        or value.get("status") != "preparation_only_not_authorized_for_execution"
        or not isinstance(candidate, dict)
        or candidate.get("api_name") != API
        or candidate.get("group_name") != GROUP
        or candidate.get("params")
        != {"ts_code": "HO2609-C-2500.CFX", "trade_date": "20260911"}
        or candidate.get("max_upstream_calls") != MAX_REQUESTS
        or candidate.get("max_seconds") != MAX_SECONDS
        or candidate.get("publish") is not False
    ):
        raise ValueError("Candidate scope changed")
    spec = contract_for(API)
    job = {
        key: candidate[key]
        for key in (
            "api_name",
            "params",
            "fields",
            "row_cap",
            "required_fields",
            "nullable_fields",
            "positive_fields",
        )
    }
    logical = digest(json_bytes(job))
    task_id = digest(json_bytes([logical, candidate["epoch"]]))
    if (
        candidate.get("fields")
        != ",".join(sorted(set(spec["extra_fields"]) | set(spec["required_fields"])))
        or candidate.get("row_cap") != spec["row_cap"]
        or candidate.get("required_fields") != spec["required_fields"]
        or candidate.get("nullable_fields") != spec["nullable_fields"]
        or candidate.get("positive_fields") != spec["positive_fields"]
        or candidate.get("logical_key") != logical
        or candidate.get("task_id_for_candidate_epoch") != task_id
        or candidate.get("priority") != 10
    ):
        raise ValueError("Candidate contract or identity changed")
    return {"manifest": value, "candidate": candidate, "job": job}


def create_only_json(path: Path, value: dict) -> tuple[int, str]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink() or path.parent.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {path}")
    body = json_bytes(value)
    descriptor, name = tempfile.mkstemp(prefix=".opt-daily-one-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return len(body), digest(body)


def _task_id(logical_key: str, epoch: str) -> str:
    return digest(json_bytes([logical_key, epoch]))


def _row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "logical_key": row["logical_key"],
        "epoch": row["epoch"],
        "job": json.loads(row["job"]),
        "priority": row["priority"],
        "state": row["state"],
        "tries": row["tries"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "group_name": row["group_name"],
    }


def inspect_duplicates(
    db: sqlite3.Connection, job: dict, candidate: dict, config: dict
) -> dict:
    """Use task PKs, the pending API index, and the post-de494 attempt rowid tail."""
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=2000")
    if db.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise ValueError("Authority pipeline schema must be version 6")
    indexes = {row[1] for row in db.execute("PRAGMA index_list('jobs')")}
    if "jobs_ready_api_history" not in indexes:
        raise ValueError("Required pending API index is missing")
    anchor = db.execute(
        "SELECT rowid FROM attempts WHERE job_id=? AND attempt=?",
        (WATERMARK_JOB_ID, WATERMARK_ATTEMPT),
    ).fetchone()
    if anchor is None or anchor[0] != ATTEMPT_WATERMARK:
        raise ValueError("de494 attempt watermark anchor changed")
    max_attempt_rowid = db.execute("SELECT MAX(rowid) FROM attempts").fetchone()[0]
    max_attempt_rowid = max_attempt_rowid or ATTEMPT_WATERMARK
    if (
        max_attempt_rowid < ATTEMPT_WATERMARK
        or max_attempt_rowid - ATTEMPT_WATERMARK > MAX_ATTEMPT_TAIL
    ):
        return {
            "action": "blocked_attempt_tail_bound",
            "upstream_calls": 0,
            "attempt_watermark": ATTEMPT_WATERMARK,
            "max_attempt_rowid": max_attempt_rowid,
        }

    logical = digest(json_bytes(job))
    epochs = {candidate["epoch"], "history"}
    planning_epoch = config.get("planning_epoch")
    if planning_epoch is None:
        planning_epoch = datetime.now(timezone.utc).strftime("%Y%m%d")
    if not isinstance(planning_epoch, str) or not 1 <= len(planning_epoch) <= 128:
        raise ValueError("Invalid planning_epoch")
    epochs.add(planning_epoch)
    ids = {_task_id(logical, epoch): epoch for epoch in epochs}

    pk_rows = []
    for task_id, epoch in sorted(ids.items()):
        saved = db.execute(
            "SELECT id,logical_key,epoch,job,priority,state,tries,result,group_name "
            "FROM jobs WHERE id=?",
            (task_id,),
        ).fetchone()
        if saved is not None:
            parsed = _row(saved)
            if parsed["logical_key"] != logical or parsed["epoch"] != epoch:
                raise ValueError("Deterministic task primary key collision")
            pk_rows.append(parsed)

    plan = " ".join(
        str(row[-1])
        for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM jobs INDEXED BY jobs_ready_api_history "
            "WHERE state='pending' AND group_name=? "
            "AND json_extract(job,'$.api_name')=? AND (epoch='history')=1 "
            "AND json_extract(job,'$.params.ts_code')=? "
            "AND json_extract(job,'$.params.trade_date')=? LIMIT 3",
            (GROUP, API, job["params"]["ts_code"], job["params"]["trade_date"]),
        )
    )
    if "jobs_ready_api_history" not in plan:
        raise ValueError("Pending semantic lookup did not use the reviewed index")
    deadline = time.monotonic() + 2
    db.set_progress_handler(
        lambda: 1 if time.monotonic() > deadline else 0,
        1000,
    )
    try:
        history_rows = [
            _row(row)
            for row in db.execute(
                "SELECT id,logical_key,epoch,job,priority,state,tries,result,group_name "
                "FROM jobs INDEXED BY jobs_ready_api_history "
                "WHERE state='pending' AND group_name=? "
                "AND json_extract(job,'$.api_name')=? AND (epoch='history')=1 "
                "AND json_extract(job,'$.params.ts_code')=? "
                "AND json_extract(job,'$.params.trade_date')=? LIMIT 3",
                (GROUP, API, job["params"]["ts_code"], job["params"]["trade_date"]),
            )
        ]
    except sqlite3.OperationalError as error:
        if "interrupted" not in str(error).lower():
            raise
        return {
            "action": "blocked_pending_history_scan_timeout",
            "upstream_calls": 0,
            "attempt_watermark": ATTEMPT_WATERMARK,
            "max_attempt_rowid": max_attempt_rowid,
            "query_plan": plan,
        }
    finally:
        db.set_progress_handler(None, 0)

    tail_plan = " ".join(
        str(row[-1])
        for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT a.rowid FROM attempts a JOIN jobs j ON j.id=a.job_id "
            "WHERE a.rowid>? AND json_extract(j.job,'$.api_name')=? "
            "AND json_extract(j.job,'$.params.ts_code')=? "
            "AND json_extract(j.job,'$.params.trade_date')=?",
            (
                ATTEMPT_WATERMARK,
                API,
                job["params"]["ts_code"],
                job["params"]["trade_date"],
            ),
        )
    )
    if (
        "INTEGER PRIMARY KEY" not in tail_plan
        or "sqlite_autoindex_jobs_1" not in tail_plan
    ):
        raise ValueError("Attempt tail lookup is not bounded by rowid and job PK")
    tail_attempts = [
        {
            "attempt_rowid": row["attempt_rowid"],
            "attempt": row["attempt"],
            "task": _row(row),
            "attempt_result": json.loads(row["attempt_result"]),
        }
        for row in db.execute(
            "SELECT a.rowid AS attempt_rowid,a.attempt,a.result AS attempt_result,"
            "j.id,j.logical_key,j.epoch,j.job,j.priority,j.state,j.tries,j.result,j.group_name "
            "FROM attempts a JOIN jobs j ON j.id=a.job_id "
            "WHERE a.rowid>? AND json_extract(j.job,'$.api_name')=? "
            "AND json_extract(j.job,'$.params.ts_code')=? "
            "AND json_extract(j.job,'$.params.trade_date')=? ORDER BY a.rowid",
            (
                ATTEMPT_WATERMARK,
                API,
                job["params"]["ts_code"],
                job["params"]["trade_date"],
            ),
        )
    ]
    pk_attempts = []
    for saved in pk_rows:
        for attempt in db.execute(
            "SELECT rowid,attempt,result FROM attempts WHERE job_id=? ORDER BY attempt",
            (saved["id"],),
        ):
            pk_attempts.append(
                {
                    "attempt_rowid": attempt["rowid"],
                    "attempt": attempt["attempt"],
                    "task": saved,
                    "attempt_result": json.loads(attempt["result"]),
                }
            )
    attempts = {
        (item["task"]["id"], item["attempt"]): item
        for item in pk_attempts + tail_attempts
    }
    if attempts:
        selected = max(attempts.values(), key=lambda item: item["attempt_rowid"])
        exact_contract = selected["task"]["job"] == job
        return {
            "action": "reuse_without_http"
            if exact_contract
            else "reuse_contract_drift_blocked",
            "upstream_calls": 0,
            "attempt_watermark": ATTEMPT_WATERMARK,
            "max_attempt_rowid": max_attempt_rowid,
            "task": selected["task"],
            "attempt": selected["attempt"],
            "attempt_rowid": selected["attempt_rowid"],
            "result": selected["attempt_result"],
            "exact_contract": exact_contract,
        }

    pending = {
        row["id"]: row for row in pk_rows + history_rows if row["state"] == "pending"
    }
    drift = [row for row in pending.values() if row["job"] != job]
    pristine = [
        row
        for row in pending.values()
        if row["job"] == job and row["tries"] == 0 and row["result"] is None
    ]
    if drift:
        return {"action": "blocked_pending_contract_drift", "upstream_calls": 0}
    if len(pristine) > 1:
        return {"action": "blocked_multiple_pristine_duplicates", "upstream_calls": 0}
    if pristine:
        return {
            "action": "use_existing_pristine",
            "upstream_calls": 0,
            "task": pristine[0],
            "attempt_watermark": ATTEMPT_WATERMARK,
            "max_attempt_rowid": max_attempt_rowid,
        }
    terminal_without_attempt = [row for row in pk_rows if row["state"] != "pending"]
    if terminal_without_attempt:
        return {"action": "blocked_terminal_without_attempt", "upstream_calls": 0}
    return {
        "action": "enqueue_candidate_epoch",
        "upstream_calls": 0,
        "candidate_task_id": candidate["task_id_for_candidate_epoch"],
        "attempt_watermark": ATTEMPT_WATERMARK,
        "max_attempt_rowid": max_attempt_rowid,
        "query_plan": {"pending": plan, "attempt_tail": tail_plan},
    }


def validate_capture(root: Path, result: dict | None, job: dict) -> dict:
    validation = {
        "physical_sha256_verified": True,
        "explicit_schema_complete": False,
        "returned_scope_exact": False,
        "natural_key_unique": False,
        "history_complete": False,
        "pit_verified": False,
        "errors": [],
    }
    if not result:
        validation["physical_sha256_verified"] = False
        validation["errors"].append("missing_result")
        return validation
    object_sha = result.get("object_sha256")
    observation_name = result.get("observation")
    observation_sha = result.get("observation_sha256")
    if not SHA_RE.fullmatch(str(object_sha or "")):
        validation["physical_sha256_verified"] = False
        validation["errors"].append("missing_object_reference")
        return validation
    object_path = regular(root / "objects" / f"{object_sha}.json", "raw object")
    object_body = object_path.read_bytes()
    if digest(object_body) != object_sha:
        raise ValueError("Raw object SHA-256 mismatch")
    if not re.fullmatch(
        r"[a-f0-9]{32}\.json", str(observation_name or "")
    ) or not SHA_RE.fullmatch(str(observation_sha or "")):
        raise ValueError("Invalid observation reference")
    observation_path = regular(root / "observations" / observation_name, "observation")
    if sha(observation_path) != observation_sha:
        raise ValueError("Observation SHA-256 mismatch")
    observation = json.loads(observation_path.read_bytes())
    expected_request = {
        "api_name": API,
        "params": job["params"],
        "fields": job["fields"],
    }
    if observation.get("request") != expected_request:
        validation["errors"].append("observation_request_mismatch")
    payload = json.loads(object_body)
    data = payload.get("data") if payload.get("code") == 0 else None
    if not isinstance(data, dict):
        validation["errors"].append("supplier_response_has_no_data_table")
        return validation
    fields, items = data.get("fields"), data.get("items")
    if not isinstance(fields, list) or not isinstance(items, list):
        validation["errors"].append("invalid_data_table")
        return validation
    missing = sorted(set(job["fields"].split(",")) - set(fields))
    validation["explicit_schema_complete"] = not missing
    if missing:
        validation["errors"].append("missing_fields:" + ",".join(missing))
    try:
        code_index, date_index = fields.index("ts_code"), fields.index("trade_date")
        keys = [(row[code_index], row[date_index]) for row in items]
        validation["returned_scope_exact"] = all(
            key == (job["params"]["ts_code"], job["params"]["trade_date"])
            for key in keys
        )
        validation["natural_key_unique"] = len(keys) == len(set(keys))
    except (ValueError, IndexError, TypeError):
        validation["errors"].append("unreadable_natural_key")
    if not validation["returned_scope_exact"]:
        validation["errors"].append("returned_scope_mismatch")
    if not validation["natural_key_unique"]:
        validation["errors"].append("duplicate_natural_key")
    part = result.get("parquet")
    if part is not None:
        if not isinstance(part, dict) or not re.fullmatch(
            r"parquet/[a-f0-9]{64}\.parquet", str(part.get("path", ""))
        ):
            raise ValueError("Invalid parquet reference")
        parquet_path = regular(root / part["path"], "parquet")
        if parquet_path.stat().st_size != part.get("bytes") or sha(
            parquet_path
        ) != part.get("sha256"):
            raise ValueError("Parquet physical evidence mismatch")
    return validation


def _archive(
    args,
    candidate_sha: str,
    config_sha: str,
    decision: dict,
    result: dict | None,
    run: dict | None,
    root: Path,
) -> dict:
    validation = validate_capture(
        root, result, decision.get("task", {}).get("job") or args.job
    )
    calls = 0 if run is None else run["requests"]
    promoted = (
        result is not None
        and result.get("status") == "sample_ok"
        and result.get("row_count", 0) > 0
        and result.get("response_complete") is True
        and not validation["errors"]
    )
    report = {
        "schema_version": 1,
        "status": "opt_daily_exact_sample_validated"
        if promoted
        else "opt_daily_exact_sample_retained_blocked",
        "candidate_sha256": candidate_sha,
        "runner_sha256": args.expected_runner_sha256,
        "code_basis_commit": CODE_BASIS_COMMIT,
        "code_sha256": CODE_SHA256,
        "authority_config_sha256": config_sha,
        "current": EXPECTED_CURRENT,
        "current_pointer_sha256": EXPECTED_CURRENT_SHA256,
        "decision": {
            key: value
            for key, value in decision.items()
            if key not in {"result", "task"}
        },
        "task": {
            key: decision["task"][key]
            for key in (
                "id",
                "logical_key",
                "epoch",
                "priority",
                "state",
                "tries",
                "group_name",
            )
        }
        if decision.get("task")
        else None,
        "actual_upstream_calls": calls,
        "max_upstream_calls": MAX_REQUESTS,
        "elapsed_seconds": None if run is None else run["elapsed_seconds"],
        "result": result,
        "validation": validation,
        "automatic_enablement_permitted": False,
        "configuration_changed": False,
        "release_published": False,
        "history_complete": False,
        "historical_versions_complete": False,
        "pit_verified": False,
        "option_universe_complete": False,
    }
    report_bytes, report_sha = create_only_json(Path(args.report), report)
    receipt = {
        "schema_version": 1,
        "status": report["status"],
        "candidate_sha256": candidate_sha,
        "runner_sha256": args.expected_runner_sha256,
        "report": Path(args.report).name,
        "report_bytes": report_bytes,
        "report_sha256": report_sha,
        "upstream_calls": calls,
        "configuration_changed": False,
        "release_published": False,
    }
    create_only_json(Path(args.receipt), receipt)
    return receipt


def execute(args, verified: dict) -> dict:
    root = Path(args.root)
    if root.is_symlink() or root.resolve() != pipeline_module.ROOT.resolve():
        raise ValueError("Execute root is not configured authority")
    root = root.resolve()
    pipeline_module.authority()
    regular(root / "ENABLED", "enable marker")
    lock_path = regular(root / "pipeline.lock", "pipeline lock")
    if sha(Path(__file__)) != args.expected_runner_sha256:
        raise ValueError("Runner SHA-256 mismatch")
    validation_root = (root / "validation").resolve()
    outputs = (Path(args.report), Path(args.receipt))
    if outputs[0].resolve() == outputs[1].resolve():
        raise ValueError("Report and receipt must be distinct")
    for output in outputs:
        resolved = output.resolve()
        if validation_root not in resolved.parents:
            raise ValueError("Execution outputs must be inside authority validation")
    if Path(args.report).exists() or Path(args.receipt).exists():
        raise FileExistsError("Fresh report and receipt paths are required")
    descriptor = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(root).free < MIN_FREE_BYTES:
            return {"status": "blocked_disk_reserve", "upstream_calls": 0}
        config_path = regular(root / "pipeline-config.json", "pipeline config")
        pointer_path = regular(root / "CURRENT.json", "CURRENT pointer")
        config_bytes, pointer_bytes = (
            config_path.read_bytes(),
            pointer_path.read_bytes(),
        )
        config_sha = digest(config_bytes)
        if config_sha != args.expected_config_sha256:
            raise ValueError("Authority config SHA-256 mismatch")
        if (
            digest(pointer_bytes) != EXPECTED_CURRENT_SHA256
            or json.loads(pointer_bytes) != EXPECTED_CURRENT
        ):
            raise ValueError("CURRENT is not pinned de494")
        config = json.loads(config_bytes)
        database = regular(root / "pipeline.sqlite", "pipeline database")
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            decision = inspect_duplicates(
                db, verified["job"], verified["candidate"], config
            )
        finally:
            db.close()
        if (
            decision["action"].startswith("blocked_")
            or decision["action"] == "reuse_contract_drift_blocked"
        ):
            args.job = verified["job"]
            return _archive(
                args,
                EXPECTED_CANDIDATE_SHA256,
                config_sha,
                decision,
                decision.get("result"),
                None,
                root,
            )
        if decision["action"] == "reuse_without_http":
            args.job = verified["job"]
            return _archive(
                args,
                EXPECTED_CANDIDATE_SHA256,
                config_sha,
                decision,
                decision["result"],
                None,
                root,
            )

        pipeline = pipeline_module.Pipeline(
            root, json.loads((REPO / "config/tushare-catalog.json").read_bytes())
        )
        pipeline.db.execute("PRAGMA busy_timeout=2000")
        try:
            selected = decision.get("task")
            if selected is None:
                with pipeline.db:
                    task_id = pipeline.enqueue(
                        API,
                        verified["candidate"]["params"],
                        verified["candidate"]["priority"],
                        verified["candidate"]["epoch"],
                    )
                if task_id != verified["candidate"]["task_id_for_candidate_epoch"]:
                    raise ValueError("Pipeline enqueue identity mismatch")
                row = pipeline.db.execute(
                    "SELECT id,logical_key,epoch,job,priority,state,tries,result,group_name "
                    "FROM jobs WHERE id=?",
                    (task_id,),
                ).fetchone()
                selected = _row(row)
                decision["task"] = selected
            if (
                selected["job"] != verified["job"]
                or selected["state"] != "pending"
                or selected["tries"] != 0
                or selected["result"] is not None
                or pipeline.db.execute(
                    "SELECT 1 FROM attempts WHERE job_id=? LIMIT 1", (selected["id"],)
                ).fetchone()
            ):
                raise ValueError("Selected task is not pristine")
            token = pipeline_module.get_secret("TUSHARE_TOKEN")
            if not token:
                return {"status": "blocked_missing_token", "upstream_calls": 0}

            def exact_status():
                row = pipeline.db.execute(
                    "SELECT state,COUNT(*) FROM jobs WHERE id=? GROUP BY state",
                    (selected["id"],),
                ).fetchone()
                return {} if row is None else {row[0]: row[1]}

            pipeline.status = exact_status
            with httpx.Client(
                trust_env=False,
                timeout=min(30, args.max_seconds),
                follow_redirects=False,
            ) as client:
                run = pipeline.run(
                    client,
                    token,
                    config,
                    max_requests=MAX_REQUESTS,
                    max_seconds=args.max_seconds,
                    pause=0,
                    task_ids=[selected["id"]],
                )
            row = pipeline.db.execute(
                "SELECT id,logical_key,epoch,job,priority,state,tries,result,group_name "
                "FROM jobs WHERE id=?",
                (selected["id"],),
            ).fetchone()
            final_task = _row(row)
            decision["task"] = final_task
            result = final_task["result"]
            if run["requests"] != 1 or result is None:
                return {
                    "status": "deferred_without_evidence",
                    "upstream_calls": run["requests"],
                    "task_id": selected["id"],
                }
            if (
                config_path.read_bytes() != config_bytes
                or pointer_path.read_bytes() != pointer_bytes
            ):
                raise RuntimeError(
                    "Authority config or CURRENT changed while lock held"
                )
        finally:
            pipeline.close()
        args.job = verified["job"]
        return _archive(
            args,
            EXPECTED_CANDIDATE_SHA256,
            config_sha,
            decision,
            result,
            run,
            root,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-runner-sha256")
    parser.add_argument("--report")
    parser.add_argument("--receipt")
    parser.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    args = parser.parse_args()
    with ExitStack() as guards:
        if not args.execute:
            for target in (
                "socket.socket.connect",
                "socket.getaddrinfo",
                "backend.shared.tushare_pipeline.get_secret",
                "backend.shared.runtime_secrets.get_secret",
            ):
                guards.enter_context(
                    patch(target, side_effect=AssertionError("Offline opt_daily plan"))
                )
        code_pins()
        verified = verify_candidate(args.candidate, args.candidate_sha256)
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "plan_only",
                    "candidate_sha256": args.candidate_sha256,
                    "code_basis_commit": CODE_BASIS_COMMIT,
                    "expected_current": EXPECTED_CURRENT,
                    "expected_current_sha256": EXPECTED_CURRENT_SHA256,
                    "request": verified["job"],
                    "candidate_task_id": verified["candidate"][
                        "task_id_for_candidate_epoch"
                    ],
                    "history_task_id": _task_id(
                        verified["candidate"]["logical_key"], "history"
                    ),
                    "attempt_watermark": ATTEMPT_WATERMARK,
                    "max_upstream_calls": MAX_REQUESTS,
                    "would_access_authority": False,
                    "would_access_credentials": False,
                    "would_call_upstream": False,
                    "would_publish": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return
    if (
        not all(
            (
                args.root,
                args.expected_config_sha256,
                args.expected_runner_sha256,
                args.report,
                args.receipt,
            )
        )
        or not SHA_RE.fullmatch(args.expected_config_sha256)
        or not SHA_RE.fullmatch(args.expected_runner_sha256)
        or not 1 <= args.max_seconds <= MAX_SECONDS
    ):
        raise ValueError(
            "Execute requires all SHA pins, outputs, and max-seconds 1..30"
        )
    print(json.dumps(execute(args, verified), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
