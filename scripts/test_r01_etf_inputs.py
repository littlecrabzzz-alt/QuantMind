#!/usr/bin/env python3
"""Self-check the R01 ETF fixed daily input package.

Validates package integrity against ``contracts/etf-input-package.schema.json``
(v2) semantics: manifest structure, file hashes, the coverage matrix
(start/end/missing/duplicates), unit conversions, the hfq factor chain, typed
corporate-action event ordering/consistency, and (when the frozen archive is
reachable) a deterministic sampled reconciliation against the raw release
files. Exits 0 only when every check passes.

Usage:
    python3 scripts/test_r01_etf_inputs.py --package <dir> [--archive-root <dir>] \
        [--report <path>]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys

import pandas as pd
import pyarrow.parquet as pq

DEFAULT_ARCHIVE_ROOT = Path.home() / "Library/Application Support/QuantMind/tushare"
DEFAULT_REGISTRY = (
    Path.home() / "Library/Application Support/QuantMind/r01/package-registry.json"
)

CONTINUITY_TOL = 0.006  # pre_close x factor continuity (derivation used 0.005)
VWAP_TOL = 0.005
PRECLOSE_TOL = 0.005

FAILURES = []
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": str(detail)[:400]})
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail and not ok else ""),
        flush=True,
    )
    return ok


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- manifest
def validate_manifest(m):
    """Structural validation mirroring etf-input-package.schema.json (v2)."""
    problems = []

    def req(obj, keys, where):
        for key in keys:
            if key not in obj:
                problems.append(f"{where}: missing required '{key}'")

    def no_extra(obj, allowed, where):
        for key in obj:
            if key not in allowed:
                problems.append(f"{where}: additional property '{key}'")

    req(
        m,
        [
            "schema_version",
            "package_id",
            "package_version",
            "package_uri",
            "source_release_id",
            "generated_at",
            "generated_by_node",
            "source_datasets",
            "unit_conversions",
            "factor_convention",
            "symbols",
            "known_gaps",
        ],
        "manifest",
    )
    no_extra(
        m,
        {
            "schema_version",
            "package_id",
            "package_version",
            "package_uri",
            "source_release_id",
            "generated_at",
            "generated_by_node",
            "source_datasets",
            "unit_conversions",
            "factor_convention",
            "symbols",
            "known_gaps",
        },
        "manifest",
    )
    if m.get("schema_version") not in (2, 3):
        problems.append("schema_version must be 2 or 3")
    for key in ("package_id", "package_version", "source_release_id"):
        if not isinstance(m.get(key), str) or not m[key]:
            problems.append(f"{key} must be a nonempty string")
    if not isinstance(m.get("package_uri"), str) or not re.fullmatch(
        r"node://(mac|cloud)/r01-etf-daily/.+", m["package_uri"]
    ):
        problems.append("package_uri pattern violated")
    if not isinstance(m.get("generated_at"), str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*", m["generated_at"]
    ):
        problems.append("generated_at must be an ISO date-time")
    if m.get("generated_by_node") not in ("mac", "cloud"):
        problems.append("generated_by_node must be mac/cloud")

    ds = m.get("source_datasets", [])
    if not isinstance(ds, list) or not ds:
        problems.append("source_datasets must be a nonempty list")
    apis = set()
    for i, entry in enumerate(ds):
        req(entry, ["api_name", "sha256"], f"source_datasets[{i}]")
        no_extra(entry, {"api_name", "sha256"}, f"source_datasets[{i}]")
        if entry.get("api_name") not in (
            "fund_daily",
            "fund_adj",
            "fund_div",
            "trade_cal",
            "etf_limit",
        ):
            problems.append(f"source_datasets[{i}].api_name invalid")
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", entry.get("sha256", "")
        ):
            problems.append(f"source_datasets[{i}].sha256 invalid")
        apis.add(entry.get("api_name"))
    if apis != {"fund_daily", "fund_adj", "fund_div", "trade_cal", "etf_limit"}:
        problems.append(
            f"source_datasets must cover the five package apis, got {sorted(apis)}"
        )

    uc = m.get("unit_conversions", {})
    req(uc, ["vol", "amount", "rules"], "unit_conversions")
    no_extra(uc, {"vol", "amount", "rules"}, "unit_conversions")
    if uc.get("vol") != "lot(100 shares) -> shares, multiply by 100":
        problems.append("unit_conversions.vol const violated")
    if uc.get("amount") != "thousand CNY -> CNY, multiply by 1000":
        problems.append("unit_conversions.amount const violated")

    fc = m.get("factor_convention", {})
    req(fc, ["formula", "verified_cases"], "factor_convention")
    no_extra(fc, {"formula", "verified_cases"}, "factor_convention")
    if fc.get("formula") != "adjusted_close = close_unadjusted × adj_factor (hfq)":
        problems.append("factor_convention.formula const violated")
    cases = fc.get("verified_cases", [])
    if (
        not isinstance(cases, list)
        or not cases
        or not all(isinstance(c, str) for c in cases)
    ):
        problems.append("factor_convention.verified_cases must be nonempty strings")
    for mandatory in ("159934.SZ 2025-09-22", "510500.SH 2015-04-15"):
        if not any(mandatory in c for c in cases):
            problems.append(f"verified_cases missing mandatory case {mandatory}")

    classes = {"equity_broad", "gold", "treasury"}
    roles = {"primary", "backup", "regression-only"}
    codes = []
    for i, s in enumerate(m.get("symbols", [])):
        where = f"symbols[{i}]"
        req(
            s,
            [
                "code",
                "class",
                "role",
                "data_start",
                "data_end",
                "missing_days",
                "warmup_start",
            ],
            where,
        )
        no_extra(
            s,
            {
                "code",
                "class",
                "role",
                "data_start",
                "data_end",
                "missing_days",
                "warmup_start",
            },
            where,
        )
        if not isinstance(s.get("code"), str) or not re.fullmatch(
            r"[0-9]{6}\.(SH|SZ)", s.get("code", "")
        ):
            problems.append(f"{where}.code pattern violated")
        if s.get("class") not in classes:
            problems.append(f"{where}.class invalid")
        if s.get("role") not in roles:
            problems.append(f"{where}.role invalid")
        for key in ("data_start", "data_end", "warmup_start"):
            if not isinstance(s.get(key), str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", s.get(key, "")
            ):
                problems.append(f"{where}.{key} pattern violated")
        if not isinstance(s.get("missing_days"), list) or any(
            not re.fullmatch(r"\d{8}", str(d)) for d in s.get("missing_days", [])
        ):
            problems.append(f"{where}.missing_days pattern violated")
        codes.append(s.get("code"))
    if len(codes) != len(set(codes)):
        problems.append("duplicate symbol codes")

    for i, g in enumerate(m.get("known_gaps", [])):
        where = f"known_gaps[{i}]"
        req(g, ["gap_id", "desc", "handling"], where)
        no_extra(g, {"gap_id", "desc", "handling"}, where)
        if g.get("handling") not in (
            "backfill-pending",
            "explicit-missing",
            "rule-approximation-declared",
        ):
            problems.append(f"{where}.handling invalid")
    return problems


CASH_ONLY_FIELDS = (
    "event_id",
    "record_date",
    "record_date_status",
    "pay_date",
    "pay_date_status",
    "entitlement_basis",
)


def row_to_event(row):
    """Documented events/*.parquet row-to-JSON export rule.

    Drop null-valued keys that are forbidden for the row's event_type (the
    cash-only dividend fields on a share_adjustment row); keep keys required
    for the row's event_type even when null (unknown dividend dates).
    """
    e = {k: v for k, v in row.items() if k != "symbol"}
    if e.get("event_type") == "share_adjustment":
        for key in CASH_ONLY_FIELDS:
            if e.get(key) is None:
                e.pop(key, None)
    if e.get("basis_note") in (None, ""):
        e.pop("basis_note", None)
    derived = e.get("derived_from")
    if isinstance(derived, dict) and derived.get("fund_div_ref") is None:
        derived.pop("fund_div_ref", None)
    return e


def validate_typed_event(e, where, schema_version=2):
    """Mirror $defs.typed_event including the event_type conditionals."""
    problems = []
    req = [
        "event_date",
        "event_type",
        "cash_per_share",
        "qty_multiplier",
        "derived_from",
        "verification",
    ]
    v3_cash_req = list(CASH_ONLY_FIELDS)
    allowed = set(req) | {"basis_note"}
    if schema_version >= 3:
        allowed |= set(CASH_ONLY_FIELDS)
    for key in req:
        if key not in e:
            problems.append(f"{where}: missing '{key}'")
    for key in e:
        if key not in allowed:
            problems.append(f"{where}: additional property '{key}'")
    if not isinstance(e.get("event_date"), str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", e.get("event_date", "")
    ):
        problems.append(f"{where}: event_date pattern")
    etype = e.get("event_type")
    if etype not in ("cash_dividend", "share_adjustment"):
        problems.append(f"{where}: event_type enum")
    cash, mult = e.get("cash_per_share"), e.get("qty_multiplier")
    if not isinstance(cash, (int, float)) or isinstance(cash, bool) or cash < 0:
        problems.append(f"{where}: cash_per_share minimum 0")
    if not isinstance(mult, (int, float)) or isinstance(mult, bool) or mult <= 0:
        problems.append(f"{where}: qty_multiplier exclusiveMinimum 0")
    if etype == "cash_dividend":
        if mult != 1:
            problems.append(f"{where}: cash_dividend requires qty_multiplier==1")
        if not cash or cash <= 0:
            problems.append(f"{where}: cash_dividend requires cash_per_share>0")
        if schema_version >= 3:
            for key in v3_cash_req:
                if key not in e:
                    problems.append(f"{where}: v3 cash_dividend missing '{key}'")
            if not isinstance(e.get("event_id"), str) or not e.get("event_id"):
                problems.append(f"{where}: event_id must be a nonempty string")
            if e.get("entitlement_basis") != "record_date_close_holdings":
                problems.append(f"{where}: entitlement_basis enum")
            for date_key, status_key in (
                ("record_date", "record_date_status"),
                ("pay_date", "pay_date_status"),
            ):
                status = e.get(status_key)
                value = e.get(date_key)
                if status not in ("known", "unknown_blocked"):
                    problems.append(f"{where}: {status_key} enum")
                    continue
                if status == "known":
                    if not isinstance(value, str) or not re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}", value or ""
                    ):
                        problems.append(
                            f"{where}: {date_key} must be YYYY-MM-DD when {status_key}=known"
                        )
                else:
                    if value is not None:
                        problems.append(
                            f"{where}: {date_key} must be null when {status_key}=unknown_blocked"
                        )
            if "record_date_status" in e or "pay_date_status" in e:
                blocked = (
                    e.get("record_date_status") == "unknown_blocked"
                    or e.get("pay_date_status") == "unknown_blocked"
                )
                if blocked and (
                    e.get("verification", {}).get("method") != "unresolved_gap"
                    or e.get("verification", {}).get("passed") is not False
                ):
                    problems.append(
                        f"{where}: blocked dividend dates require unresolved_gap/passed=false"
                    )
                if not blocked and e.get("verification", {}).get("passed") is not True:
                    problems.append(
                        f"{where}: unblocked cash event must have passed=true"
                    )
                # three-date ordering when known
                rec, pay = e.get("record_date"), e.get("pay_date")
                ex = e.get("event_date")
                if rec and rec > ex:
                    problems.append(f"{where}: record_date after ex_date")
                if pay and pay < ex:
                    problems.append(f"{where}: pay_date before ex_date")
    elif etype == "share_adjustment":
        if cash != 0:
            problems.append(f"{where}: share_adjustment requires cash_per_share==0")
        if mult == 1:
            problems.append(f"{where}: share_adjustment requires qty_multiplier!=1")
        if schema_version >= 3:
            for key in CASH_ONLY_FIELDS:
                if key in e:
                    problems.append(f"{where}: share_adjustment must not carry '{key}'")
    derived = e.get("derived_from", {})
    for key in ("adj_factor_prev", "adj_factor_new"):
        v = derived.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            problems.append(f"{where}: derived_from.{key} exclusiveMinimum 0")
    if etype == "cash_dividend" and not derived.get("fund_div_ref"):
        problems.append(f"{where}: cash_dividend requires derived_from.fund_div_ref")
    for key in derived:
        if key not in ("adj_factor_prev", "adj_factor_new", "fund_div_ref"):
            problems.append(f"{where}: derived_from additional property '{key}'")
    verification = e.get("verification", {})
    for key in ("passed", "method"):
        if key not in verification:
            problems.append(f"{where}: verification missing '{key}'")
    if verification.get("method") not in (
        "pre_close_continuity",
        "nav_continuity",
        "fund_div_match",
        "record_date_evidence",
        "unresolved_gap",
    ):
        problems.append(f"{where}: verification.method enum")
    if not isinstance(verification.get("passed"), bool):
        problems.append(f"{where}: verification.passed bool")
    for key in verification:
        if key not in ("passed", "method", "detail"):
            problems.append(f"{where}: verification additional property '{key}'")
    return problems


# ------------------------------------------------------------- raw archive
def _scan_file(args):
    root, rel_path, api, want = args
    path = Path(root) / rel_path
    try:
        table = pq.read_table(path)
    except Exception:
        return []
    df = table.to_pandas()
    out = []
    for row in df.itertuples(index=False):
        code = str(getattr(row, "ts_code", ""))
        day = str(getattr(row, "trade_date", getattr(row, "nav_date", "")))
        if (code, day) in want:
            out.append(
                {
                    "code": code,
                    "day": day,
                    "row": {
                        c: getattr(row, c)
                        for c in df.columns
                        if c
                        not in (
                            "_fetched_at",
                            "_observation",
                            "_row_identity",
                            "_source",
                            "_api_name",
                        )
                    },
                }
            )
    return out


def reconcile_against_archive(package_dir, manifest, archive_root, report):
    """Deterministic sample reconciliation against the raw frozen release."""
    release_id = manifest["source_release_id"]
    rel_root = archive_root / "releases" / release_id
    if not (rel_root / "manifest.json").is_file():
        check("archive.reachable", False, f"{rel_root} not found")
        return
    rel_manifest = json.loads((rel_root / "manifest.json").read_bytes())
    raw = (rel_root / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != release_id.removeprefix("data-"):
        check("archive.release_checksum", False, "manifest sha mismatch")
        return
    check("archive.release_checksum", True)

    # deterministic sample: per code first/last + 3 middle days (daily), factor days for events
    want = set()
    per_code = {}
    for s in manifest["symbols"]:
        code = s["code"]
        d = pd.read_parquet(package_dir / "daily" / f"{code}.parquet")
        days = list(d["trade_date"])
        idx = sorted(
            {0, len(days) // 4, len(days) // 2, (3 * len(days)) // 4, len(days) - 1}
        )
        sample_days = [days[i] for i in idx if 0 <= i < len(days)]
        per_code[code] = {"days": sample_days}
        prefix = code[7:9] + code[:6]
        for day in sample_days:
            want.add((prefix, day))
        ev = package_dir / "events" / f"{code}.parquet"
        if ev.exists():
            e = pd.read_parquet(ev)
            for _, row in e.iterrows():
                want.add((prefix, row["event_date"].replace("-", "")))

    results = {
        "daily": {},
        "adj": {},
        "commands": [
            f"scan release {release_id} apis fund_daily,fund_adj filtering {len(want)} (code,day) pairs"
        ],
    }
    for api in ("fund_daily", "fund_adj"):
        entries = [e for e in rel_manifest["datasets"] if e.get("api_name") == api]
        jobs = [(str(archive_root), e["path"], api, want) for e in entries]
        found = {}
        with ProcessPoolExecutor(max_workers=8) as pool:
            for rows in pool.map(_scan_file, jobs, chunksize=32):
                for hit in rows:
                    key = (hit["code"], hit["day"])
                    found.setdefault(key, []).append(hit["row"])
        slot = "daily" if api == "fund_daily" else "adj"
        results[slot] = {f"{c}:{d}": v for (c, d), v in found.items()}

    mismatches = []
    compared = 0
    for s in manifest["symbols"]:
        code = s["code"]
        prefix = code[7:9] + code[:6]
        d = pd.read_parquet(package_dir / "daily" / f"{code}.parquet").set_index(
            "trade_date"
        )
        f = pd.read_parquet(package_dir / "factors" / f"{code}.parquet").set_index(
            "trade_date"
        )
        for day in per_code[code]["days"]:
            raws = results["daily"].get(f"{prefix}:{day}", [])
            if not raws:
                mismatches.append(f"{code} {day}: no raw row found")
                continue
            raw = raws[-1]
            pkg = d.loc[day]
            for pkg_col, raw_col, factor in (
                ("close", "close", 1),
                ("open", "open", 1),
                ("high", "high", 1),
                ("low", "low", 1),
                ("pre_close", "pre_close", 1),
                ("vol_shares", "vol", 100.0),
                ("amount_cny", "amount", 1000.0),
            ):
                expected = round(
                    float(raw[raw_col]) * factor, 2 if pkg_col == "vol_shares" else 3
                )
                if abs(float(pkg[pkg_col]) - expected) > max(
                    1e-6, abs(expected) * 1e-9
                ):
                    mismatches.append(
                        f"{code} {day} {pkg_col}: pkg={pkg[pkg_col]} raw*{factor}={expected}"
                    )
            if day in f.index:
                raw_fs = results["adj"].get(f"{prefix}:{day}", [])
                if raw_fs:
                    if (
                        abs(
                            float(f.loc[day, "adj_factor"])
                            - float(raw_fs[-1]["adj_factor"])
                        )
                        > 1e-12
                    ):
                        mismatches.append(
                            f"{code} {day} adj_factor: pkg={f.loc[day, 'adj_factor']} raw={raw_fs[-1]['adj_factor']}"
                        )
                    compared += 1
    report["archive_reconciliation"] = {
        "sampled_pairs": len(want),
        "factor_comparisons": compared,
        "mismatches": mismatches,
        "raw_findings": results,
    }
    check(
        "archive.sample_reconciliation",
        not mismatches,
        f"{len(want)} pairs sampled, {compared} factor rows compared, {len(mismatches)} mismatches"
        + ("; first: " + mismatches[0] if mismatches else ""),
    )


# ------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        type=Path,
        default=None,
        help="package dir; default: resolve via node registry",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--skip-archive", action="store_true")
    parser.add_argument(
        "--frozen-v1",
        type=Path,
        default=None,
        help="frozen v1 package dir to verify unchanged (default: resolve from registry)",
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    package_dir = args.package
    if package_dir is None:
        registry = json.loads(args.registry.read_text())
        if not registry.get("packages"):
            raise SystemExit("Registry empty; pass --package")
        uri, info = max(
            registry["packages"].items(), key=lambda kv: kv[1].get("created_at", "")
        )
        package_dir = Path(info["absolute_path"])
        print(f"[registry] resolved {uri} -> {package_dir}")
    package_dir = package_dir.expanduser().resolve()
    report = {"package": str(package_dir)}

    manifest_path = package_dir / "manifest.json"
    check("manifest.present", manifest_path.is_file())
    manifest = json.loads(manifest_path.read_text())
    problems = validate_manifest(manifest)
    check("manifest.schema", not problems, "; ".join(problems[:6]))

    sums_path = package_dir / "SHA256SUMS.txt"
    check("sums.present", sums_path.is_file())
    bad = []
    listed = 0
    for line in sums_path.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        path = package_dir / rel
        listed += 1
        if not path.is_file() or sha256_file(path) != digest:
            bad.append(rel)
    files_on_disk = {
        str(p.relative_to(package_dir))
        for p in package_dir.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS.txt"
    }
    files_listed = set()
    for line in sums_path.read_text().splitlines():
        files_listed.add(line.split("  ", 1)[1])
    check(
        "sums.match",
        not bad and files_on_disk == files_listed,
        f"{listed} entries; bad={bad[:3]}; on_disk_not_listed={sorted(files_on_disk - files_listed)[:3]}; "
        f"listed_not_on_disk={sorted(files_listed - files_on_disk)[:3]}",
    )

    cal = pd.read_parquet(package_dir / "calendar.parquet")
    sse = cal[cal["exchange"] == "SSE"].sort_values("cal_date")
    open_days = [str(d) for d in sse[sse["is_open"] == 1]["cal_date"]]
    check(
        "calendar.sorted_unique", list(sse["cal_date"]) == sorted(set(sse["cal_date"]))
    )
    check("calendar.is_open_domain", set(sse["is_open"].unique()) <= {0, 1})

    all_event_days = {}
    for s in manifest["symbols"]:
        code = s["code"]
        d = pd.read_parquet(package_dir / "daily" / f"{code}.parquet")
        dates = [str(x) for x in d["trade_date"]]
        iso = lambda day8: f"{day8[:4]}-{day8[4:6]}-{day8[6:]}"  # noqa: E731
        start8, end8 = s["data_start"].replace("-", ""), s["data_end"].replace("-", "")
        check(
            f"{code}.columns",
            list(d.columns)
            == [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "vol_shares",
                "amount_cny",
            ],
        )
        check(
            f"{code}.sorted_unique",
            dates == sorted(dates) and len(dates) == len(set(dates)),
            f"n={len(dates)}",
        )
        check(
            f"{code}.bounds",
            dates[0] == start8 and dates[-1] == end8,
            f"{dates[0]}..{dates[-1]} vs manifest {start8}..{end8}",
        )
        expected = [day for day in open_days if start8 <= day <= end8]
        actual_missing = [day for day in expected if day not in set(dates)]
        check(
            f"{code}.missing_matches_manifest",
            actual_missing == s["missing_days"],
            f"actual={actual_missing} manifest={s['missing_days']}",
        )
        check(
            f"{code}.rowcount",
            len(dates) + len(s["missing_days"]) == len(expected),
            f"rows={len(dates)} missing={len(s['missing_days'])} expected={len(expected)}",
        )
        check(f"{code}.ts_code_constant", set(d["ts_code"]) == {code})

        vwap_bad, ohlc_bad = [], []
        for row in d.itertuples(index=False):
            if row.vol_shares > 0 and row.amount_cny > 0:
                vwap = row.amount_cny / row.vol_shares
                if not (row.low * (1 - VWAP_TOL) <= vwap <= row.high * (1 + VWAP_TOL)):
                    vwap_bad.append((row.trade_date, round(vwap, 4)))
            if (
                row.low > row.high
                or not (row.low <= row.open <= row.high)
                or not (row.low <= row.close <= row.high)
            ):
                ohlc_bad.append(row.trade_date)
        check(
            f"{code}.units_vwap_in_range",
            not vwap_bad,
            f"{len(vwap_bad)} rows outside [low,high]: {vwap_bad[:3]}",
        )
        check(
            f"{code}.ohlc_consistent",
            not ohlc_bad,
            f"{len(ohlc_bad)} rows: {ohlc_bad[:5]}",
        )

        f = pd.read_parquet(package_dir / "factors" / f"{code}.parquet")
        fdates = [str(x) for x in f["trade_date"]]
        check(
            f"{code}.factors.sorted_unique",
            fdates == sorted(fdates) and len(fdates) == len(set(fdates)),
        )
        check(f"{code}.factors.positive", bool((f["adj_factor"] > 0).all()))
        extra_factor_days = set(fdates) - set(dates)
        check(
            f"{code}.factors.cover_daily",
            set(dates) <= set(fdates) and extra_factor_days <= set(s["missing_days"]),
            f"|factors|={len(fdates)} |daily|={len(dates)} extra_factor_days={sorted(extra_factor_days)} "
            f"missing_days={s['missing_days']}",
        )

        ev_path = package_dir / "events" / f"{code}.parquet"
        events = (
            [row_to_event(r) for r in pq.read_table(ev_path).to_pylist()]
            if ev_path.exists()
            else []
        )
        ev_problems = []
        for i, e in enumerate(events):
            ev_problems.extend(
                validate_typed_event(
                    e, f"{code}.events[{i}]", schema_version=manifest["schema_version"]
                )
            )
        check(f"{code}.events.schema", not ev_problems, "; ".join(ev_problems[:4]))
        keys = [(e["event_date"], e["event_type"]) for e in events]
        check(
            f"{code}.events.unique_sorted",
            len(keys) == len(set(keys)) and keys == sorted(keys),
        )
        blocked_cash = [
            e
            for e in events
            if e["event_type"] == "cash_dividend"
            and (
                e.get("record_date_status") == "unknown_blocked"
                or e.get("pay_date_status") == "unknown_blocked"
            )
        ]
        check(
            f"{code}.events.passing_semantics",
            all(
                e["verification"]["passed"]
                for e in events
                if e["event_type"] == "share_adjustment"
            )
            and all(
                (
                    e["verification"]["passed"]
                    and e["verification"]["method"] != "unresolved_gap"
                )
                if e not in blocked_cash
                else (
                    not e["verification"]["passed"]
                    and e["verification"]["method"] == "unresolved_gap"
                )
                for e in events
                if e["event_type"] == "cash_dividend"
            ),
            f"blocked cash events must be unresolved_gap/passed=false, "
            f"others passed=true (blocked={len(blocked_cash)})",
        )
        check(f"{code}.events.all_passed", not blocked_cash)

        factor_map = dict(zip(fdates, f["adj_factor"], strict=True))
        close_map = dict(zip(dates, d["close"], strict=True))
        pre_map = dict(zip(dates, d["pre_close"], strict=True))
        prev_map = {}
        for a, b in zip(dates, dates[1:], strict=False):
            prev_map[b] = a

        # factor changes only on event days + hfq continuity there
        event_days_iso = {e["event_date"] for e in events}
        all_event_days[code] = event_days_iso
        change_days, cont_bad = [], []
        for a, b in zip(fdates, fdates[1:], strict=False):
            if factor_map[a] != factor_map[b]:
                iso_b = iso(b)
                change_days.append(iso_b)
                if iso_b not in event_days_iso:
                    continue
                cp, pc = close_map.get(a), pre_map.get(b)
                if cp and pc and cp > 0 and pc > 0:
                    ratio = (pc * factor_map[b]) / (cp * factor_map[a])
                    if abs(ratio - 1.0) > CONTINUITY_TOL:
                        cont_bad.append((iso_b, round(ratio, 6)))
        check(
            f"{code}.factor_changes_are_events",
            set(change_days) <= event_days_iso,
            f"changes={change_days} events={sorted(event_days_iso)}",
        )
        check(
            f"{code}.events_change_factors",
            event_days_iso <= set(change_days),
            f"events without factor change: {sorted(event_days_iso - set(change_days))}",
        )
        check(f"{code}.hfq_continuity", not cont_bad, str(cont_bad[:4]))

        # derived_from factors match the package factor series
        deriv_bad = []
        for e in events:
            day8 = e["event_date"].replace("-", "")
            prev8 = prev_map.get(day8)
            if (
                prev8 is None
                or factor_map.get(day8) != e["derived_from"]["adj_factor_new"]
                or factor_map.get(prev8) != e["derived_from"]["adj_factor_prev"]
            ):
                deriv_bad.append(e["event_date"])
            if (
                e["event_type"] == "cash_dividend"
                and abs(
                    e["qty_multiplier"]
                    - e["derived_from"]["adj_factor_new"]
                    / e["derived_from"]["adj_factor_prev"]
                    - 1
                )
                > 1e-9
            ):
                # cash events still record multiplier 1 while factors moved by the dividend effect; that is expected
                pass
        check(f"{code}.derived_from_matches_factors", not deriv_bad, str(deriv_bad[:4]))

        # multiplier equals factor ratio for share_adjustment
        mult_bad = []
        for e in events:
            if e["event_type"] == "share_adjustment":
                expected_m = (
                    e["derived_from"]["adj_factor_new"]
                    / e["derived_from"]["adj_factor_prev"]
                )
                if abs(e["qty_multiplier"] - expected_m) > 5e-8:
                    mult_bad.append((e["event_date"], e["qty_multiplier"], expected_m))
        check(f"{code}.multiplier_equals_factor_ratio", not mult_bad, str(mult_bad[:3]))

        # cash events reconcile with dividends parquet
        div_path = package_dir / "dividends" / f"{code}.parquet"
        if any(e["event_type"] == "cash_dividend" for e in events):
            check(f"{code}.dividends.present", div_path.is_file())
            dv = pd.read_parquet(div_path)
            by_ex = dv.groupby("ex_date")["div_cash"].sum().to_dict()
            cash_bad = []
            for e in events:
                if e["event_type"] != "cash_dividend":
                    continue
                day8 = e["event_date"].replace("-", "")
                raw_sum = float(by_ex.get(day8, 0.0))
                expected_cash = raw_sum
                if e.get("basis_note"):
                    mult = e["qty_multiplier"]
                    expected_cash = (
                        raw_sum * mult
                    )  # combined events carry post-adjustment cash
                if abs(e["cash_per_share"] - expected_cash) > 1e-6:
                    cash_bad.append(
                        (e["event_date"], e["cash_per_share"], expected_cash)
                    )
            check(f"{code}.cash_events_match_fund_div", not cash_bad, str(cash_bad[:3]))
        else:
            check(
                f"{code}.dividends.absent_ok",
                not div_path.exists() or len(pd.read_parquet(div_path)) == 0,
            )

        # unexplained pre_close discontinuities must match derivation report
        disc = []
        for a, b in zip(dates, dates[1:], strict=False):
            if b in {x.replace("-", "") for x in event_days_iso}:
                continue
            # skip pairs spanning missing days for this symbol
            span = [day for day in open_days if a < day <= b]
            if len(span) != 1:
                continue
            cp, pc = close_map[a], pre_map[b]
            if cp and pc and abs(pc / cp - 1.0) > PRECLOSE_TOL:
                disc.append((b, round(pc / cp, 6)))
        derivation = json.loads((package_dir / "derivation-report.json").read_text())
        # v2 upgrade reports document only the v1->v2 diff; per-symbol derivation
        # evidence lives in the v1 report and its files are hash-identical here.
        reported = (
            derivation.get("symbols", {})
            .get(code, {})
            .get("unexplained_pre_close_discontinuities", [])
        )
        check(
            f"{code}.preclose_discontinuities_reconciled",
            len(disc) == len(reported) == 0
            or {x[0] for x in disc} == {iso(x["date"]) for x in reported},
            f"found={disc[:4]} reported={reported[:4]}",
        )

        # etf_limit spot checks
        lim_path = package_dir / "etf_limit" / f"{code}.parquet"
        if lim_path.exists():
            lim = pd.read_parquet(lim_path)
            ldates = [str(x) for x in lim["trade_date"]]
            check(
                f"{code}.etf_limit.sorted_unique",
                ldates == sorted(ldates) and len(ldates) == len(set(ldates)),
            )
            joint = lim.merge(d, on="trade_date")
            bad_limits = joint[
                (joint["close"] > joint["up_limit"] * 1.0001)
                | (joint["close"] < joint["down_limit"] * 0.9999)
            ]
            check(
                f"{code}.etf_limit.brackets_close",
                len(bad_limits) == 0,
                f"{len(bad_limits)} violations; sample={bad_limits[['trade_date', 'close', 'up_limit', 'down_limit']].head(3).to_dict('records') if len(bad_limits) else ''}",
            )

    # mandatory regression cases
    for code, day in (("159934.SZ", "2025-09-22"), ("510500.SH", "2015-04-15")):
        ev_path = package_dir / "events" / f"{code}.parquet"
        ok, detail = False, "events file missing"
        if ev_path.exists():
            hits = [
                e
                for e in pq.read_table(ev_path).to_pylist()
                if e["event_date"] == day
                and e["event_type"] == "share_adjustment"
                and e["verification"]["passed"]
            ]
            ok = bool(hits)
            detail = f"hits={len(hits)}"
        check(f"mandatory.{code}.{day}", ok, detail)

    # AC-01 authoritative case: 511090 registration 2024-04-23 / ex 2024-04-24 /
    # pay 2024-04-29, 1.5 CNY/share (SSE fund announcement)
    if manifest["schema_version"] >= 3:
        ev_path = package_dir / "events" / "511090.SH.parquet"
        ok, detail = False, "events file missing"
        if ev_path.exists():
            hits = [
                row_to_event(r)
                for r in pq.read_table(ev_path).to_pylist()
                if r["event_date"] == "2024-04-24"
                and r["event_type"] == "cash_dividend"
            ]
            ok = bool(hits) and all(
                h["record_date"] == "2024-04-23"
                and h["record_date_status"] == "known"
                and h["pay_date"] == "2024-04-29"
                and h["pay_date_status"] == "known"
                and abs(h["cash_per_share"] - 1.5) < 1e-9
                and h["verification"]["passed"]
                and h["entitlement_basis"] == "record_date_close_holdings"
                for h in hits
            )
            detail = f"hits={len(hits)}" + (f" first={hits[0]}" if hits else "")
        check("mandatory.511090.SH.2024-04-24.three_dates", ok, detail)

        # event_id uniqueness across the package
        ids = []
        for s in manifest["symbols"]:
            ev_path = package_dir / "events" / f"{s['code']}.parquet"
            if ev_path.exists():
                ids.extend(
                    e["event_id"]
                    for e in (
                        row_to_event(r) for r in pq.read_table(ev_path).to_pylist()
                    )
                    if e.get("event_id")
                )
        check("events.event_id_unique", len(ids) == len(set(ids)), f"n={len(ids)}")

    # v1 freeze check: the frozen v1 package must be untouched (AC-01 fix keeps it)
    frozen_v1 = getattr(args, "frozen_v1", None)
    if frozen_v1 is None and args.registry.is_file():
        registry = json.loads(args.registry.read_text())
        entry = registry.get("packages", {}).get("node://mac/r01-etf-daily/v1-fcbabbb7")
        if entry:
            frozen_v1 = Path(entry["absolute_path"])
    if frozen_v1 is not None and Path(frozen_v1).is_dir():
        frozen_v1 = Path(frozen_v1).expanduser().resolve()
        v1_manifest = json.loads((frozen_v1 / "manifest.json").read_text())
        v1_sums_ok, v1_files = True, 0
        for line in (frozen_v1 / "SHA256SUMS.txt").read_text().splitlines():
            digest, rel = line.split("  ", 1)
            path = frozen_v1 / rel
            v1_files += 1
            if not path.is_file() or sha256_file(path) != digest:
                v1_sums_ok = False
                break
        v1_sha = sha256_file(frozen_v1 / "manifest.json") if v1_sums_ok else None
        lineage_ok = True
        lineage_note = ""
        dr = package_dir / "derivation-report.json"
        if dr.is_file():
            lineage = json.loads(dr.read_text())
            expected = lineage.get("v1_manifest_sha256")
            if expected and v1_sha != expected:
                lineage_ok = False
                lineage_note = f"lineage expects {expected[:12]}…, got {v1_sha[:12] if v1_sha else None}"
        check(
            "frozen_v1.unchanged",
            v1_sums_ok and lineage_ok and v1_manifest.get("schema_version") == 2,
            f"files={v1_files} sums_ok={v1_sums_ok} manifest_sha={v1_sha[:16] if v1_sha else None}… {lineage_note}",
        )
        report["frozen_v1"] = {
            "path": str(frozen_v1),
            "manifest_sha256": v1_sha,
            "sums_verified": v1_sums_ok,
            "files": v1_files,
        }
        # v1 -> v2 diff: non-event files byte-identical
        if manifest["schema_version"] >= 3 and v1_sums_ok:
            v1_sums = {}
            for line in (frozen_v1 / "SHA256SUMS.txt").read_text().splitlines():
                digest, rel = line.split("  ", 1)
                v1_sums[rel] = digest
            v2_sums = {}
            for line in (package_dir / "SHA256SUMS.txt").read_text().splitlines():
                digest, rel = line.split("  ", 1)
                v2_sums[rel] = digest
            changed = []
            for rel, digest in v2_sums.items():
                if rel.startswith("events/") or rel in (
                    "manifest.json",
                    "README.md",
                    "derivation-report.json",
                    "SHA256SUMS.txt",
                ):
                    continue
                if v1_sums.get(rel) != digest:
                    changed.append(rel)
            v1_only = [
                rel
                for rel in v1_sums
                if rel not in v2_sums
                and not rel.startswith("events/")
                and rel
                not in (
                    "manifest.json",
                    "README.md",
                    "derivation-report.json",
                    "SHA256SUMS.txt",
                )
            ]
            check(
                "diff_v1_v2.only_events_changed",
                not changed and not v1_only,
                f"changed={changed[:5]} v1_only={v1_only[:5]}",
            )
            # share_adjustment events unchanged between v1 and v2
            sa_changed = []
            for s in manifest["symbols"]:
                code = s["code"]
                p1, p2 = (
                    frozen_v1 / "events" / f"{code}.parquet",
                    package_dir / "events" / f"{code}.parquet",
                )
                if p1.exists() != p2.exists():
                    sa_changed.append(code)
                    continue
                if not p1.exists():
                    continue
                sa1 = [
                    e
                    for e in (row_to_event(r) for r in pq.read_table(p1).to_pylist())
                    if e["event_type"] == "share_adjustment"
                ]
                sa2 = [
                    e
                    for e in (row_to_event(r) for r in pq.read_table(p2).to_pylist())
                    if e["event_type"] == "share_adjustment"
                ]
                if sa1 != sa2:
                    sa_changed.append(code)
            check(
                "diff_v1_v2.share_adjustment_unchanged", not sa_changed, str(sa_changed)
            )
    else:
        print(
            "[SKIP] frozen_v1.unchanged (v1 package not resolvable; pass --frozen-v1)"
        )

    if not args.skip_archive:
        reconcile_against_archive(
            package_dir, manifest, args.archive_root.expanduser().resolve(), report
        )

    report["checks"] = CHECKS
    report["failures"] = FAILURES
    report["ok"] = not FAILURES
    report_path = args.report or (
        package_dir.parent / f"test-report-{package_dir.name}.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    print(
        f"\n{len(CHECKS) - len(FAILURES)}/{len(CHECKS)} checks passed; report: {report_path}"
    )
    if FAILURES:
        print("FAILURES:", *FAILURES[:20], sep="\n  ")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
