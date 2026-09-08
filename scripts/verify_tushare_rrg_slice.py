#!/usr/bin/env python3
"""Read-only, fixed-release RRG signal input check; no research or case mutation."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_store import read_dataset  # noqa: E402

EXPECTED_CODES = [f"CI005{i:03d}" for i in range(1, 31)]


def verify(root, release_id, config):
    protocol = config["protocol"]
    first, last = (date.fromisoformat(value) for value in protocol["comparison_window"])
    warmup = protocol["warmup_sessions"]
    params = protocol["parameters"]
    if warmup != params["ratio_lookback"] + params["momentum_lookback"] + 2 * (
        params["smooth_window"] - 1
    ):
        raise ValueError("Inconsistent warmup contract")
    if protocol["classification"] != "中信一级":
        raise ValueError("This verifier only reviews the frozen CITIC L1 scope")
    requests, metadata = {}, {}

    def read(api, limit, **filters):
        requests[api] = {**filters, "limit": limit}
        table = read_dataset(root, release_id, api, limit=limit, **filters)
        if len(table) >= limit:
            raise ValueError(f"{api} reached verifier cap; incomplete check")
        metadata[api] = json.loads(table.schema.metadata[b"tushare"])
        return table.to_pylist()

    # Scope the calendar to a conservative interval, then derive exact trading days.
    start = (first - timedelta(days=warmup * 3)).strftime("%Y%m%d")
    end = last.strftime("%Y%m%d")
    cal = read(
        "trade_cal",
        10000,
        fields=["exchange", "cal_date", "is_open"],
        start_date=start,
        end_date=end,
    )
    cal = [row for row in cal if row["exchange"] == "SSE"]
    open_days = sorted(
        {str(row["cal_date"]) for row in cal if str(row["is_open"]) == "1"}
    )
    comparison_day = next(day for day in open_days if day >= first.strftime("%Y%m%d"))
    index = open_days.index(comparison_day)
    if index < warmup:
        raise ValueError("Calendar lacks the required warmup")
    warmup_start = open_days[index - warmup]
    expected = {day for day in open_days if warmup_start <= day <= end}
    calendar_dates = {str(row["cal_date"]) for row in cal}
    lo = datetime.strptime(warmup_start, "%Y%m%d").date()
    expected_calendar = {
        (lo + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((last - lo).days + 1)
    }
    missing_calendar = sorted(expected_calendar - calendar_dates)
    invalid_calendar = [row for row in cal if str(row["is_open"]) not in ("0", "1")]
    members = read(
        "ci_index_member", 20000, fields=["l1_code", "l1_name", "in_date", "out_date"]
    )
    names = defaultdict(set)
    for row in members:
        names[row["l1_code"]].add(row["l1_name"])
    prices = read(
        "ci_daily",
        100000,
        fields=["ts_code", "trade_date", "open", "close"],
        start_date=warmup_start,
        end_date=end,
    )
    dates, invalid = defaultdict(set), []
    pairs = Counter()
    for row in prices:
        code, day = row["ts_code"], str(row["trade_date"])
        dates[code].add(day)
        pairs[(code, day)] += 1
        if any(
            row[field] is None
            or not math.isfinite(float(row[field]))
            or float(row[field]) <= 0
            for field in ("open", "close")
        ):
            invalid.append({"code": code, "date": day})
    by_code = [
        {
            "code": code,
            "names": sorted(names[code]),
            "sessions": len(dates[code]),
            "missing_dates": sorted(expected - dates[code]),
            "unexpected_dates": sorted(dates[code] - expected),
        }
        for code in EXPECTED_CODES
    ]
    excluded = sorted(
        code
        for code, labels in names.items()
        if labels.intersection(protocol["exclude_industries"])
    )
    missing_names = sorted(
        set(protocol["exclude_industries"])
        - {name for labels in names.values() for name in labels}
    )
    unexpected_codes = sorted(set(dates) - set(EXPECTED_CODES))
    conflicts = sorted(code for code, labels in names.items() if len(labels) != 1)
    missing_code_names = sorted(set(EXPECTED_CODES) - set(names))
    duplicates = sum(count - 1 for count in pairs.values())
    passed = not (
        missing_calendar
        or invalid_calendar
        or invalid
        or duplicates
        or unexpected_codes
        or missing_names
        or conflicts
        or missing_code_names
        or any(item["missing_dates"] or item["unexpected_dates"] for item in by_code)
    )
    return {
        "release_id": release_id,
        "status": "slice_structure_passed" if passed else "slice_gaps",
        "classification": protocol["classification"],
        "comparison_window": protocol["comparison_window"],
        "calendar": {
            "warmup_sessions": warmup,
            "first_comparison_session": comparison_day,
            "warmup_start": warmup_start,
            "derivation": f"SSE first comparison trading-day index minus {warmup} (contract warmup)",
            "expected_trading_sessions": len(expected),
            "missing_calendar_dates": missing_calendar,
            "invalid_is_open_rows": len(invalid_calendar),
        },
        "queries": requests,
        "dataset_metadata": metadata,
        "expected_codes": EXPECTED_CODES,
        "by_code": by_code,
        "price_rows": len(prices),
        "invalid_prices": invalid,
        "duplicate_latest_keys": duplicates,
        "unexpected_codes": unexpected_codes,
        "conflicting_names": conflicts,
        "missing_code_names": missing_code_names,
        "excluded_codes": excluded,
        "missing_exclusion_names": missing_names,
        "included_codes": sorted(set(EXPECTED_CODES) - set(excluded)),
        "included_rows": sum(
            count for (code, _), count in pairs.items() if code not in excluded
        ),
        "unverified": [
            "CITIC classification historical version and official completeness; the 30-code checklist is frozen for this audit only",
            "Historical vendor revisions, index price/return methodology and independent calendar truth",
            "Member in_date/out_date are effective dates, not historical known_at; observation as_of is not PIT",
            "Breadth stock prices/adjustments/capitalization and ETF universe/holdings/execution validity",
            "Reader chooses latest natural-key versions; this is not a raw revision-conflict audit",
            "No strategy computation, returns, case readiness update or production writes",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--config", type=Path, default=REPO / "config/rrg_sector_rotation.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New isolated output directory outside the input root",
    )
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if output == root or root in output.parents or output.exists():
        raise ValueError(
            "Output must be a new isolated directory outside the input root"
        )
    config_path = args.config.resolve()
    with (
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        ) as network,
        patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        ) as dns,
        patch(
            "backend.shared.runtime_secrets.get_secret",
            side_effect=AssertionError("Credentials forbidden"),
        ) as credentials,
        patch(
            "backend.shared.tushare_pipeline.get_secret",
            side_effect=AssertionError("Credentials forbidden"),
        ) as alias,
    ):
        report = verify(root, args.release_id, json.loads(config_path.read_bytes()))
        for mock in (network, dns, credentials, alias):
            mock.assert_not_called()
    report.update(
        checked_at=datetime.now(timezone.utc).isoformat(),
        upstream_calls=0,
        credentials_accessed=False,
        root=str(root),
    )
    report["source"] = {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reader_sha256": hashlib.sha256(
            (REPO / "backend/shared/tushare_store.py").read_bytes()
        ).hexdigest(),
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(output / "report.json"),
                "release_id": args.release_id,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "slice_structure_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
