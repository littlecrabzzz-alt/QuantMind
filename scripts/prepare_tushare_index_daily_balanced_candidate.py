#!/usr/bin/env python3
"""Build a balanced index_daily candidate from reviewed offline inventories."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.shared.tushare_intake import digest, json_bytes  # noqa: E402
from backend.shared.tushare_registry import EXTENDED_CONTRACTS  # noqa: E402
from scripts import prepare_tushare_index_daily_batch as existing  # noqa: E402


API = "index_daily"
MARKETS = ("SSE", "SZSE", "CSI")
MAX_JOBS = 360
MAX_SECONDS = 90
SHA_RE = re.compile(r"[a-f0-9]{64}")


def sha(path: Path) -> str:
    return digest(Path(path).read_bytes())


def _regular(path: Path, label: str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"Invalid {label} SHA-256")
    return value


def code_pins() -> dict[str, str]:
    paths = (
        "backend/shared/tushare_daily_quota.py",
        "backend/shared/tushare_intake.py",
        "backend/shared/tushare_pipeline.py",
        "backend/shared/tushare_rate_policy.py",
        "backend/shared/tushare_registry.py",
        "backend/shared/tushare_store.py",
        "backend/shared/tushare_structured_contracts.py",
        "config/tushare-catalog.json",
        "scripts/prepare_tushare_index_daily_batch.py",
        "scripts/prepare_tushare_index_daily_balanced_candidate.py",
        "scripts/run_tushare_fund_nav_batch.py",
        "scripts/run_tushare_index_daily_batch.py",
    )
    return {path: sha(REPO / path) for path in paths}


def _read_pinned(path: Path, expected_sha: str, label: str) -> dict:
    path = _regular(path, label)
    if sha(path) != _sha(expected_sha, label):
        raise ValueError(f"{label} SHA-256 mismatch")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}")
    return value


def verify_discovery(path: Path, expected_sha: str) -> dict:
    value = _read_pinned(path, expected_sha, "discovery evidence")
    source = value.get("source")
    markets = value.get("eligible_index_daily_markets")
    cffex = value.get("cffex_boundary")
    index_refs = value.get("index_basic_source_refs")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "tushare_fixed_release_index_discovery_evidence"
        or not isinstance(source, dict)
        or not existing.RELEASE_RE.fullmatch(str(source.get("release_id", "")))
        or source.get("release_manifest_sha256")
        != source["release_id"].removeprefix("data-")
        or source.get("manifest_sha256_verified") is not True
        or not SHA_RE.fullmatch(str(source.get("current_pointer_sha256", "")))
        or source.get("current_pointer_verified") is not True
        or source.get("fixed_mirror_read_only") is not True
        or source.get("upstream_calls") != 0
        or source.get("credentials_accessed") is not False
        or type(source.get("release_manifest_bytes")) is not int
        or source["release_manifest_bytes"] < 1
        or not isinstance(markets, dict)
        or set(markets) != set(MARKETS)
        or not isinstance(index_refs, list)
        or not index_refs
        or not isinstance(cffex, dict)
        or cffex.get("family") != "futures"
        or cffex.get("eligible_for_index_daily") is not False
    ):
        raise ValueError("Invalid fixed discovery evidence")
    for ref in index_refs:
        if (
            not isinstance(ref, dict)
            or ref.get("api_name") != "index_basic"
            or not re.fullmatch(r"parquet/[a-f0-9]{64}\.parquet", ref.get("path", ""))
            or ref.get("sha256") != Path(ref["path"]).stem
            or type(ref.get("bytes")) is not int
            or ref["bytes"] < 1
            or type(ref.get("rows")) is not int
            or ref["rows"] < 1
            or not set(ref.get("observed_markets", ())) <= set(MARKETS)
        ):
            raise ValueError("Invalid index_basic source reference")
    owner = {}
    for market in MARKETS:
        item = markets[market]
        codes = item.get("codes") if isinstance(item, dict) else None
        if (
            not isinstance(codes, list)
            or not codes
            or codes != sorted(set(codes))
            or item.get("codes_count") != len(codes)
            or item.get("codes_sha256") != digest(json_bytes(codes))
        ):
            raise ValueError(f"Invalid {market} discovery inventory")
        for code in codes:
            if not existing.CODE_RE.fullmatch(str(code)) or code.endswith(
                (".SI", ".SW", ".CFX")
            ):
                raise ValueError(f"Invalid {market} index_daily code")
            if code in owner:
                raise ValueError("A discovered code belongs to multiple markets")
            owner[code] = market
    if (
        cffex.get("codes_count", 0) < 1
        or not isinstance(cffex.get("source_refs"), list)
        or not cffex["source_refs"]
    ):
        raise ValueError("CFFEX futures boundary lacks fixed evidence")
    return {"value": value, "owner": owner}


def _canonical_job(job: dict) -> bool:
    params = job.get("params") if isinstance(job, dict) else None
    spec = EXTENDED_CONTRACTS[API]
    return job == {
        "api_name": API,
        "params": params,
        "fields": ",".join(
            sorted(set(spec["required_fields"]) | set(spec["extra_fields"]))
        ),
        "row_cap": spec["row_cap"],
        "required_fields": spec["required_fields"],
        "nullable_fields": spec["nullable_fields"],
        "positive_fields": spec["positive_fields"],
    }


def _inventory_record(record: dict) -> tuple[str, str, str]:
    if not isinstance(record, dict) or set(record) != {
        "task_id",
        "logical_key",
        "epoch",
        "priority",
        "group_name",
        "state",
        "tries",
        "result",
        "attempt_count",
        "job",
    }:
        raise ValueError("Invalid authority inventory record")
    base = {
        key: record[key]
        for key in (
            "task_id",
            "logical_key",
            "epoch",
            "priority",
            "group_name",
            "state",
            "tries",
            "job",
        )
    }
    code, start, end = existing._validate_record(base)
    if (
        record["result"] is not None
        or record["attempt_count"] != 0
        or not _canonical_job(record["job"])
    ):
        raise ValueError("Authority inventory contains a non-pristine task")
    return code, start, end


def verify_authority_inventory(path: Path, expected_sha: str, discovery: dict) -> dict:
    value = _read_pinned(path, expected_sha, "authority inventory")
    source = value.get("source")
    records = value.get("records")
    reserved = value.get("reserved_task_ids")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "tushare_index_daily_pristine_authority_inventory"
        or not isinstance(source, dict)
        or source.get("release_id") != discovery["source"]["release_id"]
        or source.get("release_manifest_sha256")
        != discovery["source"]["release_manifest_sha256"]
        or not SHA_RE.fullmatch(str(source.get("current_pointer_sha256", "")))
        or not SHA_RE.fullmatch(str(source.get("authority_config_sha256", "")))
        or source.get("pipeline_schema_version") != 6
        or source.get("captured_under_shared_lock") is not True
        or source.get("query_only") is not True
        or source.get("attempt_join_complete") is not True
        or source.get("prior_plan_inventory_complete") is not True
        or not isinstance(records, list)
        or not records
        or not isinstance(reserved, list)
        or reserved != sorted(set(reserved))
        or any(not SHA_RE.fullmatch(str(item)) for item in reserved)
    ):
        raise ValueError("Invalid authority inventory")
    ids = []
    for record in records:
        _inventory_record(record)
        ids.append(record["task_id"])
    if (
        len(ids) != len(set(ids))
        or value.get("records_sha256") != digest(json_bytes(records))
        or value.get("all_task_ids_sha256") != digest(json_bytes(sorted(ids)))
        or value.get("reserved_task_ids_sha256") != digest(json_bytes(reserved))
    ):
        raise ValueError("Authority inventory hash or identity mismatch")
    return value


def _market_queue(records: list[dict], seed: str) -> deque[dict]:
    by_code = defaultdict(list)
    for record in records:
        code, start, end = _inventory_record(record)
        by_code[code].append((end, start, record["task_id"], record))
    for values in by_code.values():
        values.sort(reverse=True)
    code_order = sorted(by_code, key=lambda code: digest(json_bytes([seed, code])))
    flattened = []
    round_number = 0
    while True:
        added = False
        for code in code_order:
            if round_number < len(by_code[code]):
                flattened.append(by_code[code][round_number][-1])
                added = True
        if not added:
            break
        round_number += 1
    return deque(flattened)


def select_records(inventory: dict, owner: dict[str, str], jobs: int, seed: str):
    if type(jobs) is not int or not 1 <= jobs <= MAX_JOBS:
        raise ValueError("jobs must be between 1 and 360")
    reserved = set(inventory["reserved_task_ids"])
    grouped = {market: [] for market in MARKETS}
    unproven = Counter()
    for record in inventory["records"]:
        code, _start, _end = _inventory_record(record)
        if record["task_id"] in reserved:
            continue
        market = owner.get(code)
        if market is None:
            unproven[code.rsplit(".", 1)[-1]] += 1
            continue
        grouped[market].append(record)
    minimum = jobs // len(MARKETS) + (1 if jobs % len(MARKETS) else 0)
    if any(len(grouped[market]) < minimum for market in MARKETS):
        raise ValueError("Insufficient balanced pristine tasks across SSE/SZSE/CSI")
    queues = {
        market: _market_queue(grouped[market], seed + ":" + market)
        for market in MARKETS
    }
    selected = []
    while len(selected) < jobs:
        progressed = False
        for market in MARKETS:
            if queues[market] and len(selected) < jobs:
                selected.append(queues[market].popleft())
                progressed = True
        if not progressed:
            break
    if len(selected) != jobs:
        raise ValueError("Insufficient reviewed pristine tasks")
    return selected, grouped, dict(sorted(unproven.items()))


def _summary(records: list[dict], owner: dict[str, str]) -> dict:
    triples = [_inventory_record(record) for record in records]
    markets = Counter(owner[code] for code, _start, _end in triples)
    return {
        "jobs": len(records),
        "market_counts": {market: markets[market] for market in MARKETS},
        "unique_index_codes": len({code for code, _start, _end in triples}),
        "start_date_min": min(start for _code, start, _end in triples),
        "end_date_max": max(end for _code, _start, end in triples),
        "request_ranges_sha256": digest(json_bytes(sorted(triples))),
    }


def _suffix_owner(records: list[dict]) -> dict[str, str]:
    suffix_market = {"SH": "SSE", "SZ": "SZSE", "CSI": "CSI"}
    owner = {}
    for record in records:
        code, _start, _end = _inventory_record(record)
        market = suffix_market.get(code.rsplit(".", 1)[-1])
        if market is None:
            raise ValueError("Candidate contains a non-reviewed index market")
        owner[code] = market
    return owner


def build_candidate(
    discovery_path: Path,
    discovery_sha256: str,
    inventory_path: Path,
    inventory_sha256: str,
    jobs: int = MAX_JOBS,
) -> dict:
    discovery = verify_discovery(discovery_path, discovery_sha256)
    inventory = verify_authority_inventory(
        inventory_path, inventory_sha256, discovery["value"]
    )
    seed = discovery["value"]["source"]["release_manifest_sha256"]
    records, eligible, unproven = select_records(
        inventory, discovery["owner"], jobs, seed
    )
    selected_ids = sorted(record["task_id"] for record in records)
    return {
        "schema_version": 1,
        "kind": "tushare_index_daily_balanced_exact_candidate",
        "status": "prepared_not_authorized_for_execution",
        "source": {
            "release_id": discovery["value"]["source"]["release_id"],
            "release_manifest_sha256": discovery["value"]["source"][
                "release_manifest_sha256"
            ],
            "authority_config_sha256": inventory["source"]["authority_config_sha256"],
            "current_pointer_sha256": inventory["source"]["current_pointer_sha256"],
            "discovery_evidence_sha256": discovery_sha256,
            "authority_inventory_sha256": inventory_sha256,
            "authority_all_task_ids_sha256": inventory["all_task_ids_sha256"],
            "reserved_task_ids_sha256": inventory["reserved_task_ids_sha256"],
            "code_sha256": code_pins(),
        },
        "limits": {
            "max_upstream_requests": jobs,
            "max_seconds": MAX_SECONDS,
            "publish": False,
            "implicit_queue_allowed": False,
        },
        "eligible_counts": {market: len(eligible[market]) for market in MARKETS},
        "unproven_suffix_counts": unproven,
        "selected": _summary(records, discovery["owner"]),
        "all_task_ids_sha256": digest(json_bytes(selected_ids)),
        "records": records,
        "boundaries": {
            "cffex_is_futures_and_excluded": True,
            "cicc_without_fixed_nonempty_evidence_excluded": True,
            "csi_discovery_saturated_and_incomplete": True,
            "history_complete": False,
            "revisions_complete": False,
            "known_at_verified": False,
            "pit_verified": False,
            "upstream_calls": 0,
            "authority_accessed_by_builder": False,
            "credentials_accessed": False,
        },
    }


def verify_candidate(path: Path, expected_sha: str) -> dict:
    value = _read_pinned(path, expected_sha, "candidate manifest")
    source = value.get("source")
    limits = value.get("limits")
    records = value.get("records")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "tushare_index_daily_balanced_exact_candidate"
        or value.get("status") != "prepared_not_authorized_for_execution"
        or not isinstance(source, dict)
        or set(source)
        != {
            "release_id",
            "release_manifest_sha256",
            "authority_config_sha256",
            "current_pointer_sha256",
            "discovery_evidence_sha256",
            "authority_inventory_sha256",
            "authority_all_task_ids_sha256",
            "reserved_task_ids_sha256",
            "code_sha256",
        }
        or source.get("release_id")
        != "data-" + str(source.get("release_manifest_sha256"))
        or any(
            not SHA_RE.fullmatch(str(source.get(key, "")))
            for key in (
                "release_manifest_sha256",
                "authority_config_sha256",
                "current_pointer_sha256",
                "discovery_evidence_sha256",
                "authority_inventory_sha256",
                "authority_all_task_ids_sha256",
                "reserved_task_ids_sha256",
            )
        )
        or source.get("code_sha256") != code_pins()
        or not isinstance(limits, dict)
        or set(limits)
        != {
            "max_upstream_requests",
            "max_seconds",
            "publish",
            "implicit_queue_allowed",
        }
        or limits.get("publish") is not False
        or limits.get("implicit_queue_allowed") is not False
        or limits.get("max_seconds") != MAX_SECONDS
        or not isinstance(records, list)
        or not 1 <= len(records) <= MAX_JOBS
        or limits.get("max_upstream_requests") != len(records)
    ):
        raise ValueError("Invalid balanced candidate")
    ids = []
    for record in records:
        _inventory_record(record)
        ids.append(record["task_id"])
    market_owner = _suffix_owner(records)
    boundaries = {
        "cffex_is_futures_and_excluded": True,
        "cicc_without_fixed_nonempty_evidence_excluded": True,
        "csi_discovery_saturated_and_incomplete": True,
        "history_complete": False,
        "revisions_complete": False,
        "known_at_verified": False,
        "pit_verified": False,
        "upstream_calls": 0,
        "authority_accessed_by_builder": False,
        "credentials_accessed": False,
    }
    if (
        len(ids) != len(set(ids))
        or value.get("all_task_ids_sha256") != digest(json_bytes(sorted(ids)))
        or value.get("selected") != _summary(records, market_owner)
        or max(value["selected"]["market_counts"].values())
        - min(value["selected"]["market_counts"].values())
        > 1
        or value.get("boundaries") != boundaries
    ):
        raise ValueError("Candidate task identity mismatch")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--discovery-sha256", required=True)
    parser.add_argument("--authority-inventory", type=Path, required=True)
    parser.add_argument("--authority-inventory-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=MAX_JOBS)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Output must be create-only")
    candidate = build_candidate(
        args.discovery,
        args.discovery_sha256,
        args.authority_inventory,
        args.authority_inventory_sha256,
        args.jobs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(json_bytes(candidate))
    verified = verify_candidate(args.output, sha(args.output))
    print(
        json.dumps(
            {
                "status": verified["status"],
                "jobs": len(verified["records"]),
                "selected": verified["selected"],
                "manifest_sha256": sha(args.output),
                "upstream_calls": 0,
                "authority_accessed": False,
                "credentials_accessed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
