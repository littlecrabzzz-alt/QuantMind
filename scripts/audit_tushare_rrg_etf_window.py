#!/usr/bin/env python3
"""Audit a pinned Tushare ETF/RRG window without inventing PIT evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_pipeline import manifest_at  # noqa: E402
from backend.shared.tushare_store import read_dataset  # noqa: E402
from scripts.prepare_tushare_rrg_pit_etf_bridge import (  # noqa: E402
    candidate_universe,
    date8,
    distinct,
    membership_inputs,
)

CORE = ("trade_cal", "ci_index_member", "etf_basic", "fund_basic")
WINDOW_DATASETS = (
    "fund_daily",
    "fund_adj",
    "fund_div",
    "etf_limit",
    "etf_sh_cons",
    "etf_sz_cons",
)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sessions(rows, start, end):
    values = {}
    for row in rows:
        if row.get("exchange") != "SSE":
            continue
        day = date8(row.get("cal_date"), "calendar date")
        flag = str(row.get("is_open"))
        if flag not in ("0", "1") or (day in values and values[day] != flag):
            raise ValueError("Invalid/conflicting SSE calendar")
        values[day] = flag
    first, last = (datetime.strptime(value, "%Y%m%d") for value in (start, end))
    required = {
        (first + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((last - first).days + 1)
    }
    if required - values.keys():
        raise ValueError("Missing natural-day SSE calendar evidence")
    return sorted(day for day, flag in values.items() if flag == "1")


def _eligible_sessions(record, sessions):
    listed, delisted = record["list_date"], record["delist_date"]
    if not listed:
        return []
    return [day for day in sessions if listed <= day and (not delisted or day <= delisted)]


def _session_ranges(days, positions):
    if not days:
        return []
    ranges, left, right = [], days[0], days[0]
    for day in days[1:]:
        if positions[day] == positions[right] + 1:
            right = day
        else:
            ranges.append({"start_date": left, "end_date": right})
            left = right = day
    ranges.append({"start_date": left, "end_date": right})
    return ranges


def _months(start, end):
    cursor = datetime.strptime(start, "%Y%m%d")
    stop = datetime.strptime(end, "%Y%m%d")
    while cursor <= stop:
        following = (
            cursor.replace(year=cursor.year + 1, month=1, day=1)
            if cursor.month == 12
            else cursor.replace(month=cursor.month + 1, day=1)
        )
        right = min(stop, following - timedelta(days=1))
        yield cursor.strftime("%Y%m%d"), right.strftime("%Y%m%d")
        cursor = following


def _years(start, end):
    first, last = int(start[:4]), int(end[:4])
    for year in range(first, last + 1):
        yield max(start, f"{year}0101"), min(end, f"{year}1231")


def _monthly_executions(sessions):
    by_month = defaultdict(list)
    for day in sessions:
        by_month[day[:6]].append(day)
    result = []
    for month in sorted(by_month):
        signal = by_month[month][-1]
        execution = next((day for day in sessions if day > signal), None)
        if execution:
            result.append({"signal_date": signal, "execution_date": execution})
    return result


def _valid_price(row):
    values = [row.get("open"), row.get("close"), row.get("vol"), row.get("amount")]
    return all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (value > 0 if index < 2 else value >= 0)
        for index, value in enumerate(values)
    )


def _valid_factor(row):
    value = row.get("adj_factor")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _etf_limit_rows(rows):
    mapped = []
    for row in rows:
        source = row.get("source_ts_code")
        match = re.fullmatch(r"([0-9]{6,7})\.(SH|SZ|BJ)", str(source or ""))
        if not match or row.get("ts_code") != "FUND:" + source:
            raise ValueError("Invalid ETF limit source namespace")
        mapped.append({**row, "ts_code": match[2] + match[1]})
    return mapped


def _fund_div_empty_receipts(manifest, source_codes):
    by_source = {}
    for code, source in source_codes.items():
        if source in by_source and by_source[source] != code:
            raise ValueError("Ambiguous ETF source identifier")
        by_source[source] = code
    receipts = set()
    for gap in manifest.get("gaps", []):
        if (
            gap.get("api_name") != "fund_div"
            or gap.get("state") != "empty"
            or gap.get("assessment") != "empty_unverified"
        ):
            continue
        params = gap.get("params")
        if not isinstance(params, dict) or set(params) != {"ts_code"}:
            raise ValueError("Invalid fund_div empty receipt")
        if params["ts_code"] in by_source:
            receipts.add(by_source[params["ts_code"]])
    return receipts


def _lineage_calendar_evidence(
    path,
    sessions,
    expected_pairs,
    missing_pairs,
    execution_pairs,
    start_date,
    end_date,
):
    if path is None:
        return {"provided": False}
    path = Path(path).resolve()
    payload = json.loads(path.read_text())
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Invalid ETF limit lineage evidence")
    task_ids = [row.get("task_id") for row in rows]
    if any(not isinstance(value, str) or not value for value in task_ids) or len(
        set(task_ids)
    ) != len(task_ids):
        raise ValueError("Invalid ETF limit lineage task identifiers")
    roots = [row for row in rows if row.get("depth") == 0]
    root_ids = {row["task_id"] for row in roots}
    if any(row.get("root_id") not in root_ids for row in rows):
        raise ValueError("Invalid ETF limit lineage root identifiers")
    lifecycle_by_day = Counter(day for day, _ in expected_pairs)
    missing_by_day = Counter(day for day, _ in missing_pairs)
    empty_windows = []
    for row in rows:
        if row.get("state") != "empty" or row.get("child_count") != 0:
            continue
        params = row.get("params")
        if not isinstance(params, dict):
            raise ValueError("Invalid ETF limit empty leaf parameters")
        if set(params) == {"trade_date"}:
            left = right = date8(params["trade_date"], "ETF limit leaf date")
        elif set(params) == {"start_date", "end_date"}:
            left = date8(params["start_date"], "ETF limit leaf start")
            right = date8(params["end_date"], "ETF limit leaf end")
        else:
            raise ValueError("Invalid ETF limit empty leaf parameters")
        if left > right:
            raise ValueError("Invalid ETF limit empty leaf range")
        if left < start_date or right > end_date:
            raise ValueError("ETF limit empty leaf falls outside audited window")
        open_days = [day for day in sessions if left <= day <= right]
        empty_windows.append(
            {
                "_root_id": row.get("root_id"),
                "_task_id": row.get("task_id"),
                "params": params,
                "sse_open_sessions": len(open_days),
                "fixed_lifecycle_pairs": sum(
                    count for day, count in lifecycle_by_day.items() if left <= day <= right
                ),
                "missing_etf_limit_pairs": sum(
                    count for day, count in missing_by_day.items() if left <= day <= right
                ),
                "classification": (
                    "calendar_excluded_non_session"
                    if not open_days
                    else "open_session_empty_unverified"
                ),
            }
        )
    leaves = [row for row in rows if row.get("child_count") == 0]
    blocked_root_ids = {
        row.get("root_id", row.get("task_id"))
        for row in roots
        if row.get("state") == "split_pending"
        and isinstance(row.get("gap"), dict)
        and row["gap"].get("reason") == "child_not_verified"
    }
    calendar_excluded_leaf_ids = {
        row["_task_id"]
        for row in empty_windows
        if row["classification"] == "calendar_excluded_non_session"
    }
    leaf_root_ids = {row["root_id"] for row in leaves}
    unresolved_leaf_root_ids = {
        row["root_id"]
        for row in leaves
        if row.get("state") != "done"
        and row.get("task_id") not in calendar_excluded_leaf_ids
    }
    calendar_covered_root_ids = (
        blocked_root_ids & leaf_root_ids
    ) - unresolved_leaf_root_ids
    for row in empty_windows:
        row.pop("_root_id", None)
        row.pop("_task_id", None)
    return {
        "provided": True,
        "sha256": _sha(path),
        "roots": len(roots),
        "descendants": len(rows) - len(roots),
        "child_not_verified_roots": len(blocked_root_ids),
        "calendar_covered_child_not_verified_roots": len(calendar_covered_root_ids),
        "leaf_tasks": len(leaves),
        "empty_leaf_tasks": len(empty_windows),
        "calendar_excluded_empty_leaf_tasks": sum(
            row["classification"] == "calendar_excluded_non_session"
            for row in empty_windows
        ),
        "open_session_empty_unverified_leaf_tasks": sum(
            row["classification"] == "open_session_empty_unverified"
            for row in empty_windows
        ),
        "open_session_empty_unverified_missing_pairs": sum(
            row["missing_etf_limit_pairs"]
            for row in empty_windows
            if row["classification"] == "open_session_empty_unverified"
        ),
        "missing_lifecycle_session_pairs": len(missing_pairs),
        "missing_monthly_execution_pairs": len(missing_pairs & execution_pairs),
        "empty_leaf_windows": empty_windows,
        "semantics": (
            "Closed-session leaves are excluded only from the fixed RRG lifecycle "
            "envelope; open-session empty leaves remain unverified and never prove suspension"
        ),
    }


def _audit(root, release_id, start_date, end_date, output, lineage=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output == root
        or root in output.parents
        or output == REPO
        or REPO in output.parents
        or any((parent / ".git").exists() for parent in (output, *output.parents))
    ):
        raise ValueError("Output must be new and outside source/data trees")
    start_date = date8(start_date, "window start")
    end_date = date8(end_date, "window end")
    if start_date >= end_date:
        raise ValueError("Window start must precede end")

    manifest = manifest_at(root, release_id)
    available = {row["api_name"] for row in manifest["datasets"]}
    if set(CORE) - available:
        raise ValueError("Pinned release lacks a core audit dataset")
    queries = []

    def read(api, *, limit, **params):
        if api not in available:
            queries.append({"api_name": api, "status": "dataset_unavailable", "rows": 0})
            return []
        table = read_dataset(root, release_id, api, limit=limit, **params)
        if len(table) >= limit:
            raise ValueError(api + " reached explicit query cap")
        metadata = json.loads(table.schema.metadata[b"tushare"])
        if metadata["release_id"] != release_id or metadata["upstream_calls"] != 0:
            raise ValueError("Unexpected fixed-reader provenance")
        queries.append(
            {
                "api_name": api,
                "status": "read",
                "rows": len(table),
                "params": {key: value for key, value in params.items() if key != "codes"},
                "metadata": metadata,
            }
        )
        return table.to_pylist()

    calendar = read(
        "trade_cal",
        limit=5000,
        date_field="cal_date",
        start_date=start_date,
        end_date=end_date,
    )
    sessions = _sessions(calendar, start_date, end_date)
    members = membership_inputs(read("ci_index_member", limit=100000), end_date)
    etfs = read("etf_basic", limit=10000)
    funds = read("fund_basic", limit=100000)
    universe, _, unsupported = candidate_universe(etfs, funds, end_date)
    supported = [
        row
        for row in universe
        if row["exchange"] in ("SH", "SZ")
        and row["EtfCode"].startswith(row["exchange"])
    ]
    known = [row for row in supported if row["list_date"]]
    overlapping = [
        row
        for row in known
        if row["list_date"] <= end_date
        and (not row["delist_date"] or row["delist_date"] >= start_date)
    ]
    codes = sorted(row["EtfCode"] for row in supported)

    window = {
        "date_field": "trade_date",
        "start_date": start_date,
        "end_date": end_date,
        "codes": codes,
    }
    rows = {
        "fund_daily": read("fund_daily", limit=5_000_000, **window),
        "fund_adj": read("fund_adj", limit=5_000_000, **window),
        "fund_div": read("fund_div", limit=200_000, codes=codes),
        # etf_limit intentionally uses the FUND: source namespace, unlike the
        # SH/SZ ETF execution keys used by the RRG inputs. Read the date window
        # first, then map its retained supplier code explicitly below.
        "etf_limit": read(
            "etf_limit",
            limit=5_000_000,
            date_field="trade_date",
            start_date=start_date,
            end_date=end_date,
        ),
        "etf_sh_cons": read("etf_sh_cons", limit=5_000_000, **window),
        "etf_sz_cons": read("etf_sz_cons", limit=5_000_000, **window),
    }
    prices = distinct(rows["fund_daily"], ("trade_date", "ts_code"), "ETF price")
    factors = distinct(rows["fund_adj"], ("trade_date", "ts_code"), "ETF factor")
    limits = distinct(
        _etf_limit_rows(rows["etf_limit"]),
        ("trade_date", "ts_code"),
        "ETF limit",
    )
    pcf_keys = {
        (row.get("trade_date"), row.get("ts_code"))
        for api in ("etf_sh_cons", "etf_sz_cons")
        for row in rows[api]
        if row.get("trade_date") and row.get("ts_code")
    }
    positions = {day: index for index, day in enumerate(sessions)}
    source_codes = {row["EtfCode"]: row.get("source_etf_code") for row in supported}
    empty_receipt_codes = _fund_div_empty_receipts(manifest, source_codes)
    dividend_keys = set()
    for row in rows["fund_div"]:
        key = tuple(
            row.get(field)
            for field in ("ts_code", "ann_date", "ex_date", "pay_date", "div_proc")
        )
        if not key[0] or key in dividend_keys:
            raise ValueError("Missing or duplicate fund dividend key")
        dividend_keys.add(key)
    dividend_codes = {key[0] for key in dividend_keys}
    expected_dividend_codes = {row["EtfCode"] for row in overlapping}
    terminal_dividend_codes = (empty_receipt_codes | dividend_codes) & expected_dividend_codes
    missing_dividend_codes = expected_dividend_codes - terminal_dividend_codes
    missing_records, plans = [], []
    expected_pairs = set()
    for record in overlapping:
        code = record["EtfCode"]
        days = _eligible_sessions(record, sessions)
        expected_pairs.update((day, code) for day in days)
        for api, observed in (("fund_daily", prices), ("fund_adj", factors)):
            missing = [
                day
                for day in days
                if (day, code) not in observed
                and (api == "fund_daily" or (day, code) in prices)
            ]
            if not missing:
                continue
            ranges = _session_ranges(missing, positions)
            missing_records.append(
                {
                    "api_name": api,
                    "ts_code": code,
                    "source_ts_code": source_codes[code],
                    "missing_sessions": len(missing),
                    "ranges": ranges,
                }
            )
            plans.extend(
                {
                    "api_name": api,
                    "params": {"ts_code": source_codes[code], **span},
                    "gate": "diagnostic_refresh_only",
                    "reason": "zero rows remain unclassified; never fill prices",
                }
                for span in ranges
            )
    for code in sorted(missing_dividend_codes):
        plans.append(
            {
                "api_name": "fund_div",
                "params": {"ts_code": source_codes[code]},
                "gate": "requires_terminal_receipt",
                "reason": "fixed release has neither event rows nor a terminal empty receipt for this ETF",
            }
        )
    for left, right in _months(start_date, end_date):
        plans.append(
            {
                "api_name": "etf_limit",
                "params": {"start_date": left, "end_date": right},
                "gate": "collection_candidate",
                "reason": "price bounds are evidence only and do not prove suspension or open tradability",
            }
        )
    for record in overlapping:
        api = "etf_sh_cons" if record["exchange"] == "SH" else "etf_sz_cons"
        for left, right in _years(
            max(start_date, record["list_date"]),
            min(end_date, record["delist_date"] or end_date),
        ):
            plans.append(
                {
                    "api_name": api,
                    "params": {
                        "ts_code": source_codes[record["EtfCode"]],
                        "start_date": left,
                        "end_date": right,
                    },
                    "gate": "blocked_until_authoritative_etf_mapping",
                    "reason": "observed ETF lifecycle is not a PIT industry mapping",
                }
            )

    executions = _monthly_executions(sessions)
    execution_days = {row["execution_date"] for row in executions}
    execution_pairs = {pair for pair in expected_pairs if pair[0] in execution_days}
    missing_limit_pairs = expected_pairs - limits.keys()
    valid_prices = {key for key, row in prices.items() if _valid_price(row)}
    valid_factors = {key for key, row in factors.items() if _valid_factor(row)}
    status = "blocked_data"
    report = {
        "schema_version": 1,
        "status": status,
        "release_id": release_id,
        "window": {
            "start_date": start_date,
            "end_date": end_date,
            "sse_sessions": len(sessions),
            "monthly_signal_execution_pairs": executions,
        },
        "upstream_calls": 0,
        "credentials_accessed": False,
        "strategy_or_returns_calculated": False,
        "membership": {
            "rows": len(members),
            "effective_interval_candidates_on_window_end": sum(
                row["interval_contains_signal_candidate"] for row in members
            ),
            "known_at_rows": sum(bool(row["known_at"]) for row in members),
            "known_at_verified": False,
            "revision_publication_evidence_verified": False,
        },
        "universe": {
            "observed_etf_rows": len(universe),
            "supported_observed_codes": len(supported),
            "known_lifecycle_codes": len(known),
            "window_lifecycle_codes": len(overlapping),
            "unknown_list_date_codes": sorted(
                row["EtfCode"] for row in supported if not row["list_date"]
            ),
            "unsupported_exchange_codes": sorted(unsupported),
            "historical_universe_verified": False,
            "industry_mapping_verified": False,
        },
        "coverage": {
            "expected_lifecycle_session_pairs": len(expected_pairs),
            "fund_daily_rows": len(rows["fund_daily"]),
            "fund_daily_valid_pairs": len(expected_pairs & valid_prices),
            "fund_daily_missing_pairs": len(expected_pairs - prices.keys()),
            "fund_daily_invalid_pairs": len((expected_pairs & prices.keys()) - valid_prices),
            "fund_adj_rows": len(rows["fund_adj"]),
            "fund_adj_valid_pairs": len(expected_pairs & valid_factors),
            "fund_adj_lifecycle_missing_pairs": len(expected_pairs - factors.keys()),
            "fund_adj_missing_for_price_pairs": len(
                (expected_pairs & prices.keys()) - factors.keys()
            ),
            "fund_adj_invalid_pairs": len((expected_pairs & factors.keys()) - valid_factors),
            "joined_valid_price_factor_pairs": len(expected_pairs & valid_prices & valid_factors),
            "monthly_execution_expected_pairs": len(execution_pairs),
            "monthly_execution_valid_price_factor_pairs": len(
                execution_pairs & valid_prices & valid_factors
            ),
            "fund_div_event_rows": len(dividend_keys),
            "fund_div_codes_with_events": len(dividend_codes),
            "fund_div_empty_receipts_available_in_fixed_release": bool(
                empty_receipt_codes
            ),
            "fund_div_empty_receipt_codes": len(
                empty_receipt_codes & expected_dividend_codes
            ),
            "fund_div_terminal_receipt_codes": len(terminal_dividend_codes),
            "fund_div_missing_terminal_receipt_codes": len(missing_dividend_codes),
            "fund_div_terminal_receipt_coverage_complete": not missing_dividend_codes,
            "etf_limit_observed_code_day_pairs": len(limits),
            "etf_limit_code_day_pairs": len(expected_pairs & limits.keys()),
            "etf_limit_missing_lifecycle_pairs": len(missing_limit_pairs),
            "etf_limit_monthly_execution_pairs": len(execution_pairs & limits.keys()),
            "etf_limit_missing_monthly_execution_pairs": len(
                execution_pairs - limits.keys()
            ),
            "pcf_code_day_pairs": len(pcf_keys),
            "pcf_monthly_execution_pairs": len(execution_pairs & pcf_keys),
        },
        "collection_plan": {
            "jobs": len(plans),
            "active_candidate_jobs": sum(
                row["gate"] != "blocked_until_authoritative_etf_mapping" for row in plans
            ),
            "dormant_pcf_jobs": sum(
                row["gate"] == "blocked_until_authoritative_etf_mapping" for row in plans
            ),
            "semantics": "Exact Tushare source parameters; not automatically enqueued",
        },
        "api_contracts": {
            "fund_daily": {"params": ["ts_code", "trade_date", "start_date", "end_date"]},
            "fund_adj": {"params": ["ts_code", "trade_date", "start_date", "end_date", "offset", "limit"]},
            "fund_div": {"params": ["ts_code"], "event_axis": ["ann_date", "ex_date", "pay_date"]},
            "etf_limit": {"params": ["ts_code", "trade_date", "start_date", "end_date"]},
            "etf_sh_cons": {"params": ["ts_code", "trade_date", "con_code", "start_date", "end_date"]},
            "etf_sz_cons": {"params": ["ts_code", "trade_date", "con_code", "start_date", "end_date"]},
        },
        "blocked_gates": [
            "ci_index_member has no verified known_at or revision publication evidence",
            "current ETF records do not provide a PIT industry mapping or complete historical universe",
            "missing fund_daily rows have no documented Tushare ETF suspension/open-tradability classifier",
            "etf_limit is a price-bound dataset and cannot substitute for suspension or opening-auction evidence",
            "fund_div terminal receipts prove completed requests, not complete source history or revisions",
            "PCF applicability dates do not prove pre-open known_at, revisions or portfolio weights",
        ],
        "queries": queries,
        "source_partition_counts": {
            api: sum(row["api_name"] == api for row in manifest["datasets"])
            for api in (*CORE, *WINDOW_DATASETS)
        },
        "partition_count_semantics": "Physical observations, not unique dates or completeness proof",
        "etf_limit_lineage": _lineage_calendar_evidence(
            lineage,
            sessions,
            expected_pairs,
            missing_limit_pairs,
            execution_pairs,
            start_date,
            end_date,
        ),
    }

    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    missing_limit_records = [
        {
            "trade_date": day,
            "ts_code": code,
            "monthly_execution": (day, code) in execution_pairs,
            "classification": "open_session_lifecycle_pair_unverified",
        }
        for day, code in sorted(missing_limit_pairs)
    ]
    for name, values in (
        ("missing-observations.jsonl", missing_records),
        ("etf-limit-missing-observations.jsonl", missing_limit_records),
        ("collection-plan.jsonl", plans),
    ):
        with (output / name).open("w") as target:
            for row in values:
                target.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha(path)}
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    (output / "manifest.json").write_text(
        json.dumps({"release_id": release_id, "status": status, "files": files}, indent=2) + "\n"
    )
    return report


def audit(*args, **kwargs):
    """Block upstream, secret and source writes while reading one fixed release."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(patch(target, side_effect=AssertionError("Offline RRG audit")))
        return _audit(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lineage", type=Path)
    args = parser.parse_args()
    report = audit(
        args.root,
        args.release_id,
        args.start_date,
        args.end_date,
        args.output,
        lineage=args.lineage,
    )
    print(json.dumps({"status": report["status"], "coverage": report["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
