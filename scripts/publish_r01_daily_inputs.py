#!/usr/bin/env python3
"""Publish the R01 daily incremental input package (H2.1-D1/D2).

Derives one decision-day package (`package_version = d<YYYYMMDD>`, schema v3.1
compatible extension of ``etf-input-package`` v3) for the 9-symbol R01 pool
from one frozen Mac Tushare archive release, reusing the release verification,
manifest and unit-conversion code paths of ``prepare_r01_etf_inputs.py``.

Each package binds the decision date to its data version identity quintuple
(decision_date, package_id, package_version, source_release_id,
manifest_sha256), records ``data_as_of`` (data cutoff trade date) and
``obtained_at`` (source partition fetch time), and embeds a quality gate
(market rows / factors / dividend events / trading status / warmup /
units+hashes). Invalid, late or incomplete data produces an explicit
``data_blocked`` result — stale data must never masquerade as a same-day
execution. The historical v2 frozen package is never touched; a revision is a
new package version with ``revised=true`` + ``supersedes``.

No supplier requests are made; reading the archive CURRENT pointer only
selects a release and never triggers collection.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_r01_etf_inputs as base  # noqa: E402  (owned sibling module)

DEFAULT_OUTPUT_ROOT = base.DEFAULT_OUTPUT_ROOT
DEFAULT_REGISTRY = base.DEFAULT_REGISTRY
POOL = base.POOL
SUFFIX_TO_PREFIX = base.SUFFIX_TO_PREFIX

REQUIRED_ROLES = ("primary",)  # symbols whose missing day blocks the gate
CONTINUITY_TOL = base.CONTINUITY_TOL
DIV_MATCH_TOL = base.DIV_MATCH_TOL
SCHEMA_VERSION = 3.1

VWAP_TOL = 0.005


def resolve_release(root: Path, release_id: str | None) -> str:
    if release_id:
        return release_id
    pointer = json.loads((root / "CURRENT.json").read_text())
    resolved = pointer.get("release_id")
    if not resolved:
        raise SystemExit("Archive CURRENT pointer has no release_id")
    return resolved


def verify_release(root: Path, release_id: str):
    release_hash = release_id.removeprefix("data-")
    raw = (root / "releases" / release_id / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != release_hash:
        raise SystemExit("Release manifest checksum mismatch")
    return json.loads(raw)


def evaluate_data_readiness(manifest: dict, manifest_sha256: str | None = None) -> dict:
    """H2.1-D2 data-readiness gate (pure; runner consumes this signature).

    Returns ``{ready, data_blocked, blocked_reasons, identity, data_as_of,
    obtained_at}``. ``ready=False`` means the affected decision for
    ``decision_date`` must be explicitly blocked; using older data as if the
    day had executed is forbidden.
    """
    reasons = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        reasons.append(
            f"schema_version {manifest.get('schema_version')} != {SCHEMA_VERSION}"
        )
    if manifest.get("package_kind") != "daily_increment":
        reasons.append(
            f"package_kind {manifest.get('package_kind')!r} != 'daily_increment'"
        )
    version = str(manifest.get("package_version", ""))
    if not version.startswith("d"):
        reasons.append(f"package_version {version!r} is not a d<date> daily version")
    for field in (
        "decision_date",
        "data_as_of",
        "obtained_at",
        "source_release_id",
        "package_id",
    ):
        if not manifest.get(field):
            reasons.append(f"missing identity field {field}")
    gate = manifest.get("quality_gate") or {}
    if gate.get("overall") != "pass":
        reasons.extend(gate.get("blocked_reasons") or ["quality_gate.overall != pass"])
    decision = manifest.get("decision_date")
    as_of = manifest.get("data_as_of")
    if decision and as_of and as_of < decision:
        reasons.append(
            f"stale-data: data_as_of {as_of} < decision_date {decision} "
            f"(late/incomplete data; executing with older data as same-day is forbidden)"
        )
    if gate and not gate.get("decision_date_is_trade_day", True):
        reasons.append(f"decision_date {decision} is not an SSE open day")
    if manifest.get("revised") and not manifest.get("supersedes"):
        reasons.append("revised package must carry supersedes")
    identity = {
        "decision_date": decision,
        "package_id": manifest.get("package_id"),
        "package_version": version,
        "source_release_id": manifest.get("source_release_id"),
        "manifest_sha256": manifest_sha256,
    }
    return {
        "ready": not reasons,
        "data_blocked": bool(reasons),
        "blocked_reasons": reasons,
        "identity": identity,
        "data_as_of": as_of,
        "obtained_at": manifest.get("obtained_at"),
    }


def _factor_event_for_day(
    day8, prev8, row_d, row_p, f_prev, f_new, div_cash, prefix, nav_lookup=None
):
    """Typed events for a single factor transition (v3 structure)."""
    events = []
    if f_prev is None or f_new is None or f_prev == f_new:
        return events
    pre = float(row_d["pre_close"]) if row_d is not None else None
    prev_close = float(row_p["close"]) if row_p is not None else None
    cash = sum(div_cash or [])
    if cash > 0 and pre and pre > cash:
        implied = f_prev * pre / (pre - cash)
        residual = abs(f_new - implied) / max(implied, 1e-12)
        year = f"{day8}"
        ev = {
            "event_date": base._iso(day8),
            "event_type": "cash_dividend",
            "cash_per_share": round(cash, 6),
            "qty_multiplier": 1.0,
            "event_id": f"fund_div:{prefix}:{day8}:{year}",
            "record_date": None,
            "record_date_status": "unknown_blocked",
            "pay_date": None,
            "pay_date_status": "unknown_blocked",
            "entitlement_basis": "record_date_close_holdings",
            "basis_note": "",
            "derived_from": {
                "adj_factor_prev": float(f_prev),
                "adj_factor_new": float(f_new),
                "fund_div_ref": f"fund_div:{prefix}:{day8}",
            },
            "verification": {
                "passed": residual <= DIV_MATCH_TOL,
                "method": "fund_div_match",
                "detail": f"div_cash={cash:.6g}/share; implied_factor={implied:.6f}; residual={residual:.5%}",
            },
        }
        events.append(ev)
    else:
        m = f_new / f_prev
        cont = None
        if pre and prev_close and prev_close > 0 and pre > 0:
            cont = (pre * f_new) / (prev_close * f_prev)
        passed = cont is not None and abs(cont - 1.0) <= CONTINUITY_TOL
        events.append(
            {
                "event_date": base._iso(day8),
                "event_type": "share_adjustment",
                "cash_per_share": 0.0,
                "qty_multiplier": round(m, 8),
                "basis_note": "",
                "derived_from": {
                    "adj_factor_prev": float(f_prev),
                    "adj_factor_new": float(f_new),
                },
                "verification": {
                    "passed": bool(passed),
                    "method": "pre_close_continuity" if passed else "unresolved_gap",
                    "detail": f"hfq continuity ratio={cont:.6f}"
                    if cont is not None
                    else "pre_close unavailable",
                },
            }
        )
    return events


def publish(args):
    root = args.root.expanduser().resolve()
    release_id = resolve_release(root, args.release_id)
    rel_manifest = verify_release(root, release_id)
    print(
        f"[release] {release_id} verified ({len(rel_manifest['datasets'])} dataset files)",
        flush=True,
    )

    # ---- calendar
    cal_rows, _, _ = base.collect_api(root, rel_manifest, "trade_cal", args.workers)
    cal, _ = base.latest_version(pd.DataFrame(cal_rows), ["exchange", "cal_date"])
    sse = cal[cal["exchange"] == "SSE"].sort_values("cal_date")
    sse_open = [str(d) for d in sse[sse["is_open"] == 1]["cal_date"]]
    open_set = set(sse_open)

    # ---- pool scans (hash-verified per file)
    daily_rows, _, _ = base.collect_api(root, rel_manifest, "fund_daily", args.workers)
    adj_rows, _, _ = base.collect_api(root, rel_manifest, "fund_adj", args.workers)
    div_rows, _, _ = base.collect_api(root, rel_manifest, "fund_div", args.workers)
    limit_rows, _, _ = base.collect_api(root, rel_manifest, "etf_limit", args.workers)
    daily, _ = base.latest_version(pd.DataFrame(daily_rows), ["ts_code", "trade_date"])
    adj, _ = base.latest_version(pd.DataFrame(adj_rows), ["ts_code", "trade_date"])
    div, _ = base.latest_version(
        pd.DataFrame(div_rows), ["ts_code", "ex_date", "base_year", "div_cash"]
    )
    limit, _ = base.latest_version(pd.DataFrame(limit_rows), ["ts_code", "trade_date"])

    # ---- decision date + previous trade day + obtained_at
    all_pool_dates = sorted({str(d) for d in daily["trade_date"]})
    if not all_pool_dates:
        raise SystemExit("Release has no pool rows")
    decision8 = args.decision_date or all_pool_dates[-1]
    if decision8 not in open_set:
        raise SystemExit(
            f"decision_date {decision8} is not an SSE open day in the release calendar"
        )
    if decision8 not in set(all_pool_dates):
        raise SystemExit(
            f"decision_date {decision8} has no pool data in release {release_id}"
        )
    earlier = [d for d in sse_open if d < decision8]
    prev8 = earlier[-1] if earlier else None
    day_rows = daily[daily["trade_date"] == decision8]
    fetched = [base._instant(v) for v in day_rows["_fetched_at"]]
    obtained_at = max(fetched) if fetched else None
    if obtained_at and not obtained_at.endswith("Z"):
        obtained_at = obtained_at.replace("+00:00", "Z")
    print(
        f"[day] decision={decision8} prev_trade_day={prev8} obtained_at={obtained_at} rows={len(day_rows)}",
        flush=True,
    )

    version = args.package_version or ("d" + decision8 + (args.revision or ""))
    package_dir = args.output_root.expanduser() / version
    if package_dir.exists():
        if not args.force:
            raise SystemExit(
                f"Package directory already exists: {package_dir} (use --force)"
            )
        shutil.rmtree(package_dir)
    for sub in ("daily", "factors", "events", "etf_limit"):
        (package_dir / sub).mkdir(parents=True)

    registry = {"packages": {}}
    if args.registry.exists():
        registry = json.loads(args.registry.read_text())
    baseline_entry = registry["packages"].get(args.baseline)
    if not baseline_entry:
        raise SystemExit(f"Baseline package {args.baseline} not found in registry")
    baseline = {
        "package_uri": args.baseline,
        "manifest_sha256": baseline_entry.get("manifest_sha256")
        or _registry_manifest_sha(Path(baseline_entry["absolute_path"])),
    }

    # ---- per-symbol derivation
    symbols_meta = []
    market_detail = {}
    factors_detail = {}
    vwap_bad = []
    events_by_code = {}
    limit_bad = []

    for code, klass, role in POOL:
        prefix = SUFFIX_TO_PREFIX[code]
        rows_d = daily[
            (daily["ts_code"] == prefix) & (daily["trade_date"] == decision8)
        ]
        row_p = (
            daily[(daily["ts_code"] == prefix) & (daily["trade_date"] == prev8)]
            if prev8
            else pd.DataFrame()
        )
        row_d = rows_d.iloc[0].to_dict() if len(rows_d) else None
        prev_row = row_p.iloc[0].to_dict() if len(row_p) else None

        out = (
            pd.DataFrame(
                {
                    "ts_code": pd.Series([code], dtype=str),
                    "trade_date": pd.Series([decision8], dtype=str),
                    "open": pd.Series(
                        [float(row_d["open"])] if row_d else [None], dtype="float64"
                    ),
                    "high": pd.Series(
                        [float(row_d["high"])] if row_d else [None], dtype="float64"
                    ),
                    "low": pd.Series(
                        [float(row_d["low"])] if row_d else [None], dtype="float64"
                    ),
                    "close": pd.Series(
                        [float(row_d["close"])] if row_d else [None], dtype="float64"
                    ),
                    "pre_close": pd.Series(
                        [float(row_d["pre_close"])] if row_d else [None],
                        dtype="float64",
                    ),
                    "vol_shares": pd.Series(
                        [round(float(row_d["vol"]) * 100.0, 2)] if row_d else [None],
                        dtype="float64",
                    ),
                    "amount_cny": pd.Series(
                        [round(float(row_d["amount"]) * 1000.0, 3)]
                        if row_d
                        else [None],
                        dtype="float64",
                    ),
                }
            )
            if row_d
            else _empty_daily(code, decision8)
        )
        pq.write_table(
            pa.Table.from_pandas(out), package_dir / "daily" / f"{code}.parquet"
        )

        f_d = adj[(adj["ts_code"] == prefix) & (adj["trade_date"] == decision8)]
        f_p = (
            adj[(adj["ts_code"] == prefix) & (adj["trade_date"] == prev8)]
            if prev8
            else pd.DataFrame()
        )
        factor = float(f_d.iloc[0]["adj_factor"]) if len(f_d) else None
        factor_prev = float(f_p.iloc[0]["adj_factor"]) if len(f_p) else None
        fq = pd.DataFrame(
            {
                "ts_code": [code],
                "trade_date": [decision8],
                "adj_factor": [factor],
            }
        )
        pq.write_table(
            pa.Table.from_pandas(fq), package_dir / "factors" / f"{code}.parquet"
        )

        code_div = (
            div[(div["ts_code"] == prefix) & (div["ex_date"].astype(str) == decision8)]
            if len(div)
            else pd.DataFrame()
        )
        div_cash = [float(v) for v in code_div["div_cash"]] if len(code_div) else []
        events = _factor_event_for_day(
            decision8, prev8, row_d, prev_row, factor_prev, factor, div_cash, prefix
        )
        # dividend record/pay dates from fund_div raw (never default to ex_date)
        for e in events:
            if e["event_type"] != "cash_dividend":
                continue
            if len(code_div):
                r = code_div.iloc[0]
                rec = None if pd.isna(r["record_date"]) else str(r["record_date"])
                pay = None if pd.isna(r["pay_date"]) else str(r["pay_date"])
                e["record_date"] = base._iso(rec) if rec else None
                e["record_date_status"] = "known" if rec else "unknown_blocked"
                e["pay_date"] = base._iso(pay) if pay else None
                e["pay_date_status"] = "known" if pay else "unknown_blocked"
                base_year = (
                    str(r["base_year"])
                    if not pd.isna(r["base_year"])
                    else f"{float(r['div_cash']):g}"
                )
                e["event_id"] = f"fund_div:{prefix}:{decision8}:{base_year}"
            blocked = (
                e["record_date_status"] == "unknown_blocked"
                or e["pay_date_status"] == "unknown_blocked"
            )
            if blocked:
                e["verification"] = {
                    "passed": False,
                    "method": "unresolved_gap",
                    "detail": f"dividend dates blocked; {e['verification']['detail']}",
                }
        if events:
            base._write_events_parquet_v3(
                package_dir / "events" / f"{code}.parquet", code, events
            )
            events_by_code[code] = events

        code_limit = limit[
            (limit["ts_code"] == "FUND:" + code) & (limit["trade_date"] == decision8)
        ]
        if len(code_limit):
            r = code_limit.iloc[0]
            out_limit = pd.DataFrame(
                {
                    "ts_code": [code],
                    "trade_date": [decision8],
                    "pre_close": [float(r["pre_close"])],
                    "up_limit": [float(r["up_limit"])],
                    "down_limit": [float(r["down_limit"])],
                    "asset_type": [str(r["asset_type"])],
                }
            )
            pq.write_table(
                pa.Table.from_pandas(out_limit),
                package_dir / "etf_limit" / f"{code}.parquet",
            )
            if row_d:
                close = float(row_d["close"])
                if not (
                    float(r["down_limit"]) * 0.9999
                    <= close
                    <= float(r["up_limit"]) * 1.0001
                ):
                    limit_bad.append(
                        (code, close, float(r["down_limit"]), float(r["up_limit"]))
                    )

        if row_d and row_d["vol"] and row_d["amount"]:
            vwap = (float(row_d["amount"]) * 1000.0) / (float(row_d["vol"]) * 100.0)
            if not (
                float(row_d["low"]) * (1 - VWAP_TOL)
                <= vwap
                <= float(row_d["high"]) * (1 + VWAP_TOL)
            ):
                vwap_bad.append((code, round(vwap, 4)))
        market_detail[code] = {
            "role": role,
            "row": row_d is not None,
            "vol_zero": bool(row_d and float(row_d["vol"]) == 0),
        }
        factors_detail[code] = {"factor": factor, "factor_prev": factor_prev}

        baseline_symbol = _baseline_symbol(baseline_entry, code)
        symbols_meta.append(
            {
                "code": code,
                "class": klass,
                "role": role,
                "data_start": base._iso(decision8),
                "data_end": base._iso(decision8),
                "missing_days": [] if row_d is not None else [decision8],
                "warmup_start": baseline_symbol.get("warmup_start")
                if baseline_symbol
                else base._iso(decision8),
            }
        )

    pq.write_table(
        pa.Table.from_pandas(
            sse[["exchange", "cal_date", "is_open", "pretrade_date"]].reset_index(
                drop=True
            )
        ),
        package_dir / "calendar.parquet",
    )

    # ---- quality gate (D1 producer side)
    required_missing = [
        c
        for c, d in market_detail.items()
        if d["role"] in REQUIRED_ROLES and not d["row"]
    ]
    optional_missing = [
        c
        for c, d in market_detail.items()
        if d["role"] not in REQUIRED_ROLES and not d["row"]
    ]
    factors_missing = [c for c, fd in factors_detail.items() if fd["factor"] is None]
    unverified_events = [
        f"{c}:{e['event_date']}"
        for c, evs in events_by_code.items()
        for e in evs
        if not e["verification"]["passed"]
    ]
    warmup_ok = all(
        _months_between(s["warmup_start"], base._iso(decision8)) >= base.WARMUP_MONTHS
        for s in symbols_meta
        if s["role"] in REQUIRED_ROLES
    )

    checks = {
        "calendar": {
            "status": "pass" if decision8 in open_set else "fail",
            "detail": {"decision_date_is_trade_day": decision8 in open_set},
        },
        "market_rows": {
            "status": "fail" if required_missing else "pass",
            "detail": {
                "required_missing": required_missing,
                "optional_missing": optional_missing,
                "per_symbol": market_detail,
            },
        },
        "factors": {
            "status": "fail" if factors_missing else "pass",
            "detail": {"missing": factors_missing, "per_symbol": factors_detail},
        },
        "dividend_events": {
            "status": "fail" if unverified_events else "pass",
            "detail": {
                "events": {
                    c: [e["event_type"] for e in evs]
                    for c, evs in events_by_code.items()
                },
                "unverified": unverified_events,
            },
        },
        "trading_status": {
            "status": "fail" if vwap_bad or limit_bad else "pass",
            "detail": {
                "zero_volume": [c for c, d in market_detail.items() if d["vol_zero"]],
                "vwap_out_of_range": vwap_bad,
                "limit_violations": limit_bad,
            },
        },
        "warmup": {
            "status": "pass" if warmup_ok else "fail",
            "detail": {
                "required_months": base.WARMUP_MONTHS,
                "baseline": args.baseline,
            },
        },
        "units_and_hashes": {
            "status": "pass",
            "detail": {
                "rule": "source files SHA256-verified during scan; "
                "vol_shares=vol*100, amount_cny=amount*1000; SHA256SUMS recomputed on write"
            },
        },
    }
    blocked_reasons = [
        f"{name}: {c['detail']}"
        if isinstance(c.get("detail"), str)
        else f"{name}: {c['status']}"
        for name, c in checks.items()
        if c["status"] != "pass"
    ]
    as_of_iso = base._iso(decision8)
    gate = {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall": "pass" if not blocked_reasons else "blocked",
        "blocked_reasons": blocked_reasons,
        "decision_date_is_trade_day": decision8 in open_set,
        "checks": checks,
    }

    manifest_out = {
        "schema_version": SCHEMA_VERSION,
        "package_id": f"r01-etf-daily-{release_id.removeprefix('data-')[:12]}-d{decision8}",
        "package_version": version,
        "package_uri": f"node://mac/r01-etf-daily/{version}",
        "source_release_id": release_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_by_node": "mac",
        "source_datasets": [],  # filled below
        "unit_conversions": {
            "vol": "lot(100 shares) -> shares, multiply by 100",
            "amount": "thousand CNY -> CNY, multiply by 1000",
            "rules": (
                "Same conversion as the v2 fixed package (see its manifest). Source files of every "
                "scanned api are SHA256-verified against the frozen release manifest before parsing; "
                "this manifest's source_datasets[].sha256 uses the same file-list digest rule."
            ),
        },
        "factor_convention": {
            "formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
            "verified_cases": [
                f"{c} {e['event_date']} {e['event_type']} verification={e['verification']['method']}"
                for c, evs in events_by_code.items()
                for e in evs
            ]
            or ["no events on decision_date"],
        },
        "symbols": symbols_meta,
        "known_gaps": [
            {
                "gap_id": "DG-004",
                "desc": "etf_limit reference prices only from 2019-06-26; earlier dates use the "
                "declared ±10% rule approximation (product constraints).",
                "handling": "rule-approximation-declared",
            },
        ],
        # ---- v3.1 optional extension fields (daily increment identity + gating)
        "package_kind": "daily_increment",
        "decision_date": as_of_iso,
        "data_as_of": as_of_iso,
        "obtained_at": obtained_at,
        "baseline_package": baseline,
        "quality_gate": gate,
        "revised": bool(args.revision),
        "supersedes": None,
    }
    for api in base.SOURCE_APIS:
        entries = [e for e in rel_manifest["datasets"] if e.get("api_name") == api]
        lines = "".join(
            f"{e['path']} {e['sha256']}\n"
            for e in sorted(entries, key=lambda e: e["path"])
        )
        manifest_out["source_datasets"].append(
            {
                "api_name": api,
                "sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
            }
        )
    if args.revision:
        prior_uri = f"node://mac/r01-etf-daily/d{decision8}"
        prior = registry["packages"].get(prior_uri)
        if not prior:
            raise SystemExit(
                f"Revision requires an existing original package {prior_uri}"
            )
        prior_dir = Path(prior["absolute_path"])
        manifest_out["supersedes"] = {
            "package_version": f"d{decision8}",
            "manifest_sha256": base.sha256_file(prior_dir / "manifest.json"),
        }

    (package_dir / "manifest.json").write_text(
        json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n"
    )
    (package_dir / "README.md").write_text(
        _readme(version, decision8, release_id, args, gate, prev8), encoding="utf-8"
    )
    report = {
        "kind": "daily_increment",
        "decision_date": as_of_iso,
        "prev_trade_day": base._iso(prev8) if prev8 else None,
        "source_release_id": release_id,
        "obtained_at": obtained_at,
        "package_version": version,
        "baseline": baseline,
        "quality_gate": gate,
        "market_rows": market_detail,
        "factors": factors_detail,
        "events": dict(events_by_code),
        "revised": manifest_out["revised"],
        "supersedes": manifest_out["supersedes"],
    }
    (package_dir / "derivation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    base._write_sums(package_dir)

    # ---- registry
    uri = manifest_out["package_uri"]
    registry["packages"][uri] = {
        "absolute_path": str(package_dir),
        "package_id": manifest_out["package_id"],
        "package_version": version,
        "source_release_id": release_id,
        "created_at": manifest_out["generated_at"],
        "kind": "daily_increment",
        "decision_date": as_of_iso,
        "baseline": args.baseline,
        "manifest_sha256": base.sha256_file(package_dir / "manifest.json"),
        "revised": manifest_out["revised"],
        "supersedes": manifest_out["supersedes"],
    }
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=args.registry.parent)
    with os.fdopen(fd, "w") as handle:
        json.dump(registry, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, args.registry)

    manifest_sha = base.sha256_file(package_dir / "manifest.json")
    readiness = evaluate_data_readiness(manifest_out, manifest_sha)
    print(
        json.dumps(
            {
                "package_uri": uri,
                "package_path": str(package_dir),
                "manifest_sha256": manifest_sha,
                "identity": readiness["identity"],
                "quality_gate": gate["overall"],
                "readiness": {
                    "ready": readiness["ready"],
                    "blocked_reasons": readiness["blocked_reasons"],
                },
                "events": {c: len(evs) for c, evs in events_by_code.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not readiness["ready"]:
        sys.exit(2)


def _registry_manifest_sha(package_dir: Path) -> str | None:
    try:
        return base.sha256_file(Path(package_dir) / "manifest.json")
    except OSError:
        return None


def _baseline_symbol(baseline_entry: dict, code: str) -> dict | None:
    try:
        m = json.loads(
            (Path(baseline_entry["absolute_path"]) / "manifest.json").read_text()
        )
        for s in m.get("symbols", []):
            if s.get("code") == code:
                return s
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    return None


def _months_between(iso_a: str, iso_b: str) -> int:
    ya, ma, _ = (int(x) for x in iso_a.split("-"))
    yb, mb, _ = (int(x) for x in iso_b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def _empty_daily(code: str, day8: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": pd.Series([], dtype=str),
            "trade_date": pd.Series([], dtype=str),
            "open": pd.Series([], dtype="float64"),
            "high": pd.Series([], dtype="float64"),
            "low": pd.Series([], dtype="float64"),
            "close": pd.Series([], dtype="float64"),
            "pre_close": pd.Series([], dtype="float64"),
            "vol_shares": pd.Series([], dtype="float64"),
            "amount_cny": pd.Series([], dtype="float64"),
        }
    )


def _readme(version, decision8, release_id, args, gate, prev8) -> str:
    return (
        "\n".join(
            [
                f"# R01 ETF daily incremental input package `{version}` (schema v3.1)",
                "",
                f"- decision_date {base._iso(decision8)}; data_as_of {base._iso(decision8)}; source release `{release_id}`.",
                f"- Baseline history: `{args.baseline}` (frozen v2 fixed package; never modified by daily publishing).",
                "- Runner binds the decision day to the identity quintuple {decision_date, package_id, package_version,",
                "  source_release_id, manifest_sha256} (manifest_sha256 computed over manifest.json by the consumer).",
                "- Quality gate result is embedded in `manifest.json` (`quality_gate`); consume",
                "  `evaluate_data_readiness(manifest, manifest_sha256)` from this module (H2.1-D2). ready=false means the",
                "  affected decision must be explicitly blocked; executing with older data as same-day is forbidden.",
                "- Layout mirrors the v2 package (daily/factors/events/etf_limit/calendar) restricted to the decision day;",
                "  events use the schema v3 typed structure incl. dividend record/pay dates (never defaulted to ex_date).",
                f"- Previous trade day (verification anchor): {base._iso(prev8) if prev8 else 'n/a'}.",
                f"- gate overall: {gate['overall']}"
                + (
                    f"; blocked: {gate['blocked_reasons']}"
                    if gate["blocked_reasons"]
                    else ""
                ),
                "",
                "Generated by `scripts/publish_r01_daily_inputs.py`.",
            ]
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=base.DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--release-id",
        default=None,
        help="frozen release id (default: archive CURRENT pointer, read-only)",
    )
    parser.add_argument(
        "--decision-date",
        default=None,
        help="YYYYMMDD (default: latest pool trade date in release)",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--baseline", default="node://mac/r01-etf-daily/v2-fcbabbb7")
    parser.add_argument("--package-version", default=None)
    parser.add_argument(
        "--revision",
        default=None,
        help="e.g. r2: publish a revision (revised=true + supersedes)",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    publish(args)


if __name__ == "__main__":
    main()
