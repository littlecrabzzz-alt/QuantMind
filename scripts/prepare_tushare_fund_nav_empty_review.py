#!/usr/bin/env python3
"""Prepare a read-only paired review plan for empty fund_nav leaves."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys


API = "fund_nav"
EPOCH = "history"
ROUND1_MINIMUM_AGE_SECONDS = 24 * 60 * 60
ROUND2_MINIMUM_AGE_SECONDS = 7 * 24 * 60 * 60
MINIMUM_AGE_SECONDS = ROUND1_MINIMUM_AGE_SECONDS
MINIMUM_AGE_SECONDS_BY_ROUND = {
    1: ROUND1_MINIMUM_AGE_SECONDS,
    2: ROUND2_MINIMUM_AGE_SECONDS,
}
MAX_TARGETS = 360
BOUNDARIES = {
    "empty_semantics": (
        "Repeated empty responses prove only what the supplier returned at those "
        "observation times; they do not prove that historical NAV never existed."
    ),
    "lifecycle": (
        "Current fund lifecycle fields are context for choosing a positive control and "
        "never convert an empty NAV response into historical coverage."
    ),
    "point_in_time": (
        "fetched_at is this system's observation time; ann_date may be null and neither "
        "field proves when a value first became knowable."
    ),
    "closure": (
        "This plan changes no job or partition state. Empty review cannot produce the "
        "positive artifact evidence required by normal partition closure."
    ),
}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


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


def _stamp(value):
    return _time(value, "timestamp").isoformat()


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


def _stored(root, name, expected, pattern, label):
    if not isinstance(name, str) or not re.fullmatch(pattern, name):
        raise ValueError(f"Invalid {label} path")
    if (
        not isinstance(expected, dict)
        or set(expected) != {"sha256", "bytes"}
        or not re.fullmatch(r"[a-f0-9]{64}", str(expected.get("sha256", "")))
        or type(expected.get("bytes")) is not int
        or expected["bytes"] <= 0
    ):
        raise ValueError(f"Invalid {label} inventory")
    path = _regular(root / name, label)
    if path.resolve() != root / name or path.stat().st_size != expected["bytes"]:
        raise ValueError(f"{label} identity mismatch")
    if sha(path) != expected["sha256"]:
        raise ValueError(f"{label} hash mismatch")
    return path


def _valid_job(job):
    params = job.get("params") if isinstance(job, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("api_name") != API
        or not isinstance(params, dict)
        or set(params) != {"ts_code", "start_date", "end_date"}
        or not re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", str(params.get("ts_code", "")))
        or not re.fullmatch(r"[0-9]{8}", str(params.get("start_date", "")))
        or not re.fullmatch(r"[0-9]{8}", str(params.get("end_date", "")))
        or params["start_date"] > params["end_date"]
        or job.get("row_cap") != 1000
        or set(job.get("required_fields", ())) != {"ts_code", "nav_date"}
        or "ann_date" not in job.get("nullable_fields", ())
        or not {"ts_code", "nav_date", "ann_date"}.issubset(
            set(str(job.get("fields", "")).split(","))
        )
    ):
        raise ValueError("Invalid fund_nav history job")
    return params


def _release(root, release_id):
    if not re.fullmatch(r"data-[a-f0-9]{64}", release_id):
        raise ValueError("Invalid fixed release ID")
    path = _regular(root / "releases" / release_id / "manifest.json", "manifest")
    if path.resolve() != root / "releases" / release_id / "manifest.json":
        raise ValueError("Fixed release manifest path mismatch")
    raw = path.read_bytes()
    if digest(raw) != release_id.removeprefix("data-"):
        raise ValueError("Fixed release manifest hash mismatch")
    manifest = json.loads(raw)
    if not isinstance(manifest.get("files"), dict) or not isinstance(
        manifest.get("datasets"), list
    ):
        raise ValueError("Invalid fixed release manifest")
    return manifest


def _empty_evidence(root, job, result):
    if (
        not isinstance(result, dict)
        or result.get("api_name") != API
        or result.get("status") != "empty_unverified"
        or result.get("http_status") != 200
        or result.get("response_complete") is not True
        or result.get("response_format") != "json"
        or result.get("field_coverage") != "complete_for_explicit_request"
        or result.get("row_count") != 0
        or result.get("supplier_has_more") is True
        or result.get("missing_fields") not in (None, [])
    ):
        return None
    observation_name = result.get("observation")
    observation_sha = result.get("observation_sha256")
    object_sha = result.get("object_sha256")
    if (
        not re.fullmatch(r"[a-f0-9]{32}\.json", str(observation_name or ""))
        or not re.fullmatch(r"[a-f0-9]{64}", str(observation_sha or ""))
        or not re.fullmatch(r"[a-f0-9]{64}", str(object_sha or ""))
    ):
        raise ValueError("Empty result lacks immutable evidence")
    observation_path = _regular(
        root / "observations" / observation_name, "empty observation"
    )
    object_path = _regular(root / "objects" / f"{object_sha}.json", "empty object")
    if (
        observation_path.resolve() != root / "observations" / observation_name
        or object_path.resolve() != root / "objects" / f"{object_sha}.json"
    ):
        raise ValueError("Empty evidence path mismatch")
    observation_raw = observation_path.read_bytes()
    object_raw = object_path.read_bytes()
    if digest(observation_raw) != observation_sha or digest(object_raw) != object_sha:
        raise ValueError("Empty evidence hash mismatch")
    observation = json.loads(observation_raw)
    request = {key: job[key] for key in ("api_name", "params", "fields")}
    assessment = (
        observation.get("assessment") if isinstance(observation, dict) else None
    )
    if (
        not isinstance(observation, dict)
        or observation.get("request") != request
        or observation.get("object_sha256") != object_sha
        or not isinstance(assessment, dict)
    ):
        raise ValueError("Empty observation request mismatch")
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
        if assessment.get(key) != result.get(key):
            raise ValueError("Empty observation assessment mismatch")
    payload = json.loads(object_raw)
    data = payload.get("data") if isinstance(payload, dict) else None
    requested_fields = job["fields"].split(",")
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 0
        or not isinstance(data, dict)
        or data.get("items") != []
        or not set(requested_fields).issubset(data.get("fields", []))
    ):
        raise ValueError("Empty response object mismatch")
    fetched_at = _stamp(observation.get("fetched_at"))
    return {
        "observation": {
            "path": f"observations/{observation_name}",
            "sha256": observation_sha,
            "fetched_at": fetched_at,
        },
        "object": {
            "path": f"objects/{object_sha}.json",
            "sha256": object_sha,
        },
    }


def _sample_evidence(root, job, result):
    if (
        not isinstance(result, dict)
        or result.get("api_name") != API
        or result.get("status") != "sample_ok"
        or result.get("http_status") != 200
        or result.get("response_complete") is not True
        or result.get("response_format") != "json"
        or result.get("field_coverage") != "complete_for_explicit_request"
        or not result.get("row_count")
        or result.get("supplier_has_more") is True
        or result.get("missing_fields") not in (None, [])
    ):
        return None
    observation_name = result.get("observation")
    observation_sha = result.get("observation_sha256")
    object_sha = result.get("object_sha256")
    if (
        not re.fullmatch(r"[a-f0-9]{32}\.json", str(observation_name or ""))
        or not re.fullmatch(r"[a-f0-9]{64}", str(observation_sha or ""))
        or not re.fullmatch(r"[a-f0-9]{64}", str(object_sha or ""))
    ):
        raise ValueError("Control result lacks immutable evidence")
    observation_path = _regular(
        root / "observations" / observation_name, "round-one control observation"
    )
    object_path = _regular(
        root / "objects" / f"{object_sha}.json", "round-one control object"
    )
    if (
        observation_path.resolve() != root / "observations" / observation_name
        or object_path.resolve() != root / "objects" / f"{object_sha}.json"
    ):
        raise ValueError("Round-one control evidence path mismatch")
    observation_raw = observation_path.read_bytes()
    object_raw = object_path.read_bytes()
    if digest(observation_raw) != observation_sha or digest(object_raw) != object_sha:
        raise ValueError("Round-one control evidence hash mismatch")
    observation = json.loads(observation_raw)
    request = {key: job[key] for key in ("api_name", "params", "fields")}
    assessment = (
        observation.get("assessment") if isinstance(observation, dict) else None
    )
    if (
        not isinstance(observation, dict)
        or observation.get("request") != request
        or observation.get("object_sha256") != object_sha
        or not isinstance(assessment, dict)
    ):
        raise ValueError("Round-one control observation request mismatch")
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
        if assessment.get(key) != result.get(key):
            raise ValueError("Round-one control observation assessment mismatch")
    payload = json.loads(object_raw)
    data = payload.get("data") if isinstance(payload, dict) else None
    fields = data.get("fields") if isinstance(data, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    requested_fields = job["fields"].split(",")
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 0
        or not isinstance(fields, list)
        or not set(requested_fields).issubset(fields)
        or not isinstance(items, list)
        or not items
        or len(items) != result["row_count"]
    ):
        raise ValueError("Round-one control response object mismatch")
    try:
        rows = [dict(zip(fields, item, strict=True)) for item in items]
    except (TypeError, ValueError) as exc:
        raise ValueError("Round-one control response object mismatch") from exc
    params = job["params"]
    if not all(
        row.get("ts_code") == params["ts_code"]
        and params["start_date"]
        <= str(row.get("nav_date", "")).replace("-", "")
        <= params["end_date"]
        for row in rows
    ):
        raise ValueError("Round-one control row mismatch")
    return {
        "observation": {
            "path": f"observations/{observation_name}",
            "sha256": observation_sha,
            "fetched_at": _stamp(observation.get("fetched_at")),
        },
        "object": {
            "path": f"objects/{object_sha}.json",
            "sha256": object_sha,
        },
    }


def _round1_evidence(root, release_root, job, attempt, result):
    review = result.get("empty_review") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("api_name") != API
        or result.get("status") != "round1_valid_empty"
        or result.get("history_complete") is not False
        or result.get("pit_verified") is not False
        or not isinstance(review, dict)
        or review.get("schema_version") != 1
        or review.get("kind") != "fund_nav_empty_review"
        or review.get("review_round") != 1
        or review.get("retry_not_before") is not None
        or type(review.get("retry_index")) is not int
        or not 0 <= review["retry_index"] <= 2
    ):
        return None
    fixed_release_id = review.get("fixed_release_id")
    if not re.fullmatch(r"data-[a-f0-9]{64}", str(fixed_release_id or "")):
        raise ValueError("Round-one review has invalid fixed release identity")
    for key in (
        "manifest_sha256",
        "authority_sha256",
        "request_observation_sha256",
        "request_object_sha256",
        "control_observation_sha256",
        "control_object_sha256",
    ):
        if not re.fullmatch(r"[a-f0-9]{64}", str(review.get(key, ""))):
            raise ValueError("Round-one review lacks pinned evidence")
    fixed = _release(release_root, fixed_release_id)
    params = job["params"]
    control = _controls(
        release_root, fixed, {params["ts_code"]: params["end_date"]}
    ).get(params["ts_code"])
    if control is None:
        raise ValueError("Round-one fixed release lacks its positive control")
    request = _empty_evidence(root, job, result.get("request_result"))
    control_job = {**job, "params": control["request_params"]}
    positive = _sample_evidence(root, control_job, result.get("control_result"))
    if request is None or positive is None:
        raise ValueError("Round-one valid-empty evidence is not verifiable")
    expected = {
        "request_observation_sha256": request["observation"]["sha256"],
        "request_object_sha256": request["object"]["sha256"],
        "control_observation_sha256": positive["observation"]["sha256"],
        "control_object_sha256": positive["object"]["sha256"],
    }
    if any(review[key] != value for key, value in expected.items()):
        raise ValueError("Round-one review evidence hash mismatch")
    completed = max(
        _time(request["observation"]["fetched_at"], "round-one request fetched_at"),
        _time(positive["observation"]["fetched_at"], "round-one control fetched_at"),
    )
    return {
        "attempt": attempt,
        "manifest_sha256": review["manifest_sha256"],
        "fixed_release_id": fixed_release_id,
        **expected,
        "completed_at": completed.isoformat(),
    }


def _controls(root, manifest, code_end_dates):
    import pyarrow.parquet as pq

    if not code_end_dates:
        return {}
    candidates = {code: [] for code in code_end_dates}
    for dataset in sorted(
        manifest["datasets"], key=lambda item: str(item.get("path", ""))
    ):
        if (
            dataset.get("api_name") != API
            or dataset.get("quality_state") != "sample_ok"
        ):
            continue
        name = dataset.get("path")
        expected = manifest["files"].get(name)
        path = _stored(
            root,
            name,
            expected,
            r"parquet/[a-f0-9]{64}\.parquet",
            "control parquet",
        )
        if path.stem != expected["sha256"]:
            raise ValueError("Control parquet name/hash mismatch")
        table = pq.ParquetFile(path).read(
            columns=["ts_code", "nav_date", "ann_date", "_observation"]
        )
        for row in table.to_pylist():
            code = row.get("ts_code")
            nav_date = str(row.get("nav_date") or "").replace("-", "")
            observation = row.get("_observation")
            if (
                code in candidates
                and re.fullmatch(r"[0-9]{8}", nav_date)
                and nav_date > code_end_dates[code]
                and re.fullmatch(r"[a-f0-9]{32}\.json", str(observation or ""))
            ):
                ann_date = row.get("ann_date")
                candidates[code].append(
                    (
                        nav_date,
                        ""
                        if ann_date in (None, "")
                        else str(ann_date).replace("-", ""),
                        observation,
                        name,
                    )
                )
    controls = {}
    for code, rows in candidates.items():
        if not rows:
            continue
        nav_date, ann_date, observation_name, parquet_name = min(rows)
        observation_expected = manifest["files"].get("observations/" + observation_name)
        observation_path = _stored(
            root,
            "observations/" + observation_name,
            observation_expected,
            r"observations/[a-f0-9]{32}\.json",
            "control observation",
        )
        observation = json.loads(observation_path.read_bytes())
        request = observation.get("request") if isinstance(observation, dict) else None
        params = request.get("params") if isinstance(request, dict) else None
        assessment = (
            observation.get("assessment") if isinstance(observation, dict) else None
        )
        covered = bool(
            isinstance(params, dict)
            and params.get("ts_code") == code
            and (
                params.get("nav_date") == nav_date
                or (
                    str(params.get("start_date", ""))
                    <= nav_date
                    <= str(params.get("end_date", ""))
                )
            )
        )
        if (
            not isinstance(request, dict)
            or request.get("api_name") != API
            or not covered
            or not isinstance(assessment, dict)
            or assessment.get("status") != "sample_ok"
            or not assessment.get("row_count", 0)
        ):
            raise ValueError("Control observation does not prove the selected row")
        controls[code] = {
            "natural_key": {
                "ts_code": code,
                "nav_date": nav_date,
                "ann_date": ann_date or None,
            },
            "request_params": {
                "ts_code": code,
                "start_date": nav_date,
                "end_date": nav_date,
            },
            "source_observation": {
                "path": "observations/" + observation_name,
                "sha256": observation_expected["sha256"],
                "fetched_at": _stamp(observation.get("fetched_at")),
            },
            "source_parquet": {
                "path": parquet_name,
                **manifest["files"][parquet_name],
            },
        }
    return controls


def prepare(
    root,
    release_root,
    release_id,
    output=None,
    *,
    now=None,
    jobs=MAX_TARGETS,
    review_round=1,
):
    if type(jobs) is not int or not 0 <= jobs <= MAX_TARGETS:
        raise ValueError("jobs must be between 0 and 360")
    if (
        type(review_round) is not int
        or review_round not in MINIMUM_AGE_SECONDS_BY_ROUND
    ):
        raise ValueError("review_round must be 1 or 2")
    root = _root(root, "Authority root")
    release_root = _root(release_root, "Fixed release root")
    database = _regular(root / "pipeline.sqlite", "Pipeline database")
    fixed = _release(release_root, release_id)
    now = _time(now or datetime.now(timezone.utc), "as_of")
    candidates = []
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 6:
            raise ValueError("Pipeline schema must already be version 6")
        rows = db.execute(
            "SELECT DISTINCT j.* FROM jobs j "
            "JOIN partition_children c ON c.child_id=j.id "
            "JOIN partition_splits s ON s.parent_id=c.parent_id "
            "WHERE j.epoch=? AND json_extract(j.job,'$.api_name')=? "
            "AND j.state='empty' AND json_extract(j.result,'$.status')='empty_unverified' "
            "AND s.coverage_proven=1 AND s.status='gap' AND s.gap='child_not_verified' "
            "AND NOT EXISTS(SELECT 1 FROM partition_splits leaf WHERE leaf.parent_id=j.id) "
            "AND NOT EXISTS(SELECT 1 FROM partition_children pc "
            "JOIN partition_splits nested ON nested.parent_id=pc.child_id "
            "WHERE pc.parent_id=c.parent_id AND nested.status='gap') "
            "ORDER BY j.id",
            (EPOCH, API),
        ).fetchall()
        for row in rows:
            job = json.loads(row["job"])
            params = _valid_job(job)
            valid = []
            reviews = []
            for attempt in db.execute(
                "SELECT attempt,result FROM attempts WHERE job_id=? ORDER BY attempt",
                (row["id"],),
            ):
                result = json.loads(attempt["result"])
                evidence = _empty_evidence(root, job, result)
                if evidence:
                    valid.append((attempt["attempt"], evidence))
                review = (
                    result.get("empty_review") if isinstance(result, dict) else None
                )
                if isinstance(review, dict) and review.get("schema_version") == 1:
                    reviews.append((attempt["attempt"], result))
            if len(valid) != 1:
                continue
            current = json.loads(row["result"])
            if (
                current.get("observation")
                != Path(valid[0][1]["observation"]["path"]).name
            ):
                raise ValueError("Current empty result is not the first empty evidence")
            terminal = {
                "review_conflict",
                "manual_hold",
                "review_recovered_data",
                "round1_valid_empty" if review_round == 1 else "review_exhausted",
            }
            current_round = [
                result
                for _, result in reviews
                if result["empty_review"].get("review_round") == review_round
            ]
            if any(result.get("status") in terminal for result in current_round):
                continue
            round1 = [
                (attempt, result)
                for attempt, result in reviews
                if result.get("status") == "round1_valid_empty"
                and result["empty_review"].get("review_round") == 1
            ]
            if review_round == 1 and round1:
                continue
            if review_round == 2 and any(
                result["empty_review"].get("review_round") == 1
                and result.get("status")
                in {"review_conflict", "manual_hold", "review_recovered_data"}
                for _, result in reviews
            ):
                continue
            if review_round == 2 and len(round1) != 1:
                if len(round1) > 1:
                    raise ValueError(
                        "Target has multiple round-one valid-empty results"
                    )
                continue
            parents = sorted(
                parent[0]
                for parent in db.execute(
                    "SELECT c.parent_id FROM partition_children c "
                    "JOIN partition_splits s ON s.parent_id=c.parent_id "
                    "WHERE c.child_id=? AND s.coverage_proven=1 "
                    "AND s.status='gap' AND s.gap='child_not_verified'",
                    (row["id"],),
                )
            )
            logical = digest(json_bytes(job))
            if row["logical_key"] != logical or row["id"] != digest(
                json_bytes([logical, row["epoch"]])
            ):
                raise ValueError("Authority job identity mismatch")
            candidates.append(
                (
                    params["ts_code"],
                    row["id"],
                    {
                        "target": {
                            "task_id": row["id"],
                            "logical_key": row["logical_key"],
                            "epoch": row["epoch"],
                            "priority": row["priority"],
                            "group_name": row["group_name"],
                            "state": row["state"],
                            "tries": row["tries"],
                            "job": job,
                            "job_sha256": logical,
                        },
                        "parent_ids": parents,
                        "first_empty": {"attempt": valid[0][0], **valid[0][1]},
                        "review_round": review_round,
                    },
                    round1[0] if round1 else None,
                )
            )
    finally:
        db.close()
    code_end_dates = {}
    for code, _, record, _ in candidates:
        code_end_dates[code] = max(
            code_end_dates.get(code, ""), record["target"]["job"]["params"]["end_date"]
        )
    controls = _controls(release_root, fixed, code_end_dates)
    eligible = []
    for code, task_id, record, round1 in candidates:
        if code not in controls:
            continue
        record["control"] = controls[code]
        if review_round == 1:
            not_before = _time(
                record["first_empty"]["observation"]["fetched_at"],
                "first fetched_at",
            ) + timedelta(seconds=ROUND1_MINIMUM_AGE_SECONDS)
        else:
            attempt, result = round1
            pinned = _round1_evidence(
                root,
                release_root,
                record["target"]["job"],
                attempt,
                result,
            )
            if pinned is None:
                continue
            record["round1_valid_empty"] = pinned
            not_before = _time(
                pinned["completed_at"], "round-one completed_at"
            ) + timedelta(seconds=ROUND2_MINIMUM_AGE_SECONDS)
        record["not_before"] = not_before.isoformat()
        if now >= not_before:
            eligible.append((not_before, code, task_id, record))
    eligible.sort(key=lambda item: item[:3])
    records = [item[3] for item in eligible[:jobs]]
    task_ids = sorted(record["target"]["task_id"] for record in records)
    manifest = {
        "schema_version": 1,
        "kind": "fund_nav_empty_review_plan",
        "source": {"api_name": API, "epoch": EPOCH, "state": "empty"},
        "fixed_release": {
            "release_id": release_id,
            "manifest_sha256": release_id.removeprefix("data-"),
        },
        "review_round": review_round,
        "minimum_age_seconds": MINIMUM_AGE_SECONDS_BY_ROUND[review_round],
        "as_of": now.isoformat(),
        "eligible_targets": len(eligible),
        "selected_targets": len(records),
        "all_task_ids_sha256": digest(json_bytes(task_ids)),
        "boundaries": BOUNDARIES,
        "records": records,
    }
    if output is not None:
        requested_output = Path(output)
        if requested_output.is_symlink():
            raise ValueError("Output must not be a symlink")
        output = requested_output.resolve()
        if (
            output.exists()
            or output.is_symlink()
            or output == root
            or root in output.parents
            or output == release_root
            or release_root in output.parents
        ):
            raise ValueError("Output must not exist and must be outside input roots")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            target.write(json_bytes(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", default="-")
    parser.add_argument("--as-of")
    parser.add_argument("--jobs", type=int, default=MAX_TARGETS)
    parser.add_argument("--review-round", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    result = prepare(
        args.root,
        args.release_root,
        args.release_id,
        None if args.output == "-" else args.output,
        now=args.as_of,
        jobs=args.jobs,
        review_round=args.review_round,
    )
    if args.output == "-":
        sys.stdout.buffer.write(json_bytes(result))
    else:
        print(
            json.dumps(
                {
                    "status": "prepared_not_executed",
                    "review_round": result["review_round"],
                    "eligible_targets": result["eligible_targets"],
                    "selected_targets": result["selected_targets"],
                    "manifest_sha256": sha(args.output),
                    "all_task_ids_sha256": result["all_task_ids_sha256"],
                    "would_access_credentials": False,
                    "would_call_upstream": False,
                    "would_change_task_state": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
