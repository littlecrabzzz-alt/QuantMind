#!/usr/bin/env python3
"""Audit public documentation; prepare or execute bounded RRG data probes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from backend.shared.runtime_secrets import get_secret
from backend.shared.stock_utils import StockCodeUtil
from backend.shared.tushare_intake import (
    DOC_ROOT,
    DocParser,
    capture_sample,
    digest,
    parse_document,
    utc_now,
    verify_release,
)

# Explicit reviewed read-only probes. Never dispatch arbitrary catalogue entries
# (the official sidebar also includes portfolio save/delete endpoints).
RRG_PROBES = [
    ("trade_cal", 6000, ["cal_date", "is_open"], {"exchange": "SSE"}),
    ("ci_daily", 4000, ["ts_code", "trade_date", "open", "close"], {}),
    (
        "ci_index_member",
        5000,
        ["l1_code", "l1_name", "ts_code", "in_date", "out_date"],
        {"is_new": "Y"},
    ),
    (
        "ci_index_member",
        5000,
        ["l1_code", "l1_name", "ts_code", "in_date", "out_date"],
        {"is_new": "N"},
    ),
    ("etf_basic", 5000, ["ts_code", "list_date", "list_status"], {"list_status": "L"}),
    ("etf_basic", 5000, ["ts_code", "list_date", "list_status"], {"list_status": "D"}),
    ("etf_basic", 5000, ["ts_code", "list_date", "list_status"], {"list_status": "P"}),
    (
        "fund_daily",
        5000,
        ["ts_code", "trade_date", "open", "close", "vol", "amount"],
        {},
    ),
    ("fund_adj", 2000, ["ts_code", "trade_date", "adj_factor"], {}),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def refresh_catalog(output):
    # Public metadata only. Direct HTTPS avoids inheriting secret-bearing proxy
    # configuration; TLS verification stays enabled. Four bounded public readers.
    with httpx.Client(trust_env=False, timeout=30, follow_redirects=False) as client:
        index = client.get(DOC_ROOT)
        index.raise_for_status()
        parser = DocParser()
        parser.feed(index.text)
        if not parser.links:
            raise ValueError("Official catalogue links were not found")

        def read(entry):
            doc_id, title = entry
            time.sleep(0.25)
            try:
                response = client.get(f"{DOC_ROOT}?doc_id={doc_id}")
                response.raise_for_status()
                return parse_document(response.text, doc_id, title)
            except httpx.HTTPError as exc:
                return {
                    "doc_id": doc_id,
                    "title": title,
                    "url": f"{DOC_ROOT}?doc_id={doc_id}",
                    "audit_status": "fetch_failed",
                    "error_type": type(exc).__name__,
                    "permission_status": "unprobed",
                    "coverage_status": "not_ingested",
                }

        with ThreadPoolExecutor(max_workers=4) as pool:
            entries = list(pool.map(read, parser.links.items()))
    value = {
        "schema_version": 1,
        "fetched_at": utc_now(),
        "source": DOC_ROOT,
        "index_sha256": digest(index.content),
        "entry_count": len(entries),
        "entries": entries,
    }
    write_json(output, value)
    return {
        "entry_count": len(entries),
        "status_counts": {
            status: sum(e["audit_status"] == status for e in entries)
            for status in sorted({e["audit_status"] for e in entries})
        },
    }


def probe_jobs(catalog, date, fund=None, period=None):
    datetime.strptime(date, "%Y%m%d")
    definitions = list(RRG_PROBES)
    if bool(fund) != bool(period):
        raise ValueError("Supply both --fund and --period")
    if fund:
        if not re.fullmatch(r"(SH|SZ)[0-9]{6}", fund):
            raise ValueError("Use an internal prefix-format ETF code")
        datetime.strptime(period, "%Y%m%d")
        if period[4:] not in {"0331", "0630", "0930", "1231"}:
            raise ValueError("Period must be a quarter end")
        definitions.append(
            (
                "fund_portfolio",
                2000,
                ["ts_code", "ann_date", "end_date", "symbol", "mkv"],
                {"ts_code": StockCodeUtil.to_suffix(fund), "period": period},
            )
        )
    jobs = []
    for api, cap, required, base in definitions:
        docs = [e for e in catalog["entries"] if api in e.get("api_names", [])]
        fields = sorted({f for e in docs for f in e.get("output_fields", [])})
        if not fields:
            raise ValueError(f"No audited output schema for {api}; refresh catalogue")
        params = dict(base)
        if api == "trade_cal":
            params.update(start_date=date, end_date=date)
        elif api in {"ci_daily", "fund_daily", "fund_adj"}:
            params["trade_date"] = date
        jobs.append(
            {
                "api_name": api,
                "params": params,
                "fields": ",".join(fields),
                "row_cap": cap,
                "cap_source": "conservative_probe_threshold"
                if api in {"trade_cal", "fund_portfolio"}
                else "official_documentation",
                "required_fields": required,
                "nullable_fields": ["out_date"] if api == "ci_index_member" else [],
                "source_docs": [e["url"] for e in docs],
            }
        )
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    catalogue = commands.add_parser("catalog")
    catalogue.add_argument("--output", type=Path, required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--catalog", type=Path, required=True)
    probe.add_argument("--date", required=True, help="One known trading day, YYYYMMDD")
    probe.add_argument("--fund", help="Optional representative ETF, prefix format")
    probe.add_argument("--period", help="Holdings report quarter end, YYYYMMDD")
    probe.add_argument("--output", type=Path, required=True, help="Preparation report")
    probe.add_argument(
        "--execute",
        action="store_true",
        help="Execute only inside verified cloud authority container",
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--release-id", required=True)
    args = parser.parse_args()
    if args.command == "catalog":
        print(json.dumps(refresh_catalog(args.output), ensure_ascii=False))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_release(args.root, args.release_id)))
        return 0
    catalog_bytes = args.catalog.read_bytes()
    jobs = probe_jobs(json.loads(catalog_bytes), args.date, args.fund, args.period)
    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "catalog_sha256": digest(catalog_bytes),
        "jobs": jobs,
        "status": "prepared",
        "rrg_status": "blocked_data",
        "limitations": [
            "sample_only",
            "holdings_probe_requires_fund_and_period",
            "historical_members_known_at_unverified",
            "ci_daily_open_may_be_unavailable",
        ],
    }
    if not args.execute:
        # Preparation never loads credentials and does not contact the data API.
        write_json(args.output, report)
        print(json.dumps({"status": "prepared", "jobs": len(jobs)}))
        return 0
    root = Path("/data/tushare")
    if os.getenv("QM_NODE_ROLE") != "authority" or not Path("/.dockerenv").exists():
        raise ValueError("Execution requires the verified cloud authority container")
    if root.resolve() != root or not Path("/data").is_mount():
        raise ValueError("Expected authority /data mount; verify Compose mounts")
    token = get_secret("TUSHARE_TOKEN")
    if not token:
        report["status"] = "blocked_missing_token"
        write_json(args.output, report)
        print(json.dumps({"status": report["status"]}))
        return 2
    # Conservative bounded probe: no scheduler, no retries, no backfill watermark.
    with httpx.Client(trust_env=False, timeout=30, follow_redirects=False) as client:
        results = []
        for job in jobs:
            results.append(capture_sample(client, token, job, root))
            time.sleep(3)
    report.update(status="probed", results=results)
    release_id = "probe-" + uuid4().hex
    # Immutable manifest can be mirrored only with its referenced observations
    # and objects. It is evidence of sampling, never a research-ready release.
    release = root / "releases" / release_id
    release.mkdir(parents=True)
    write_json(release / "manifest.json", report)
    write_json(args.output, {**report, "release_id": release_id})
    print(
        json.dumps(
            {
                "status": "probed",
                "release_id": release_id,
                "results": [r["status"] for r in results],
            }
        )
    )
    return 0 if all(r["status"] == "sample_ok" for r in results) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, httpx.HTTPError) as exc:
        # Generic safe error type: upstream/request details never go to logs.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
