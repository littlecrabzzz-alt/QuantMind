#!/usr/bin/env python3
"""Prepare isolated research-case signal inputs from an already accepted RRG release."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_pipeline import manifest_at  # noqa: E402
from backend.shared.tushare_store import read_dataset  # noqa: E402

OUTPUTS = {
    "industry_prices": "data/quantdb/1_kline_data/index_daily/tushare_rrg.parquet",
    "calendar": "data/quantdb/2_base_sector/trading_calendar/trading_days.parquet",
}
GAPS = [
    "Official historical CITIC classification, index methodology and revisions are unverified",
    "Historical members lack verified known_at; effective dates and fetched_at are not publication times",
    "Breadth adjusted stock prices and free-float capitalization have not passed this input contract",
    "Historical ETF universe, disclosed exposure and executable open-price semantics remain unverified",
    "Quadrant boundaries, ties, cash weights and independent test period require a frozen protocol",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def day(value):
    return datetime.strptime(value, "%Y%m%d")


def _prepare(
    root,
    release_id,
    config_path,
    report_path,
    report_sha256,
    calendar_release_id,
    calendar_end,
    output,
    research_case_path,
):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root, output = Path(root).resolve(), Path(output).resolve()
    config_path, report_path = Path(config_path).resolve(), Path(report_path).resolve()
    research_case_path = Path(research_case_path).resolve()
    protected = (
        root,
        REPO,
        config_path.parent.parent,
        research_case_path.parent.parent,
    )
    if output.exists() or any(
        output == base or base in output.parents for base in protected
    ):
        raise ValueError("Output must be new and outside source/data repositories")
    if sha(report_path) != report_sha256:
        raise ValueError("Accepted coordinate report fingerprint mismatch")
    report = json.loads(report_path.read_bytes())
    config = json.loads(config_path.read_bytes())
    if (
        report.get("status") != "coordinate_consumer_passed"
        or report.get("release_id") != release_id
        or report.get("source_hashes", {}).get("config") != sha(config_path)
    ):
        raise ValueError("Accepted report, fixed release and config do not match")
    audit = report["slice_audit"]
    protocol = config["protocol"]
    if (
        audit.get("status") != "slice_structure_passed"
        or audit.get("release_id") != release_id
        or report["comparison_window"] != protocol["comparison_window"]
        or report["parameters"] != protocol["parameters"]
        or protocol["classification"] != "中信一级"
    ):
        raise ValueError("Accepted slice/protocol mismatch")
    specs = {spec["id"]: spec for spec in config["datasets"]}
    for identifier, relative in OUTPUTS.items():
        if not Path(relative).match(specs[identifier]["glob"]):
            raise ValueError(
                "Current research input glob differs; review mapping explicitly"
            )
    fingerprints = {
        "config": sha(config_path),
        "research_case": sha(research_case_path),
    }
    manifests = {
        rid: manifest_at(root, rid) for rid in {release_id, calendar_release_id}
    }

    def read(rid, api, query):
        # Same fixed-release reader used by the existing slice/coordinate exports.
        # Drop the projection so original stored fields and provenance survive.
        query = {key: value for key, value in query.items() if key != "fields"}
        table = read_dataset(root, rid, api, **query)
        if len(table) >= query["limit"]:
            raise ValueError("Adapter query reached its explicit bound")
        metadata = json.loads(table.schema.metadata[b"tushare"])
        if metadata["upstream_calls"] != 0 or metadata["release_id"] != rid:
            raise ValueError("Unexpected input provenance")
        return table, metadata

    prices, price_metadata = read(release_id, "ci_daily", audit["queries"]["ci_daily"])
    codes = set(report["included_codes"])
    selected = [row for row in prices.to_pylist() if row["ts_code"] in codes]
    if not codes or len(selected) != report["price_rows"]:
        raise ValueError("Accepted price scope differs from fixed reader result")
    for row in selected:
        row.update(
            time=day(row["trade_date"]),
            IndexCode=row["ts_code"],
            Category=protocol["classification"],
            classification_verification="frozen_audit_scope_only",
            input_release_id=release_id,
        )
    calendar, calendar_metadata = read(
        release_id, "trade_cal", audit["queries"]["trade_cal"]
    )
    warmup = audit["calendar"]["warmup_start"]
    end = protocol["comparison_window"][1].replace("-", "")
    if day(calendar_end) <= day(end) or (day(calendar_end) - day(end)).days > 31:
        raise ValueError(
            "Calendar supplement must cover 1..31 days after comparison end"
        )
    supplement_query = {
        "date_field": "cal_date",
        "start_date": (day(end) + timedelta(days=1)).strftime("%Y%m%d"),
        "end_date": calendar_end,
        "limit": 100,
    }
    supplement, supplement_metadata = read(
        calendar_release_id, "trade_cal", supplement_query
    )
    calendar_rows = []
    for table, rid, lo, hi in (
        (calendar, release_id, warmup, end),
        (supplement, calendar_release_id, supplement_query["start_date"], calendar_end),
    ):
        for original in table.to_pylist():
            if original["exchange"] != "SSE" or not lo <= original["cal_date"] <= hi:
                continue
            row = dict(original)
            if str(row["is_open"]) not in ("0", "1"):
                raise ValueError("Invalid calendar open flag")
            row.update(
                TradingDate=day(row["cal_date"]),
                IsTradingDay=int(row["is_open"]),
                input_release_id=rid,
            )
            calendar_rows.append(row)
    dates = [row["cal_date"] for row in calendar_rows]
    if len(dates) != len(set(dates)):
        raise ValueError("Conflicting calendar rows require explicit review")
    available = set(dates)
    for offset in range(1, (day(calendar_end) - day(end)).days + 1):
        if (day(end) + timedelta(days=offset)).strftime("%Y%m%d") not in available:
            raise ValueError("Calendar supplement has missing dates")
    open_days = sorted(row["cal_date"] for row in calendar_rows if row["IsTradingDay"])
    mapping = []
    for previous in report["month_end_mapping"]:
        signal = previous["signal_close_date"].replace("-", "")
        following = next((value for value in open_days if value > signal), None)
        next_open = day(following).date().isoformat() if following else None
        if previous.get("next_open_date") and previous["next_open_date"] != next_open:
            raise ValueError("Previously accepted next-session mapping changed")
        mapping.append(
            {
                "signal_close_date": previous["signal_close_date"],
                "next_open_date": next_open,
                "calendar_release_id": calendar_release_id
                if following and following > end
                else release_id,
                "status": "calendar_mapped_only"
                if next_open
                else "next_session_unavailable",
                "execution_price_verified": False,
            }
        )
    gaps = list(GAPS)
    if any(row["next_open_date"] is None for row in mapping):
        gaps.append("A next trading session remains outside the calendar supplement")
    tables = {
        "industry_prices": pa.Table.from_pylist(selected),
        "calendar": pa.Table.from_pylist(
            sorted(calendar_rows, key=lambda row: row["cal_date"])
        ),
    }
    structure = []
    for identifier, table in tables.items():
        missing = set(specs[identifier]["required_columns"]) - set(table.column_names)
        if missing:
            raise ValueError(
                "Mapped table lacks current research input columns: "
                + ",".join(sorted(missing))
            )
        structure.append(
            {"id": identifier, "status": "passed_structure_only", "rows": len(table)}
        )
    unprepared = [
        spec["id"] for spec in config["datasets"] if spec["id"] not in OUTPUTS
    ]
    metadata = {
        "schema_version": 1,
        "status": "signal_input_mapping_prepared",
        "workflow_stage": "blocked_data",
        "research_ready": False,
        "local_reproduction": False,
        "automatic_trading_authorized": False,
        "release_id": release_id,
        "calendar_release_id": calendar_release_id,
        "accepted_report": {"path": str(report_path), "sha256": report_sha256},
        "source_config": {"path": str(config_path), "sha256": fingerprints["config"]},
        "research_case_reference": {
            "path": str(research_case_path),
            "sha256": fingerprints["research_case"],
            "source_copied_or_executed": False,
        },
        "adapter_sha256": sha(__file__),
        "structure": structure,
        "unprepared_datasets": unprepared,
        "review_gates": [
            {"id": gate["id"], "status": "unknown"} for gate in config["review_gates"]
        ],
        "remaining_gaps": gaps,
        "month_end_mapping": mapping,
        "mapping": {
            "industry_prices": {"ts_code": "IndexCode", "trade_date": "time"},
            "calendar": {"cal_date": "TradingDate", "is_open": "IsTradingDay"},
            "Category": "Frozen audit label; official historical classification is unverified",
        },
        "reader_metadata": [price_metadata, calendar_metadata, supplement_metadata],
        "source_queries": [
            {
                "release_id": release_id,
                "api_name": "ci_daily",
                "query": {
                    k: v
                    for k, v in audit["queries"]["ci_daily"].items()
                    if k != "fields"
                },
            },
            {
                "release_id": release_id,
                "api_name": "trade_cal",
                "query": {
                    k: v
                    for k, v in audit["queries"]["trade_cal"].items()
                    if k != "fields"
                },
            },
            {
                "release_id": calendar_release_id,
                "api_name": "trade_cal",
                "query": supplement_query,
            },
        ],
        "source_partitions": [
            {"release_id": rid, **dataset}
            for rid, manifest in sorted(manifests.items())
            for dataset in manifest["datasets"]
            if dataset["api_name"]
            in (("ci_daily", "trade_cal") if rid == release_id else ("trade_cal",))
        ],
        "upstream_calls": 0,
        "credentials_accessed": False,
        "scope_note": "Existing accepted report reused; no coordinate recomputation, full-industry re-audit, portfolio or return calculation",
    }
    if (
        sha(config_path) != fingerprints["config"]
        or sha(research_case_path) != fingerprints["research_case"]
    ):
        raise ValueError("Research reference changed while preparing inputs")
    output.mkdir(parents=True, exist_ok=False)
    for identifier, table in tables.items():
        path = output / OUTPUTS[identifier]
        path.parent.mkdir(parents=True, exist_ok=True)
        table = table.replace_schema_metadata(
            {
                b"rrg_input": json.dumps(
                    {
                        "workflow_stage": "blocked_data",
                        "release_id": release_id,
                        "calendar_release_id": calendar_release_id,
                        "known_at_verified": False,
                    }
                ).encode()
            }
        )
        pq.write_table(table, path, compression="zstd")
    (output / "input-report.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )
    paths = [*OUTPUTS.values(), "input-report.json"]
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    name: {
                        "sha256": sha(output / name),
                        "bytes": (output / name).stat().st_size,
                    }
                    for name in paths
                }
            },
            indent=2,
        )
        + "\n"
    )
    return metadata


def prepare(*args, **kwargs):
    """No sockets, secrets, source writes or research-state updates during adaptation."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline adapter boundary"))
            )
        return _prepare(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "config", "coordinate-report", "research-case", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("release-id", "report-sha256", "calendar-release-id", "calendar-end"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    report = prepare(
        args.root,
        args.release_id,
        args.config,
        args.coordinate_report,
        args.report_sha256,
        args.calendar_release_id,
        args.calendar_end,
        args.output,
        args.research_case,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "workflow_stage": report["workflow_stage"],
                "structure": report["structure"],
                "upstream_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
