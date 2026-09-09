#!/usr/bin/env python3
"""Read-only fixed-release realtime audit. No Pipeline, secrets, HTTP or enable."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import sysconfig

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


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_checks(api, params, rows, slot):
    from backend.shared.tushare_registry import REALTIME_RUNTIME_CONTRACTS

    spec = REALTIME_RUNTIME_CONTRACTS[api]
    failures = Counter()
    wanted_day = (
        datetime.strptime(slot, "%Y%m%dT%H%M%SZ") + timedelta(hours=8)
    ).strftime("%Y%m%d")
    for row in rows:
        code = row.get(spec["source_code_field"])
        if params.get("ts_code") and code != params["ts_code"]:
            failures["source_code"] += 1
        if "freq" in spec["fields"] and row.get("freq") != params.get("freq"):
            failures["source_freq"] += 1
        raw_time = row.get(spec["date_field"])
        stamp = None
        if isinstance(raw_time, str):
            for pattern in (
                ("%Y%m%d",)
                if api == "stk_auction"
                else ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
            ):
                try:
                    stamp = datetime.strptime(raw_time, pattern)
                    break
                except ValueError:
                    pass
        if stamp is None:
            failures["source_time_format"] += 1
            continue
        day = stamp.strftime("%Y%m%d")
        if api == "stk_auction":
            if "trade_date" in params and day != params["trade_date"]:
                failures["source_trade_date"] += 1
            if (
                "start_date" in params
                and not params["start_date"] <= day <= params["end_date"]
            ):
                failures["source_range"] += 1
        elif day != wanted_day:
            failures["snapshot_source_date_component"] += 1
    return dict(failures)


def expected_code(api, raw, params):
    if api == "stk_auction":
        kind = params.get("ts_type") or "AUCTION_UNTYPED"
    else:
        kind = (
            "STK"
            if api == "rt_k"
            else "ETF"
            if "etf" in api
            else "FUT"
            if "fut" in api
            else "IDX"
        )
    if kind == "STK" and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", raw):
        code, exchange = raw.rsplit(".", 1)
        return exchange + code
    return {"ETF": "FUND", "STK": "STK_UNVERIFIED"}.get(kind, kind) + ":" + raw


def audit(args):
    import pyarrow.parquet as pq
    from backend.shared.tushare_pipeline import manifest_at
    from backend.shared.tushare_registry import REALTIME_RUNTIME_CONTRACTS
    from backend.shared.tushare_intake import json_bytes
    from backend.shared.tushare_realtime_extra_contracts import CODE_PATTERNS
    from backend.shared.tushare_store import read_dataset, dataset_schema

    if not 1 <= args.max_rows <= 100000 or not 1 <= args.max_partitions <= 200:
        raise ValueError("Explicit fixed audit bounds required")
    if args.report.is_symlink() or args.report.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Unsafe/oversized probe report")
    body = args.report.read_bytes()
    report = json.loads(body)
    slot = report["snapshot_slot"]
    if not isinstance(slot, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", slot):
        raise ValueError("Invalid immutable snapshot slot")
    datetime.strptime(slot, "%Y%m%dT%H%M%SZ")
    planned = report["planned_requests"]
    samples = report["results"]
    if len(planned) != 15 or Counter(s["api_name"] for s in planned) != Counter(
        {a: 6 if a == "stk_auction" else 1 for a in APIS}
    ):
        raise ValueError("Unexpected bounded probe plan")
    variants = Counter()
    minute_apis = {"rt_idx_min", "rt_fut_min", "rt_idx_min_daily", "rt_fut_min_daily"}
    for item in planned:
        api, params = item["api_name"], item["params"]
        if api == "stk_auction":
            axis = "day" if "trade_date" in params else "range"
            allowed = (
                {"ts_code", "trade_date"}
                if axis == "day"
                else {"ts_code", "start_date", "end_date"}
            )
            if set(params) - {"ts_type"} != allowed or params.get("ts_type") not in (
                None,
                "STK",
                "ETF",
            ):
                raise ValueError("Unexpected auction variant identity")
            variants[(axis, params.get("ts_type"))] += 1
        elif set(params) != (
            {"ts_code", "freq"} if api in minute_apis else {"ts_code"}
        ) or (api in minute_apis and params["freq"] != "1MIN"):
            raise ValueError("Current-only single-code 1MIN plan required")
        family = (
            "etfs"
            if "etf" in api or params.get("ts_type") == "ETF"
            else "stocks"
            if api in ("stk_auction", "rt_k")
            else "minute_futures"
            if "fut" in api
            else "sw_indexes"
            if api == "rt_sw_k"
            else "indexes"
        )
        if not isinstance(params["ts_code"], str) or not re.fullmatch(
            CODE_PATTERNS[family], params["ts_code"]
        ):
            raise ValueError("Unexpected source code namespace")
    if variants != Counter(
        {(axis, kind): 1 for axis in ("day", "range") for kind in (None, "STK", "ETF")}
    ):
        raise ValueError("All auction date/type variants required")
    identities = {canonical((s["api_name"], s["params"])) for s in planned}
    if (
        len(identities) != len(planned)
        or len({canonical((s["api_name"], s["params"])) for s in samples})
        != len(samples)
        or any(
            canonical((s["api_name"], s["params"])) not in identities for s in samples
        )
    ):
        raise ValueError("Probe sample identity does not match frozen plan")
    if (
        report.get("actual_upstream_calls", 16) > 15
        or report.get("replay_scope") != "current_only"
        or report.get("frequencies_tested") != ["1MIN"]
    ):
        raise ValueError("Probe bound or current-only scope mismatch")
    manifest = manifest_at(args.root, args.release_id)
    checked_paths, objects, sources = set(), {}, {}
    gaps, sample_checks, dataset_checks = [], [], []
    total_rows, source_bytes = 0, 0
    raw_maps = {}

    def checked(name):
        if not re.fullmatch(
            r"(objects|observations|parquet)/[a-f0-9]{32,64}\.(json|parquet)", name
        ):
            raise ValueError("Invalid evidence path")
        expected = manifest["files"][name]
        path = args.root / name
        if (
            path.is_symlink()
            or path.parent.is_symlink()
            or path.resolve().parent != args.root.resolve() / path.parent.name
        ):
            raise ValueError("Unsafe evidence path")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Fixed object bound exceeded; no truncation")
        raw = path.read_bytes()
        if len(raw) != expected["bytes"] or digest(raw) != expected["sha256"]:
            raise ValueError("Fixed evidence SHA mismatch")
        checked_paths.add(name)
        return raw

    def original(observation, api):
        nonlocal source_bytes
        if observation in objects:
            return objects[observation]
        observed = json.loads(checked("observations/" + observation))
        if observed["request"]["api_name"] != api:
            raise ValueError("Observation API mismatch")
        raw = checked("objects/" + observed["object_sha256"] + ".json")
        source_bytes += len(raw)
        if source_bytes > 128 * 1024 * 1024:
            raise ValueError("Total source byte bound exceeded; no truncation")
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            response = None
        data = (
            response.get("data")
            if isinstance(response, dict) and response.get("code") == 0
            else None
        )
        if not isinstance(data, dict):
            result = (observed, [], [], None)
        else:
            fields = data.get("fields")
            if not isinstance(fields, list) or len(fields) != len(set(fields)):
                raise ValueError("Source schema ambiguous")
            rows = [dict(zip(fields, r, strict=True)) for r in data["items"]]
            result = (observed, fields, rows, data.get("has_more"))
        raw_maps[observation] = {digest(json_bytes(r)): r for r in result[2]}
        objects[observation] = result
        return result

    for sample in samples:
        api, params = sample["api_name"], sample["params"]
        spec = REALTIME_RUNTIME_CONTRACTS[api]
        info = {
            "api_name": api,
            "params": params,
            "status": sample["status"],
            "source_rows": 0,
            "observation": sample.get("observation"),
            "returned_fields": [],
            "missing_fields": list(spec["fields"]),
            "filter_mismatches": {},
        }
        observation = sample.get("observation")
        if observation:
            observed, fields, rows, more = original(observation, api)
            if (
                digest(checked("observations/" + observation))
                != sample["observation_sha256"]
                or observed["object_sha256"] != sample["object_sha256"]
                or observed["request"]["params"] != params
            ):
                raise ValueError("Probe immutable provenance mismatch")
            if not set(spec["fields"]) <= set(observed["request"]["fields"].split(",")):
                raise ValueError("Full known fields not requested")
            if api != "stk_auction":
                try:
                    requested = datetime.fromisoformat(
                        observed["requested_at"].replace("Z", "+00:00")
                    )
                    origin = datetime.strptime(slot, "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    if (
                        requested.tzinfo is None
                        or not 0 <= (requested - origin).total_seconds() <= 120
                    ):
                        raise ValueError("Observation outside explicit slot budget")
                except (KeyError, TypeError, ValueError):
                    gaps.append(
                        {
                            "api_name": api,
                            "kind": "observation_snapshot_slot_unverified",
                            "params": params,
                        }
                    )
            info.update(
                source_rows=len(rows),
                returned_fields=fields,
                missing_fields=sorted(set(spec["fields"]) - set(fields)),
                filter_mismatches=source_checks(api, params, rows, slot),
            )
            sources[observation] = rows
            if len(rows) != sample.get("row_count", 0):
                raise ValueError("Probe row count mismatch")
            if len(rows) >= spec["row_cap"] or more is True:
                gaps.append(
                    {"api_name": api, "kind": "saturation_unresolved", "params": params}
                )
        else:
            gaps.append(
                {
                    "api_name": api,
                    "kind": "no_complete_response_observation",
                    "params": params,
                }
            )
        for condition, kind in (
            (info["missing_fields"], "known_columns_missing"),
            (info["filter_mismatches"], "source_filter_or_time_mismatch"),
            (sample.get("normalization_error"), "normalization_failed"),
            (
                not info["source_rows"] or sample["status"] != "sample_ok",
                "not_nonempty_success",
            ),
        ):
            if condition:
                gaps.append({"api_name": api, "kind": kind, "params": params})
        sample_checks.append(info)
    for request in planned:
        if not any(
            s["api_name"] == request["api_name"] and s["params"] == request["params"]
            for s in samples
        ):
            gaps.append(
                {
                    "api_name": request["api_name"],
                    "kind": "planned_request_not_attempted",
                    "params": request["params"],
                }
            )
    for api in APIS:
        spec = REALTIME_RUNTIME_CONTRACTS[api]
        parts = [d for d in manifest["datasets"] if d["api_name"] == api]
        if len(parts) > args.max_partitions:
            raise ValueError("Fixed part bound exceeded; no truncation")
        candidates, seen = [], set()
        for part in parts:
            checked(part["path"])
            file = pq.ParquetFile(args.root / part["path"])
            total_rows += file.metadata.num_rows
            if total_rows > args.max_rows:
                raise ValueError("Fixed row bound exceeded; no truncation")
            rows = file.read().to_pylist()
            part_source_counts = {}
            for stored in rows:
                observation = stored["_observation"]
                observed, fields, raw_rows, _ = original(observation, api)
                params = observed["request"]["params"]
                source_hash = stored.get("_raw_row_identity", stored["_row_identity"])
                original_row = raw_maps[observation].get(source_hash)
                part_source_counts.setdefault(observation, Counter())[source_hash] += 1
                if original_row is None:
                    raise ValueError("Parquet row missing original source hash")
                for field, value in original_row.items():
                    projected_field = (
                        "source_" + field
                        if field == spec["source_code_field"]
                        else field
                    )
                    if projected_field not in stored or canonical(
                        stored[projected_field]
                    ) != canonical(value):
                        raise ValueError("Raw scalar changed in Parquet")
                raw_code = original_row[spec["source_code_field"]]
                canonical_code = expected_code(api, raw_code, params)
                if (
                    stored[spec["source_code_field"]] != canonical_code
                    or stored["ts_code"] != canonical_code
                ):
                    raise ValueError("Source namespace projection mismatch")
                if spec["request_identity_fields"]:
                    identity = {
                        f: params.get(f) for f in spec["request_identity_fields"]
                    }
                    if (
                        json.loads(stored["_request_identity"]) != identity
                        or stored["_request_identity_status"] != "complete"
                        or stored["_row_identity"]
                        != digest(
                            (
                                digest(json_bytes(original_row))
                                + "\n"
                                + json_bytes(identity).decode()
                            ).encode()
                        )
                    ):
                        raise ValueError("Request dimension provenance mismatch")
                seen.add(observation)
            for observation, counts in part_source_counts.items():
                expected_counts = Counter(
                    digest(json_bytes(r)) for r in objects[observation][2]
                )
                if counts != expected_counts:
                    raise ValueError("Raw/Parquet source row multiplicity mismatch")
            candidates.extend(rows)
        nonempty = {
            s["observation"]
            for s in sample_checks
            if s["api_name"] == api and s["source_rows"]
        }
        if nonempty - seen:
            gaps.append({"api_name": api, "kind": "nonempty_raw_not_in_fixed_parquet"})
        if not candidates:
            gaps.append({"api_name": api, "kind": "no_fixed_rows"})
            continue
        schema = dataset_schema(args.root, args.release_id, api)
        if schema["default_date_field"] != spec["date_field"]:
            raise ValueError("Default date axis mismatch")
        keys = list(dict.fromkeys([*spec["keys"], "_row_identity"]))
        if schema["keys"] != keys:
            raise ValueError("Natural key mismatch")
        latest = {}
        for row in candidates:
            key = tuple(row[k] for k in keys)
            rank = (
                datetime.fromisoformat(row["_fetched_at"].replace("Z", "+00:00")),
                row["_observation"],
            )
            if key not in latest or rank > latest[key][0]:
                latest[key] = (rank, row)
        table = read_dataset(args.root, args.release_id, api)
        actual = table.to_pylist()
        expected = [
            {field: v[1].get(field) for field in table.column_names}
            for v in latest.values()
        ]
        if Counter(map(canonical, actual)) != Counter(map(canonical, expected)):
            raise ValueError("Independent full fixed dataset comparison failed")
        date_checks = []
        axis = spec["date_field"]
        stamp = next(
            (r.get(axis) for r in expected if isinstance(r.get(axis), str)), None
        )
        try:
            if stamp is None:
                raise ValueError("No source date/time value")
            selected = read_dataset(
                args.root, args.release_id, api, start_date=stamp, end_date=stamp
            ).to_pylist()
            wanted = [r for r in expected if r.get(axis) == stamp]
            if Counter(map(canonical, selected)) != Counter(map(canonical, wanted)):
                raise ValueError("Exact source date/time filter mismatch")
            date_checks.append(
                {
                    "field": axis,
                    "value": stamp,
                    "rows": len(selected),
                    "all_columns_equal": True,
                }
            )
        except ValueError:
            gaps.append({"api_name": api, "kind": "fixed_date_filter_unverified"})
        if set(spec["fields"]) - set(table.column_names):
            gaps.append({"api_name": api, "kind": "fixed_known_columns_missing"})
        dataset_checks.append(
            {
                "api_name": api,
                "raw_probe_rows_verified": sum(
                    len(sources[o]) for o in nonempty & seen
                ),
                "all_fixed_rows_after_dedupe": len(actual),
                "known_columns_missing": sorted(
                    set(spec["fields"]) - set(table.column_names)
                ),
                "date_checks": date_checks,
                "all_columns_sha256": digest(
                    canonical(sorted(map(canonical, actual))).encode()
                ),
            }
        )
    candidates = [
        api
        for api in APIS
        if not any(g["api_name"] == api for g in gaps)
        and any(d["api_name"] == api and d["date_checks"] for d in dataset_checks)
    ]
    result = {
        "status": "verified_with_gaps" if gaps else "verified_sample_only",
        "release_id": args.release_id,
        "probe_report_sha256": digest(body),
        "runtime_contract_sha256": digest(
            canonical(REALTIME_RUNTIME_CONTRACTS).encode()
        ),
        "official_field_count": sum(
            len(REALTIME_RUNTIME_CONTRACTS[api]["fields"]) for api in APIS
        ),
        "probe_samples": sample_checks,
        "dataset_checks": dataset_checks,
        "gaps": gaps,
        "sample_passed_api_candidates": candidates,
        "automatic_activation_permitted": False,
        "source_timezone_pit_verified": False,
        "frequencies_tested": ["1MIN"],
        "all_supplier_fields_complete": False,
        "history_complete": False,
        "upstream_calls": 0,
        "verified_files": len(checked_paths),
    }
    result["equivalence_sha256"] = digest(canonical(result).encode())
    return result


def main():
    import argparse
    import socket
    from unittest.mock import patch

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    for name in ("root", "report", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--release-id", required=True)
    p.add_argument("--probe-sha256", required=True)
    p.add_argument("--compare-report", type=Path)
    p.add_argument("--max-rows", type=int, default=100000)
    p.add_argument("--max-partitions", type=int, default=200)
    args = p.parse_args()
    if args.output.exists() or args.output.resolve().is_relative_to(
        args.root.resolve()
    ):
        raise ValueError("Use a new report outside fixed data")
    if (
        not re.fullmatch(r"[a-f0-9]{64}", args.probe_sha256)
        or digest(args.report.read_bytes()) != args.probe_sha256
    ):
        raise ValueError("Operator-fixed probe SHA mismatch")
    sys.path.extend([str(args.repo), sysconfig.get_paths()["purelib"]])
    with (
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("offline audit")
        ),
        patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("offline audit")
        ),
        patch(
            "backend.shared.tushare_pipeline.get_secret",
            side_effect=AssertionError("no credentials"),
        ),
        patch(
            "backend.shared.runtime_secrets.get_secret",
            side_effect=AssertionError("no credentials"),
        ),
    ):
        result = audit(args)
    if (
        args.compare_report
        and json.loads(args.compare_report.read_bytes())["equivalence_sha256"]
        != result["equivalence_sha256"]
    ):
        raise ValueError("Cloud/Mac fixed audit differs")
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "release_id",
                    "equivalence_sha256",
                    "sample_passed_api_candidates",
                    "upstream_calls",
                )
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
