#!/usr/bin/env python3
"""Derive the R01 ETF fixed daily input package from one frozen Tushare release.

Reads only the frozen release named by ``--release-id`` (default: the release
frozen by R01P0-W1C2 scope.json). Every source parquet file of the five package
datasets is size+SHA256 verified against the release manifest before it is
parsed; ``fund_nav`` (verification-only cross-check source) is lazily verified
for the files it actually contributes. The package layout, units and typed
corporate-action events follow ``contracts/etf-input-package.schema.json`` (v2):

    <output-root>/<version>/
      manifest.json            # validates against etf-input-package.schema.json
      SHA256SUMS.txt           # sha256 of every other file in the package
      README.md                # layout, digest rules, warmup and usage notes
      derivation-report.json   # evidence: coverage, events, nav cross-checks
      calendar.parquet         # SSE trade calendar
      daily/<code>.parquet     # unadjusted OHLCV, vol in shares, amount in CNY
      factors/<code>.parquet   # hfq adj_factor per trade date
      dividends/<code>.parquet # raw fund_div events (when the code has any)
      events/<code>.parquet    # typed corporate-action events (when any)
      etf_limit/<code>.parquet # exchange limit prices (2019-06-26 onwards)

The absolute path of the package is registered in the node-private registry
(``~/Library/Application Support/QuantMind/r01/package-registry.json``); the
package itself is referenced by ``node://mac/r01-etf-daily/<version>``.

No supplier requests are made; missing rows are never fabricated.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_ARCHIVE_ROOT = Path.home() / "Library/Application Support/QuantMind/tushare"
DEFAULT_OUTPUT_ROOT = (
    Path.home() / "Library/Application Support/QuantMind/r01/etf-daily"
)
DEFAULT_REGISTRY = (
    Path.home() / "Library/Application Support/QuantMind/r01/package-registry.json"
)
DEFAULT_SAMPLES_ROOT = (
    Path.home() / "Library/Application Support/QuantMind/r01/etf-daily-samples"
)
DEFAULT_RELEASE_ID = (
    "data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab"
)

# Verification pool frozen by artifacts/p01c/scope.json rev2.1 (schema_version=2).
POOL = [
    ("510300.SH", "equity_broad", "primary"),
    ("510500.SH", "equity_broad", "primary"),
    ("159915.SZ", "equity_broad", "primary"),
    ("588000.SH", "equity_broad", "backup"),
    ("518880.SH", "gold", "primary"),
    ("159934.SZ", "gold", "regression-only"),
    ("511010.SH", "treasury", "primary"),
    ("511260.SH", "treasury", "primary"),
    ("511090.SH", "treasury", "backup"),
]
SUFFIX_TO_PREFIX = {
    code: code[7:9] + code[:6] for code, _, _ in POOL
}  # 510300.SH -> SH510300
PREFIX_SET = set(SUFFIX_TO_PREFIX.values())
SUFFIX_SET = set(SUFFIX_TO_PREFIX)

SOURCE_APIS = ("fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit")
NAV_API = "fund_nav"  # verification-only cross-check source, not a package dataset

SCAN_COLUMNS = {
    "fund_daily": [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "_fetched_at",
        "_observation",
    ],
    "fund_adj": ["ts_code", "trade_date", "adj_factor", "_fetched_at", "_observation"],
    "fund_div": None,  # all columns
    "trade_cal": None,
    "etf_limit": [
        "ts_code",
        "trade_date",
        "pre_close",
        "up_limit",
        "down_limit",
        "asset_type",
        "_fetched_at",
        "_observation",
    ],
    "fund_nav": ["ts_code", "nav_date", "unit_nav", "_fetched_at", "_observation"],
}

CONTINUITY_TOL = 0.005  # 0.5% relative tolerance for pre_close x factor continuity
DIV_MATCH_TOL = 0.0015  # relative tolerance for dividend-implied factor jump
WARMUP_MONTHS = 10  # 10-month MA rule from the study plan


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _instant(value):
    if not isinstance(value, str):
        return ""
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
        )
    except ValueError:
        return value


def scan_one(args):
    """Verify one release file against the manifest and extract pool rows."""
    root, rel_path, api, entry = args
    path = Path(root) / rel_path
    if path.is_symlink() or not path.is_file():
        return {"api": api, "path": rel_path, "error": "missing-or-symlink", "rows": []}
    try:
        table = pq.read_table(path, columns=SCAN_COLUMNS[api])
    except Exception as exc:
        return {"api": api, "path": rel_path, "error": f"read:{exc}", "rows": []}
    df = table.to_pandas()
    if api in ("fund_daily", "fund_adj", "fund_div", NAV_API):
        mask = df["ts_code"].isin(PREFIX_SET)
    elif api == "etf_limit":
        mask = df["ts_code"].isin({"FUND:" + s for s in SUFFIX_SET})
    else:
        mask = pd.Series(True, index=df.index)
    sub = df[mask]
    if api == NAV_API and sub.empty:
        return {"api": api, "path": rel_path, "error": None, "rows": []}
    if path.stat().st_size != entry.get("bytes") or sha256_file(path) != entry.get(
        "sha256"
    ):
        return {"api": api, "path": rel_path, "error": "hash-mismatch", "rows": []}
    return {"api": api, "path": rel_path, "error": None, "rows": sub.to_dict("records")}


def collect_api(root: Path, manifest: dict, api: str, workers: int):
    """Scan+verify all files of one api; return (rows, digest, files)."""
    entries = [d for d in manifest["datasets"] if d.get("api_name") == api]
    if not entries:
        raise SystemExit(f"Release manifest has no {api} datasets")
    jobs = [(str(root), e["path"], api, e) for e in entries]
    rows, errors = [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(scan_one, jobs, chunksize=16):
            if result["error"]:
                errors.append(result)
            rows.extend(result["rows"])
    if errors:
        raise SystemExit(
            f"Fixed-release file verification failed for {api}: {errors[:3]} (n={len(errors)})"
        )
    lines = "".join(
        f"{e['path']} {e['sha256']}\n" for e in sorted(entries, key=lambda e: e["path"])
    )
    digest = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    return rows, digest, entries


def latest_version(df: pd.DataFrame, key_cols):
    """Keep the latest row per key using the store's observation ordering.

    Mirrors tushare_store semantics: order by (_fetched_at, _observation), keep
    the last row per logical key. Returns (deduped_df, dropped_version_count).
    """
    if df.empty:
        return df, 0
    df = df.copy()
    df["_sort"] = df["_fetched_at"].map(_instant) + "|" + df["_observation"].astype(str)
    df = df.sort_values(key_cols + ["_sort"], kind="mergesort")
    dropped = int(df.duplicated(subset=key_cols, keep="last").sum())
    df = df[~df.duplicated(subset=key_cols, keep="last")].drop(columns=["_sort"])
    return df, dropped


def _iso(day: str) -> str:
    return f"{day[:4]}-{day[4:6]}-{day[6:8]}"


def _event(day, etype, cash, mult, basis, f_prev, f_new, ref, passed, method, detail):
    derived = {"adj_factor_prev": float(f_prev), "adj_factor_new": float(f_new)}
    if ref:
        derived["fund_div_ref"] = ref
    return {
        "event_date": _iso(day),
        "event_type": etype,
        "cash_per_share": cash,
        "qty_multiplier": mult,
        "basis_note": basis,
        "derived_from": derived,
        "verification": {"passed": bool(passed), "method": method, "detail": detail},
    }


def _nav_check(nav_days, day, prev_day, pre, prev_close):
    """Informational fund_nav cross-check for a share adjustment.

    The fund's NAV step can be booked one or more trade days before the price
    adjustment (e.g. 159934 folded in NAV on 2025-09-19 while the exchange
    price/factor stepped on 2025-09-22), so we look for the largest single-day
    NAV step within [prev_day - 10 calendar days, event_day] and compare it to
    the implied price ratio 1/qty_multiplier (= pre_close/prev_close).
    """
    if not nav_days or not pre or not prev_close or prev_close <= 0 or pre <= 0:
        return ""
    window = [d for d in nav_days if _shift(day, -14) <= d <= day]
    window.sort()
    best_step, best_ratio = None, None
    for a, b in zip(window, window[1:], strict=False):
        va, vb = nav_days[a], nav_days[b]
        if va and vb and va > 0:
            ratio = vb / va
            if best_ratio is None or abs(ratio - 1.0) > abs(best_ratio - 1.0):
                best_step, best_ratio = (a, b), ratio
    if best_step is None:
        return ""
    price_ratio = pre / prev_close
    residual = abs(best_ratio / price_ratio - 1.0)
    return (
        f"fund_nav cross-check: largest nav step {best_step[0]}->{best_step[1]} ratio={best_ratio:.6f} vs "
        f"price ratio={price_ratio:.6f}; residual={residual:.4%}"
    )


def _shift(day: str, days: int) -> str:
    from datetime import datetime, timedelta

    base = datetime.strptime(day, "%Y%m%d") + timedelta(days=days)
    return base.strftime("%Y%m%d")


def _signal_ready_month(dates):
    """First month-end that has WARMUP_MONTHS prior months of month-end closes."""
    month_last = {}
    for day in dates:
        month_last[day[:6]] = day
    months = sorted(month_last)
    if len(months) <= WARMUP_MONTHS:
        return None
    return month_last[months[WARMUP_MONTHS]]


def _write_events_parquet(path, code, events):
    derived = pa.struct(
        [
            pa.field("adj_factor_prev", pa.float64()),
            pa.field("adj_factor_new", pa.float64()),
            pa.field("fund_div_ref", pa.string()),
        ]
    )
    verification = pa.struct(
        [
            pa.field("passed", pa.bool_()),
            pa.field("method", pa.string()),
            pa.field("detail", pa.string()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("symbol", pa.string()),
            pa.field("event_date", pa.string()),
            pa.field("event_type", pa.string()),
            pa.field("cash_per_share", pa.float64()),
            pa.field("qty_multiplier", pa.float64()),
            pa.field("basis_note", pa.string()),
            pa.field("derived_from", derived),
            pa.field("verification", verification),
        ]
    )
    rows = [
        {
            "symbol": code,
            **{
                k: e[k]
                for k in (
                    "event_date",
                    "event_type",
                    "cash_per_share",
                    "qty_multiplier",
                    "basis_note",
                )
            },
            "derived_from": e["derived_from"],
            "verification": e["verification"],
        }
        for e in events
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def _write_readme(package_dir: Path, version: str, args, warmup_note: str):
    lines = [
        f"# R01 ETF fixed daily input package `{version}`",
        "",
        f"- Source: Mac Tushare archive release `{args.release_id}` (frozen; every package-dataset file SHA256-verified).",
        "- Reference: `node://mac/r01-etf-daily/"
        + version
        + "`; the absolute path of this package is",
        "  registered in the node-private registry `~/Library/Application Support/QuantMind/r01/package-registry.json`.",
        "- Layout: `manifest.json`, `SHA256SUMS.txt`, `calendar.parquet`, `daily/`, `factors/`, `dividends/`,",
        "  `events/`, `etf_limit/`, `derivation-report.json` (evidence).",
        "- Units: `vol_shares = fund_daily.vol * 100` (lots -> shares), `amount_cny = fund_daily.amount * 1000` (thousand CNY -> CNY).",
        "- Factors: `adjusted_close = close_unadjusted * adj_factor` (hfq). Factor jumps are typed into",
        "  `events/` as `cash_dividend`/`share_adjustment`; qty_multiplier = adj_factor_new/adj_factor_prev.",
        "- Dates: `trade_date` strings `YYYYMMDD`; `event_date` strings `YYYY-MM-DD`.",
        warmup_note,
        "- Missing rows are never fabricated; see `manifest.json` `known_gaps`.",
        "- Samples live outside this package in `etf-daily-samples/"
        + version
        + "/` (clearly marked, not research input).",
        "",
        "Generated by `scripts/prepare_r01_etf_inputs.py` in the QuantMind repo.",
    ]
    (package_dir / "README.md").write_text("\n".join(lines) + "\n")


def _write_sums(package_dir: Path):
    lines = []
    for path in sorted(package_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256_file(path)}  {path.relative_to(package_dir)}")
    (package_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")


SSE_511090_20240424_ANNOUNCEMENT = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2024-04-19/511090_20240419_UBA9.pdf"
# Authoritative case from the independent acceptance report AC-01:
# 511090 registration 2024-04-23 / ex-div 2024-04-24 / pay 2024-04-29, 1.5 CNY/share.
AUTHORITATIVE_511090 = {
    "code": "511090.SH",
    "event_date": "2024-04-24",
    "record_date": "2024-04-23",
    "pay_date": "2024-04-29",
    "cash_per_share": 1.5,
}


def _verify_package_sums(package_dir: Path):
    """Return {rel_path: sha256} after recomputing SHA256SUMS.txt entries."""
    sums = {}
    for line in (package_dir / "SHA256SUMS.txt").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        path = package_dir / rel
        if not path.is_file() or sha256_file(path) != digest:
            raise SystemExit(f"Frozen package file missing/hash mismatch: {rel}")
        sums[rel] = digest
    on_disk = {
        str(p.relative_to(package_dir))
        for p in package_dir.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS.txt"
    }
    if on_disk != set(sums):
        raise SystemExit("Frozen package SHA256SUMS does not cover all files")
    return sums


def _write_events_parquet_v3(path, code, events):
    """Schema v3 events parquet: cash rows carry the dividend date fields.

    Rows are exported to JSON row-type-aware: keys whose value is null AND that
    are forbidden for the row's event_type (the cash-only date fields on a
    share_adjustment row) are dropped; keys required for the row's event_type
    are kept even when null (unknown dates).
    """
    derived = pa.struct(
        [
            pa.field("adj_factor_prev", pa.float64()),
            pa.field("adj_factor_new", pa.float64()),
            pa.field("fund_div_ref", pa.string()),
        ]
    )
    verification = pa.struct(
        [
            pa.field("passed", pa.bool_()),
            pa.field("method", pa.string()),
            pa.field("detail", pa.string()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("symbol", pa.string()),
            pa.field("event_date", pa.string()),
            pa.field("event_type", pa.string()),
            pa.field("cash_per_share", pa.float64()),
            pa.field("qty_multiplier", pa.float64()),
            pa.field("event_id", pa.string()),
            pa.field("record_date", pa.string()),
            pa.field("record_date_status", pa.string()),
            pa.field("pay_date", pa.string()),
            pa.field("pay_date_status", pa.string()),
            pa.field("entitlement_basis", pa.string()),
            pa.field("basis_note", pa.string()),
            pa.field("derived_from", derived),
            pa.field("verification", verification),
        ]
    )
    rows = []
    for e in events:
        row = {
            "symbol": code,
            **{
                k: e[k]
                for k in (
                    "event_date",
                    "event_type",
                    "cash_per_share",
                    "qty_multiplier",
                    "basis_note",
                )
            },
            **{
                k: e.get(k)
                for k in (
                    "event_id",
                    "record_date",
                    "record_date_status",
                    "pay_date",
                    "pay_date_status",
                    "entitlement_basis",
                )
            },
            "derived_from": e["derived_from"],
            "verification": e["verification"],
        }
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def upgrade_dividends_v3(args):
    """Derive package v2 (schema v3): v1 content frozen, dividend events upgraded."""
    root = args.root.expanduser().resolve()
    release_hash = args.release_id.removeprefix("data-")
    manifest_path = root / "releases" / args.release_id / "manifest.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != release_hash:
        raise SystemExit("Release manifest checksum mismatch")
    rel_manifest = json.loads(raw)

    v1_dir = args.from_package.expanduser().resolve()
    v1_manifest = json.loads((v1_dir / "manifest.json").read_text())
    if v1_manifest.get("schema_version") != 2:
        raise SystemExit("--from-package must be a schema_version=2 (v1) package")
    if v1_manifest["source_release_id"] != args.release_id:
        raise SystemExit("v1 package source release differs from --release-id")
    v1_sums = _verify_package_sums(v1_dir)
    v1_manifest_sha = sha256_file(v1_dir / "manifest.json")
    print(
        f"[v1] frozen package verified ({len(v1_sums)} files, manifest {v1_manifest_sha[:12]}…)",
        flush=True,
    )

    # ---- fund_div record/pay dates from the same frozen release
    rows, _, entries = collect_api(root, rel_manifest, "fund_div", args.workers)
    div = pd.DataFrame(rows)
    div, _ = latest_version(div, ["ts_code", "ex_date", "base_year", "div_cash"])
    div_dates = {}
    prefix_to_suffix = {v: k for k, v in SUFFIX_TO_PREFIX.items()}
    for row in div.itertuples(index=False):
        code = prefix_to_suffix.get(row.ts_code)
        if code is None:
            continue
        div_dates.setdefault(code, {})[str(row.ex_date)] = {
            "record_date": None if pd.isna(row.record_date) else str(row.record_date),
            "pay_date": None if pd.isna(row.pay_date) else str(row.pay_date),
            "base_year": None if pd.isna(row.base_year) else str(row.base_year),
            "div_cash": None if pd.isna(row.div_cash) else float(row.div_cash),
        }
    print(
        f"[fund_div] {len(entries)} files verified, codes with events: {sorted(div_dates)}",
        flush=True,
    )

    version = args.package_version or ("v2-" + release_hash[:8])
    package_dir = args.output_root.expanduser() / version
    if package_dir.exists():
        if not args.force:
            raise SystemExit(
                f"Package directory already exists: {package_dir} (use --force)"
            )
        shutil.rmtree(package_dir)
    (package_dir / "events").mkdir(parents=True)

    # ---- copy every non-events file byte-identical from v1
    copied = {}
    for rel in sorted(v1_sums):
        if rel.startswith("events/") or rel in (
            "manifest.json",
            "README.md",
            "derivation-report.json",
            "SHA256SUMS.txt",
        ):
            continue
        target = package_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(v1_dir / rel, target)
        copied[rel] = sha256_file(target)
    diff_mismatch = [rel for rel, digest in copied.items() if digest != v1_sums[rel]]
    if diff_mismatch:
        raise SystemExit(f"Copied files differ from v1: {diff_mismatch}")

    # ---- upgrade dividend events
    blocked_stats = {"codes": {}, "total_blocked": 0, "total_cash": 0}
    coverage = {}
    authoritative_ok = False
    for code, _, _ in POOL:
        v1_ev = v1_dir / "events" / f"{code}.parquet"
        if not v1_ev.exists():
            continue
        events = pq.read_table(v1_ev).to_pylist()
        upgraded = []
        cov_rows = []
        for e in events:
            e = {k: v for k, v in e.items() if k != "symbol"}
            if e["event_type"] != "cash_dividend":
                upgraded.append(e)
                continue
            day8 = e["event_date"].replace("-", "")
            info = div_dates.get(code, {}).get(day8)
            if info is None:
                raise SystemExit(
                    f"fund_div raw event missing for {code} {day8}; cannot upgrade"
                )
            prefix = SUFFIX_TO_PREFIX[code]
            year = info["base_year"] or f"{info['div_cash']:g}"
            rec = _iso(info["record_date"]) if info["record_date"] else None
            pay = _iso(info["pay_date"]) if info["pay_date"] else None
            rec_status = "known" if rec else "unknown_blocked"
            pay_status = "known" if pay else "unknown_blocked"
            e2 = dict(e)
            e2["event_id"] = f"fund_div:{prefix}:{day8}:{year}"
            e2["record_date"] = rec
            e2["record_date_status"] = rec_status
            e2["pay_date"] = pay
            e2["pay_date_status"] = pay_status
            e2["entitlement_basis"] = "record_date_close_holdings"
            blocked = rec_status == "unknown_blocked" or pay_status == "unknown_blocked"
            if blocked:
                e2["verification"] = {
                    "passed": False,
                    "method": "unresolved_gap",
                    "detail": (
                        f"dividend dates blocked (record_date={'known' if rec else 'unknown'}, "
                        f"pay_date={'known' if pay else 'unknown'}); ex_date anchoring kept; "
                        f"factor evidence retained: {e['verification'].get('detail', '')}"
                    ),
                }
                blocked_stats["total_blocked"] += 1
            elif (
                code == AUTHORITATIVE_511090["code"]
                and e["event_date"] == AUTHORITATIVE_511090["event_date"]
            ):
                ref = e2["derived_from"]
                e2["derived_from"] = {
                    **ref,
                    "fund_div_ref": f"{ref.get('fund_div_ref', '')}; announcement: {SSE_511090_20240424_ANNOUNCEMENT}",
                }
                e2["verification"] = {
                    "passed": True,
                    "method": "record_date_evidence",
                    "detail": (
                        f"authoritative announcement match: record_date={rec} ex_date={day8} "
                        f"pay_date={pay} div={info['div_cash']:g} CNY/share "
                        f"(SSE disclosure {SSE_511090_20240424_ANNOUNCEMENT}); "
                        f"factor evidence: {e['verification'].get('detail', '')}"
                    ),
                }
                if (
                    rec == AUTHORITATIVE_511090["record_date"]
                    and pay == AUTHORITATIVE_511090["pay_date"]
                    and abs(
                        e2["cash_per_share"] - AUTHORITATIVE_511090["cash_per_share"]
                    )
                    < 1e-9
                ):
                    authoritative_ok = True
            else:
                e2["verification"] = {
                    **e["verification"],
                    "detail": (
                        f"{e['verification'].get('detail', '')}; "
                        f"record_date={rec} pay_date={pay} (fund_div raw fields)"
                    ),
                }
            upgraded.append(e2)
            cov_rows.append(
                {
                    "event_date": e2["event_date"],
                    "record_date": rec,
                    "record_date_status": rec_status,
                    "pay_date": pay,
                    "pay_date_status": pay_status,
                    "cash_per_share": e2["cash_per_share"],
                    "blocked": blocked,
                    "event_id": e2["event_id"],
                }
            )
        blocked_stats["codes"][code] = {
            "cash_events": sum(
                1 for x in upgraded if x["event_type"] == "cash_dividend"
            ),
            "blocked": sum(1 for x in cov_rows if x["blocked"]),
        }
        blocked_stats["total_cash"] += blocked_stats["codes"][code]["cash_events"]
        coverage[code] = cov_rows
        _write_events_parquet_v3(
            package_dir / "events" / f"{code}.parquet", code, upgraded
        )
        print(
            f"[v2-events] {code}: {len(upgraded)} events "
            f"(cash={blocked_stats['codes'][code]['cash_events']}, blocked={blocked_stats['codes'][code]['blocked']})",
            flush=True,
        )
    if not authoritative_ok:
        raise SystemExit(
            "Authoritative 511090 2024-04-24 case did not match the archive (record/pay/cash)"
        )

    manifest_out = dict(v1_manifest)
    manifest_out.update(
        {
            "schema_version": 3,
            "package_version": version,
            "package_uri": f"node://mac/r01-etf-daily/{version}",
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
    manifest_out["factor_convention"] = dict(v1_manifest["factor_convention"])
    manifest_out["factor_convention"]["verified_cases"] = list(
        v1_manifest["factor_convention"]["verified_cases"]
    ) + [
        (
            f"{AUTHORITATIVE_511090['code']} {AUTHORITATIVE_511090['event_date']} cash_dividend record_date_evidence: "
            f"record {AUTHORITATIVE_511090['record_date']} / ex {AUTHORITATIVE_511090['event_date']} / "
            f"pay {AUTHORITATIVE_511090['pay_date']} / {AUTHORITATIVE_511090['cash_per_share']} CNY per share "
            f"matches the SSE fund announcement ({SSE_511090_20240424_ANNOUNCEMENT}); blocked dividend-date events: 0"
        )
    ]
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n"
    )

    report = {
        "kind": "v2-upgrade-from-v1",
        "v1_package": str(v1_dir),
        "v1_package_uri": v1_manifest["package_uri"],
        "v1_manifest_sha256": v1_manifest_sha,
        "source_release_id": args.release_id,
        "package_version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "diff_v1_to_v2": (
            "Only dividend (cash_dividend) event fields changed: added event_id, record_date, "
            "record_date_status, pay_date, pay_date_status, entitlement_basis (schema v3). "
            "daily/, factors/, dividends/, etf_limit/, calendar.parquet copied byte-identical "
            "(hash-equal to v1 SHA256SUMS); share_adjustment events unchanged; v1 package untouched."
        ),
        "files_copied_byte_identical": sorted(copied),
        "share_adjustment_events_unchanged": True,
        "dividend_date_coverage": coverage,
        "blocked_events": blocked_stats,
        "authoritative_511090_case": {
            **AUTHORITATIVE_511090,
            "matched": authoritative_ok,
            "announcement": SSE_511090_20240424_ANNOUNCEMENT,
        },
    }
    (package_dir / "derivation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )

    readme = [
        f"# R01 ETF fixed daily input package `{version}` (schema v3)",
        "",
        "- v2 upgrade of the frozen v1 package (AC-01 fix): identical daily/factors/dividends/etf_limit/calendar",
        "  content; only cash_dividend events gained `event_id`, `record_date`, `record_date_status`, `pay_date`,",
        "  `pay_date_status`, `entitlement_basis` (contract `etf-input-package.schema.json` v3).",
        "- Unknown dates are `null` with `*_status=unknown_blocked` and `verification.method=unresolved_gap`,",
        "  `passed=false`; ex_date is NEVER defaulted into record_date/pay_date.",
        "- Entitlement basis (normative): `record_date_close_holdings` — holdings registered at the record-date",
        "  close receive the dividend; cash becomes available on pay_date.",
        "- Row-to-JSON export rule for `events/*.parquet`: drop null-valued keys that are forbidden for the",
        "  row's event_type (the dividend date fields on share_adjustment rows); keep required keys even when null.",
        f"- v1 lineage: {v1_manifest['package_uri']} (manifest sha256 {v1_manifest_sha}); source release {args.release_id}.",
        "- Units/factors/warmup conventions unchanged from v1 (see v1 README and docs/r01-p0/).",
        "",
        "Generated by `scripts/prepare_r01_etf_inputs.py --from-package <v1 dir>`.",
    ]
    (package_dir / "README.md").write_text("\n".join(readme) + "\n")
    _write_sums(package_dir)

    # ---- registry
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    registry = {"packages": {}}
    if args.registry.exists():
        try:
            registry = json.loads(args.registry.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit("Node registry is corrupt") from exc
    uri = manifest_out["package_uri"]
    existing = registry["packages"].get(uri)
    if (
        existing
        and existing.get("absolute_path") != str(package_dir)
        and not args.force
    ):
        raise SystemExit(f"Registry already maps {uri} to {existing['absolute_path']}")
    registry["packages"][uri] = {
        "absolute_path": str(package_dir),
        "package_id": manifest_out["package_id"],
        "package_version": version,
        "source_release_id": args.release_id,
        "created_at": manifest_out["generated_at"],
        "upgrade_of": v1_manifest["package_uri"],
    }
    fd, tmp = tempfile.mkstemp(dir=args.registry.parent)
    with os.fdopen(fd, "w") as handle:
        json.dump(registry, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, args.registry)

    print(
        json.dumps(
            {
                "package_uri": uri,
                "package_path": str(package_dir),
                "manifest_sha256": sha256_file(package_dir / "manifest.json"),
                "schema_version": 3,
                "cash_events": blocked_stats["total_cash"],
                "blocked_events": blocked_stats["total_blocked"],
                "authoritative_511090_matched": authoritative_ok,
                "v1_manifest_sha256_unchanged": sha256_file(v1_dir / "manifest.json")
                == v1_manifest_sha,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--samples-root", type=Path, default=DEFAULT_SAMPLES_ROOT)
    parser.add_argument("--package-version", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--from-package",
        type=Path,
        default=None,
        help="upgrade mode: derive schema-v3 package v2 from this frozen v1 package",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing package directory/registry entry",
    )
    args = parser.parse_args()

    if args.from_package:
        upgrade_dividends_v3(args)
        return

    root = args.root.expanduser().resolve()
    release_hash = args.release_id.removeprefix("data-")
    if not re.fullmatch(r"[0-9a-f]{64}", release_hash):
        raise SystemExit("Invalid release id")
    manifest_path = root / "releases" / args.release_id / "manifest.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != release_hash:
        raise SystemExit("Release manifest checksum mismatch")
    manifest = json.loads(raw)
    print(
        f"[release] {args.release_id} verified ({len(manifest['datasets'])} dataset files)",
        flush=True,
    )

    version = args.package_version or ("v1-" + release_hash[:8])
    package_dir = args.output_root.expanduser() / version
    if package_dir.exists():
        if not args.force:
            raise SystemExit(
                f"Package directory already exists: {package_dir} (use --force)"
            )
        shutil.rmtree(package_dir)
    for sub in ("daily", "factors", "dividends", "events", "etf_limit"):
        (package_dir / sub).mkdir(parents=True, exist_ok=True)

    report = {
        "source_release_id": args.release_id,
        "package_version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "apis": {},
        "symbols": {},
    }

    # ------------------------------------------------------------------ scan
    rows_by_api = {}
    for api in (*SOURCE_APIS, NAV_API):
        rows, digest, entries = collect_api(root, manifest, api, args.workers)
        rows_by_api[api] = pd.DataFrame(rows)
        report["apis"][api] = {
            "files": len(entries),
            "rows_pool": len(rows),
            "file_list_sha256": digest,
        }
        print(f"[scan] {api}: {len(entries)} files, {len(rows)} pool rows", flush=True)

    # ------------------------------------------------------------- calendar
    cal = rows_by_api["trade_cal"]
    cal, cal_dropped = latest_version(cal, ["exchange", "cal_date"])
    sse = cal[cal["exchange"] == "SSE"].sort_values("cal_date")
    sse_open = [str(d) for d in sse[sse["is_open"] == 1]["cal_date"]]
    open_set = set(sse_open)
    if len(sse_open) != len(open_set):
        raise SystemExit("Duplicate SSE open dates after latest-version selection")
    pq.write_table(
        pa.Table.from_pandas(
            sse[["exchange", "cal_date", "is_open", "pretrade_date"]].reset_index(
                drop=True
            )
        ),
        package_dir / "calendar.parquet",
    )
    report["calendar"] = {
        "sse_open_days": len(sse_open),
        "range": [sse_open[0], sse_open[-1]],
        "dropped_versions": cal_dropped,
    }

    # --------------------------------------------------- per-symbol derivation
    daily, daily_dropped = latest_version(
        rows_by_api["fund_daily"], ["ts_code", "trade_date"]
    )
    adj, adj_dropped = latest_version(
        rows_by_api["fund_adj"], ["ts_code", "trade_date"]
    )
    div, div_dropped = latest_version(
        rows_by_api["fund_div"], ["ts_code", "ex_date", "base_year", "div_cash"]
    )
    nav, nav_dropped = latest_version(rows_by_api[NAV_API], ["ts_code", "nav_date"])
    limit, limit_dropped = latest_version(
        rows_by_api["etf_limit"], ["ts_code", "trade_date"]
    )
    report["apis"]["fund_daily"]["dropped_versions"] = daily_dropped
    report["apis"]["fund_adj"]["dropped_versions"] = adj_dropped
    report["apis"]["fund_div"]["dropped_versions"] = div_dropped
    report["apis"][NAV_API]["dropped_versions"] = nav_dropped
    report["apis"]["etf_limit"]["dropped_versions"] = limit_dropped

    nav_lookup = {}
    if len(nav):
        prefix_to_suffix = {v: k for k, v in SUFFIX_TO_PREFIX.items()}
        for row in nav.itertuples(index=False):
            code = prefix_to_suffix.get(row.ts_code)
            if code is not None and row.unit_nav == row.unit_nav:  # skip NaN
                nav_lookup.setdefault(code, {})[str(row.nav_date)] = float(row.unit_nav)
    nav_last = max((max(v) for v in nav_lookup.values()), default=None)

    symbols_meta = []
    events_manifest = {}
    verified_cases = []
    pre_close_discontinuities = {}
    limit_first_dates = []

    for code, klass, role in POOL:
        prefix = SUFFIX_TO_PREFIX[code]
        d = (
            daily[daily["ts_code"] == prefix]
            .sort_values("trade_date")
            .reset_index(drop=True)
        )
        if d.empty:
            raise SystemExit(f"No fund_daily rows for {code}")
        f = (
            adj[adj["ts_code"] == prefix]
            .sort_values("trade_date")
            .reset_index(drop=True)
        )
        factor_by_date = {
            str(k): float(v)
            for k, v in zip(f["trade_date"], f["adj_factor"], strict=True)
        }

        out = pd.DataFrame(
            {
                "ts_code": code,
                "trade_date": d["trade_date"].astype(str),
                "open": d["open"].astype(float),
                "high": d["high"].astype(float),
                "low": d["low"].astype(float),
                "close": d["close"].astype(float),
                "pre_close": d["pre_close"].astype(float),
                "vol_shares": (d["vol"].astype(float) * 100.0).round(2),
                "amount_cny": (d["amount"].astype(float) * 1000.0).round(3),
            }
        )
        pq.write_table(
            pa.Table.from_pandas(out), package_dir / "daily" / f"{code}.parquet"
        )

        dates = list(out["trade_date"])
        date_set = set(dates)
        data_start, data_end = dates[0], dates[-1]
        expected = [day for day in sse_open if data_start <= day <= data_end]
        missing = [day for day in expected if day not in date_set]
        dup_dates = int(out["trade_date"].duplicated().sum())

        fq = pd.DataFrame(
            {
                "ts_code": code,
                "trade_date": sorted(factor_by_date),
                "adj_factor": [factor_by_date[k] for k in sorted(factor_by_date)],
            }
        )
        pq.write_table(
            pa.Table.from_pandas(fq), package_dir / "factors" / f"{code}.parquet"
        )
        missing_factor_days = [day for day in dates if day not in factor_by_date]

        # ---------------- dividends (raw fund_div rows)
        code_div = div[div["ts_code"] == prefix] if len(div) else pd.DataFrame()
        div_events = {}
        if len(code_div):
            code_div = code_div.sort_values(["ex_date", "base_year"])
            keep_cols = [
                c
                for c in (
                    "ts_code",
                    "ann_date",
                    "base_date",
                    "base_unit",
                    "base_year",
                    "div_cash",
                    "div_proc",
                    "ear_amount",
                    "ear_distr",
                    "earpay_date",
                    "ex_date",
                    "imp_anndate",
                    "net_ex_date",
                    "pay_date",
                    "record_date",
                )
                if c in code_div.columns
            ]
            out_div = code_div[keep_cols].copy()
            out_div["ts_code"] = code
            pq.write_table(
                pa.Table.from_pandas(out_div.reset_index(drop=True)),
                package_dir / "dividends" / f"{code}.parquet",
            )
            for row in out_div.itertuples(index=False):
                div_events.setdefault(str(row.ex_date), []).append(float(row.div_cash))

        # ---------------- typed corporate-action events from factor jumps
        close_by_date = dict(zip(out["trade_date"], out["close"], strict=True))
        pre_by_date = dict(zip(out["trade_date"], out["pre_close"], strict=True))
        events = []
        discontinuities = []
        event_days = set()
        prev_date = None
        for i, day in enumerate(dates):
            if i > 0 and prev_date is not None:
                f_prev = factor_by_date.get(prev_date)
                f_new = factor_by_date.get(day)
                prev_close = close_by_date.get(prev_date)
                pre = pre_by_date.get(day)
                # pre_close vs prev close (unexplained discontinuity detection)
                if prev_close and pre:
                    ratio_raw = pre / prev_close
                else:
                    ratio_raw = None
                if f_prev is not None and f_new is not None and f_prev != f_new:
                    event_days.add(day)
                    cash = sum(div_events.get(day, []))
                    basis = ""
                    if cash > 0 and pre is not None and pre > cash:
                        implied = f_prev * pre / (pre - cash)
                        residual = abs(f_new - implied) / max(implied, 1e-12)
                        if residual <= DIV_MATCH_TOL:
                            events.append(
                                _event(
                                    day,
                                    "cash_dividend",
                                    round(cash, 6),
                                    1.0,
                                    basis,
                                    f_prev,
                                    f_new,
                                    f"fund_div:{prefix}:{day}",
                                    True,
                                    "fund_div_match",
                                    f"div_cash={cash:.6g}/share; implied_factor={implied:.6f}; residual={residual:.5%}",
                                )
                            )
                        else:
                            m = f_new / implied
                            basis = f"same-day cash+share adjustment; cash_per_share converted to post-adjustment share basis (raw div {cash:.6g}/share x multiplier {m:.6f})"
                            events.append(
                                _event(
                                    day,
                                    "cash_dividend",
                                    round(cash * m, 6),
                                    1.0,
                                    basis,
                                    f_prev,
                                    f_new,
                                    f"fund_div:{prefix}:{day}",
                                    True,
                                    "pre_close_continuity",
                                    f"combined event; div-implied residual before multiplier removal={residual:.5%}",
                                )
                            )
                            events.append(
                                _event(
                                    day,
                                    "share_adjustment",
                                    0.0,
                                    round(m, 8),
                                    basis,
                                    f_prev,
                                    f_new,
                                    None,
                                    True,
                                    "pre_close_continuity",
                                    "residual multiplier after removing the dividend effect",
                                )
                            )
                    else:
                        m = f_new / f_prev
                        cont = None
                        if pre is not None and prev_close not in (None, 0) and pre > 0:
                            cont = (pre * f_new) / (prev_close * f_prev)
                        passed = cont is not None and abs(cont - 1.0) <= CONTINUITY_TOL
                        detail = (
                            f"hfq continuity ratio={cont:.6f}"
                            if cont is not None
                            else "pre_close unavailable"
                        )
                        nav_note = _nav_check(
                            nav_lookup.get(code, {}), day, prev_date, pre, prev_close
                        )
                        if nav_note:
                            detail += "; " + nav_note
                        events.append(
                            _event(
                                day,
                                "share_adjustment",
                                0.0,
                                round(m, 8),
                                basis,
                                f_prev,
                                f_new,
                                None,
                                passed,
                                "pre_close_continuity" if passed else "unresolved_gap",
                                detail,
                            )
                        )
                elif ratio_raw is not None and abs(ratio_raw - 1.0) > 0.005:
                    discontinuities.append(
                        {
                            "date": day,
                            "prev_close": float(prev_close),
                            "pre_close": float(pre),
                            "ratio": round(float(ratio_raw), 6),
                        }
                    )
            prev_date = day
        if events:
            events_manifest[code] = events
            _write_events_parquet(
                package_dir / "events" / f"{code}.parquet", code, events
            )
        if discontinuities:
            pre_close_discontinuities[code] = discontinuities

        # ---------------- etf_limit
        code_limit = limit[limit["ts_code"] == "FUND:" + code].sort_values("trade_date")
        if len(code_limit):
            out_limit = code_limit[
                ["trade_date", "pre_close", "up_limit", "down_limit", "asset_type"]
            ].copy()
            out_limit.insert(0, "ts_code", code)
            pq.write_table(
                pa.Table.from_pandas(out_limit.reset_index(drop=True)),
                package_dir / "etf_limit" / f"{code}.parquet",
            )
            limit_first_dates.append(str(code_limit["trade_date"].iloc[0]))

        symbols_meta.append(
            {
                "code": code,
                "class": klass,
                "role": role,
                "data_start": _iso(data_start),
                "data_end": _iso(data_end),
                "missing_days": missing,
                "warmup_start": _iso(data_start),
            }
        )
        report["symbols"][code] = {
            "rows": len(dates),
            "data_start": data_start,
            "data_end": data_end,
            "expected_open_days": len(expected),
            "missing_days": missing,
            "duplicate_dates": dup_dates,
            "missing_factor_days": missing_factor_days,
            "zero_volume_days": int((out["vol_shares"] == 0).sum()),
            "fund_div_events": div_events,
            "typed_events": events,
            "unexplained_pre_close_discontinuities": discontinuities,
            "signal_ready_month": _signal_ready_month(dates),
            "etf_limit_rows": int(len(code_limit)),
        }
        print(
            f"[symbol] {code}: rows={len(dates)} missing={len(missing)} events={len(events)} "
            f"zero_vol={int((out['vol_shares'] == 0).sum())} disc={len(discontinuities)}",
            flush=True,
        )

    # ------------------------------------------------------- verified cases
    mandatory = [("159934.SZ", "2025-09-22"), ("510500.SH", "2015-04-15")]
    for code, iso_day in mandatory:
        found = [
            e
            for e in events_manifest.get(code, [])
            if e["event_date"] == iso_day and e["event_type"] == "share_adjustment"
        ]
        if not found or not found[0]["verification"]["passed"]:
            raise SystemExit(
                f"Mandatory regression case missing or unverified: {code} {iso_day}"
            )
    for code, evs in events_manifest.items():
        for e in evs:
            verified_cases.append(
                f"{code} {e['event_date']} {e['event_type']} qty_multiplier={e['qty_multiplier']:.6f} "
                f"cash_per_share={e['cash_per_share']:.6g} adj_factor "
                f"{e['derived_from']['adj_factor_prev']}->{e['derived_from']['adj_factor_new']} "
                f"verification={e['verification']['method']} ({e['verification']['detail']})"
            )

    # ----------------------------------------------------------- known gaps
    known_gaps = []
    missing_total = {
        c: r["missing_days"] for c, r in report["symbols"].items() if r["missing_days"]
    }
    if missing_total:
        known_gaps.append(
            {
                "gap_id": "DG-003",
                "desc": (
                    "fund_daily rows absent at supplier for: "
                    + "; ".join(
                        f"{c} {','.join(d)}" for c, d in sorted(missing_total.items())
                    )
                    + ". Whole-market day partitions for these dates exist in the frozen release with pipeline jobs "
                    "state=done (each day collected twice); the fund row is absent in the supplier response, so the "
                    "existing day-task backfill entry cannot recover it and no row is fabricated."
                ),
                "handling": "explicit-missing",
            }
        )
    limit_start = min(limit_first_dates) if limit_first_dates else None
    known_gaps.append(
        {
            "gap_id": "DG-004",
            "desc": (
                f"etf_limit exchange limit prices start {limit_start} for all pool codes; before that date no "
                "up/down limit reference exists in the archive. Product constraints declare a +/-10% rule "
                "approximation for pre-limit dates."
            ),
            "handling": "rule-approximation-declared",
        }
    )
    known_gaps.append(
        {
            "gap_id": "DG-007",
            "desc": (
                f"fund_nav (verification-only cross-check source) covers pool codes up to {nav_last}, lagging "
                "fund_daily; corporate-action verification after that date relies on pre_close continuity only."
            ),
            "handling": "explicit-missing",
        }
    )

    # ------------------------------------------------------------- manifest
    manifest_out = {
        "schema_version": 2,
        "package_id": f"r01-etf-daily-{release_hash[:12]}",
        "package_version": version,
        "package_uri": f"node://mac/r01-etf-daily/{version}",
        "source_release_id": args.release_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_by_node": "mac",
        "source_datasets": [
            {"api_name": api, "sha256": report["apis"][api]["file_list_sha256"]}
            for api in SOURCE_APIS
        ],
        "unit_conversions": {
            "vol": "lot(100 shares) -> shares, multiply by 100",
            "amount": "thousand CNY -> CNY, multiply by 1000",
            "rules": (
                "fund_daily vol is stored in lots (100 shares) and amount in thousand CNY; daily/*.parquet "
                "carry vol_shares=vol*100 and amount_cny=amount*1000 (rounded to 2/3 decimals); OHLC and "
                "adj_factor are unrounded. source_datasets[].sha256 is the sha256 over the sorted "
                "'path sha256\\n' lines of every release file of that api in the frozen release (see "
                "derivation-report.json apis.*.file_list_sha256). fund_nav is a verification-only source "
                "and is not a package dataset."
            ),
        },
        "factor_convention": {
            "formula": "adjusted_close = close_unadjusted × adj_factor (hfq)",
            "verified_cases": verified_cases,
        },
        "symbols": symbols_meta,
        "known_gaps": known_gaps,
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n"
    )

    _write_readme(
        package_dir,
        version,
        args,
        f"- Warmup: `warmup_start` equals `data_start` (first daily row). With the {WARMUP_MONTHS}-month MA rule",
    )
    report["pre_close_discontinuities"] = pre_close_discontinuities
    (package_dir / "derivation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    _write_sums(package_dir)

    # ------------------------------------------------------------- samples
    samples_dir = args.samples_root.expanduser() / version
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    for code, _, _ in POOL:
        table = pq.read_table(package_dir / "daily" / f"{code}.parquet")
        n = table.num_rows
        pq.write_table(
            table.slice(0, min(3, n)), samples_dir / f"sample-{code}-head.parquet"
        )
        pq.write_table(
            table.slice(max(0, n - 3)), samples_dir / f"sample-{code}-tail.parquet"
        )
        ev = package_dir / "events" / f"{code}.parquet"
        if ev.exists():
            pq.write_table(
                pq.read_table(ev), samples_dir / f"sample-{code}-events.parquet"
            )
    (samples_dir / "SAMPLE_README.md").write_text(
        "# SAMPLE DATA (not research input)\n\n"
        "Head/tail excerpts of the fixed input package for eyeballing only.\n"
        f"Real input package: node://mac/r01-etf-daily/{version}\n"
        "Do not run research on these samples.\n"
    )
    report["samples_dir"] = str(samples_dir)

    # ------------------------------------------------------------ registry
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    registry = {"packages": {}}
    if args.registry.exists():
        try:
            registry = json.loads(args.registry.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit("Node registry is corrupt") from exc
    uri = manifest_out["package_uri"]
    existing = registry["packages"].get(uri)
    if (
        existing
        and existing.get("absolute_path") != str(package_dir)
        and not args.force
    ):
        raise SystemExit(f"Registry already maps {uri} to {existing['absolute_path']}")
    registry["packages"][uri] = {
        "absolute_path": str(package_dir),
        "package_id": manifest_out["package_id"],
        "package_version": version,
        "source_release_id": args.release_id,
        "created_at": manifest_out["generated_at"],
    }
    fd, tmp = tempfile.mkstemp(dir=args.registry.parent)
    with os.fdopen(fd, "w") as handle:
        json.dump(registry, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, args.registry)

    print(
        json.dumps(
            {
                "package_uri": uri,
                "package_path": str(package_dir),
                "manifest_sha256": sha256_file(package_dir / "manifest.json"),
                "symbols": len(symbols_meta),
                "events": {c: len(e) for c, e in events_manifest.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
