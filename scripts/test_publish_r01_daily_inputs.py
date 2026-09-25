#!/usr/bin/env python3
"""Self-check the R01 daily incremental input packages (H2.1-D1/D2).

Validates every published daily package (`d<YYYYMMDD>`, schema v3.1) in the
node registry: manifest structure, file hashes, identity quintuple, single-day
content shape, event equivalence with the frozen v2 package, quality-gate
consistency and the H2.1-D2 readiness gate — including explicit negative
(blocked) cases and a tamper-detection check. The frozen v1/v2 fixed packages
are re-verified unchanged (regression), and the archive stays read-only.

Exits 0 only when every check passes.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_r01_daily_inputs as pub  # noqa: E402
import prepare_r01_etf_inputs as base  # noqa: E402
from test_r01_etf_inputs import (  # noqa: E402
    validate_manifest,
    validate_typed_event,
    row_to_event,
    sha256_file,
)

FROZEN_EXPECTED = {
    "node://mac/r01-etf-daily/v1-fcbabbb7": "cd8b807e8caf152c8d7e5c024ba518722bb3acad68de73b483b922adf7135245",
    "node://mac/r01-etf-daily/v2-fcbabbb7": "a0d88429301685aa3939b294c38bb942013de4befe29e8a01e7a1f03a80fc622",
}
V2_URI = "node://mac/r01-etf-daily/v2-fcbabbb7"

FAILURES = []
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail and not ok else ""),
        flush=True,
    )
    return ok


def verify_sums(package_dir: Path):
    listed = {}
    for line in (package_dir / "SHA256SUMS.txt").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        path = package_dir / rel
        if not path.is_file() or sha256_file(path) != digest:
            return None, rel
        listed[rel] = digest
    on_disk = {
        str(p.relative_to(package_dir))
        for p in package_dir.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS.txt"
    }
    if on_disk != set(listed):
        return None, "file set mismatch vs SHA256SUMS"
    return listed, None


def check_daily_package(
    package_dir: Path, registry_entry: dict, baseline_dir: Path, tag: str
):
    manifest = json.loads((package_dir / "manifest.json").read_text())
    problems = validate_manifest(manifest)
    check(f"{tag}.manifest_schema", not problems, "; ".join(problems[:5]))

    sums, bad = verify_sums(package_dir)
    check(f"{tag}.sums", sums is not None, bad)

    manifest_sha = sha256_file(package_dir / "manifest.json")
    check(
        f"{tag}.identity",
        (
            manifest["package_version"] == package_dir.name
            and registry_entry.get("manifest_sha256") == manifest_sha
            and manifest["decision_date"] == manifest["data_as_of"]
            and manifest["decision_date"].replace("-", "") == package_dir.name[1:9]
        ),
        f"version={manifest['package_version']} registry_sha={registry_entry.get('manifest_sha256', '')[:12]} actual={manifest_sha[:12]}",
    )

    decision8 = manifest["decision_date"].replace("-", "")
    cal = pd.read_parquet(package_dir / "calendar.parquet")
    sse_open = {
        str(d)
        for d in cal[(cal["exchange"] == "SSE") & (cal["is_open"] == 1)]["cal_date"]
    }
    check(f"{tag}.decision_is_trade_day", decision8 in sse_open)

    baseline_manifest = json.loads((baseline_dir / "manifest.json").read_text())
    baseline_events = {}
    for s in baseline_manifest["symbols"]:
        p = baseline_dir / "events" / f"{s['code']}.parquet"
        if p.exists():
            baseline_events[s["code"]] = [
                row_to_event(r) for r in pq.read_table(p).to_pylist()
            ]

    for s in manifest["symbols"]:
        code = s["code"]
        d = pd.read_parquet(package_dir / "daily" / f"{code}.parquet")
        row_expected = s["missing_days"] == []
        codes_in_file = set(d["ts_code"].tolist()) if len(d) else set()
        check(
            f"{tag}.{code}.daily_shape",
            (
                len(d) == (1 if row_expected else 0)
                and (len(d) == 0 or str(d.iloc[0]["trade_date"]) == decision8)
                and codes_in_file <= {code}
            ),
            f"rows={len(d)} missing_days={s['missing_days']} codes={codes_in_file}",
        )
        f = pd.read_parquet(package_dir / "factors" / f"{code}.parquet")
        factor = None if f.empty else float(f.iloc[0]["adj_factor"])
        check(
            f"{tag}.{code}.factor_shape",
            len(f) == 1 and factor is not None and factor > 0,
        )
        if row_expected and len(d):
            row = d.iloc[0]
            vol, amount = float(row["vol_shares"]), float(row["amount_cny"])
            if vol > 0 and amount > 0:
                vwap = amount / vol
                check(
                    f"{tag}.{code}.units",
                    float(row["low"]) * 0.995 <= vwap <= float(row["high"]) * 1.005,
                    f"vwap={vwap:.4f} low={row['low']} high={row['high']}",
                )
        ev_path = package_dir / "events" / f"{code}.parquet"
        if ev_path.exists():
            events = [row_to_event(r) for r in pq.read_table(ev_path).to_pylist()]
            ev_problems = [
                p
                for i, e in enumerate(events)
                for p in validate_typed_event(
                    e, f"{tag}.{code}.events[{i}]", schema_version=3.1
                )
            ]
            check(
                f"{tag}.{code}.events_schema",
                not ev_problems,
                "; ".join(ev_problems[:3]),
            )
            same_day_baseline = [
                e
                for e in baseline_events.get(code, [])
                if e["event_date"] == manifest["decision_date"]
            ]

            def _semantic(e):
                e = json.loads(json.dumps(e))
                e.get("verification", {}).pop(
                    "detail", None
                )  # prose differs (v2 adds nav cross-check note)
                return e

            check(
                f"{tag}.{code}.events_match_baseline",
                [_semantic(e) for e in events]
                == [_semantic(e) for e in same_day_baseline],
                f"daily={[e['event_type'] for e in events]} baseline={[e['event_type'] for e in same_day_baseline]}",
            )
        else:
            same_day_baseline = [
                e
                for e in baseline_events.get(code, [])
                if e["event_date"] == manifest["decision_date"]
            ]
            check(f"{tag}.{code}.no_events_consistent", not same_day_baseline)
        lim_path = package_dir / "etf_limit" / f"{code}.parquet"
        if lim_path.exists() and row_expected and len(d):
            lim = pd.read_parquet(lim_path)
            ok = (
                len(lim) == 1
                and float(lim.iloc[0]["down_limit"]) * 0.9999
                <= float(d.iloc[0]["close"])
                <= float(lim.iloc[0]["up_limit"]) * 1.0001
            )
            check(f"{tag}.{code}.limit_brackets_close", ok)

    # quality gate consistency + positive readiness
    gate = manifest["quality_gate"]
    detail_market = gate["checks"]["market_rows"]["detail"]["per_symbol"]
    actual_rows = {s["code"]: (s["missing_days"] == []) for s in manifest["symbols"]}
    check(
        f"{tag}.gate_market_consistent",
        {c: v["row"] for c, v in detail_market.items()} == actual_rows,
    )
    readiness = pub.evaluate_data_readiness(manifest, manifest_sha)
    check(
        f"{tag}.readiness_ready",
        readiness["ready"] and not readiness["data_blocked"],
        str(readiness["blocked_reasons"]),
    )
    check(
        f"{tag}.identity_quintuple",
        all(readiness["identity"].values()),
        str(readiness["identity"]),
    )
    return manifest, manifest_sha


def negative_gate_cases(manifest: dict, manifest_sha: str):
    def mutate(**kw):
        m = json.loads(json.dumps(manifest))
        for k, v in kw.items():
            if v is None and k in m:
                del m[k]
            else:
                m[k] = v
        return m

    cases = [
        (
            "stale_data",
            mutate(decision_date=_next_day(manifest["decision_date"])),
            "stale-data",
        ),
        (
            "quality_blocked",
            mutate(
                quality_gate={
                    **manifest["quality_gate"],
                    "overall": "blocked",
                    "blocked_reasons": ["market_rows: required missing"],
                }
            ),
            "market_rows",
        ),
        ("missing_obtained_at", mutate(obtained_at=None), "obtained_at"),
        ("wrong_kind", mutate(package_kind="fixed"), "package_kind"),
        (
            "non_trade_day",
            mutate(
                quality_gate={
                    **manifest["quality_gate"],
                    "decision_date_is_trade_day": False,
                }
            ),
            "not an SSE open day",
        ),
        ("revised_without_supersedes", mutate(revised=True), "supersedes"),
        ("wrong_schema_version", mutate(schema_version=3), "schema_version"),
        ("wrong_version_namespace", mutate(package_version="v9-xyz"), "d<date>"),
    ]
    for name, m, needle in cases:
        result = pub.evaluate_data_readiness(m, manifest_sha)
        check(
            f"gate_negative.{name}",
            result["data_blocked"]
            and not result["ready"]
            and any(needle in r for r in result["blocked_reasons"]),
            f"reasons={result['blocked_reasons']}",
        )


def _next_day(iso_day: str) -> str:
    from datetime import datetime, timedelta

    d = datetime.strptime(iso_day, "%Y-%m-%d") + timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def tamper_detection(package_dir: Path, tag: str):
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / "pkg"
        shutil.copytree(package_dir, copied)
        target = copied / "daily" / "510300.SH.parquet"
        raw = bytearray(target.read_bytes())
        raw[-1] ^= 0xFF
        target.write_bytes(bytes(raw))
        sums, bad = verify_sums(copied)
        check(f"{tag}.tamper_detected", sums is None and bad is not None, f"bad={bad}")


def _recon_scan(args):
    root, rel_path, want = args
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


def reconcile_archive(package_dir: Path, manifest: dict, archive_root: Path, tag: str):
    release_id = manifest["source_release_id"]
    rel_root = archive_root / "releases" / release_id
    if not (rel_root / "manifest.json").is_file():
        check(f"{tag}.archive_reachable", False, str(rel_root))
        return
    rel_manifest = json.loads((rel_root / "manifest.json").read_bytes())
    decision8 = manifest["decision_date"].replace("-", "")
    want = set()
    for s in manifest["symbols"]:
        prefix = s["code"][7:9] + s["code"][:6]
        want.add((prefix, decision8))
    found = {"fund_daily": {}, "fund_adj": {}}
    for api in ("fund_daily", "fund_adj"):
        jobs = [
            (str(archive_root), e["path"], want)
            for e in rel_manifest["datasets"]
            if e.get("api_name") == api
        ]
        with ProcessPoolExecutor(max_workers=8) as pool:
            for rows in pool.map(_recon_scan, jobs, chunksize=32):
                for hit in rows:
                    found[api].setdefault(f"{hit['code']}:{hit['day']}", []).append(
                        hit["row"]
                    )
    mismatches = []
    for s in manifest["symbols"]:
        code = s["code"]
        prefix = code[7:9] + code[:6]
        d = pd.read_parquet(package_dir / "daily" / f"{code}.parquet")
        raws = found["fund_daily"].get(f"{prefix}:{decision8}", [])
        if not raws:
            mismatches.append(f"{code} {decision8}: no raw row")
            continue
        raw = raws[-1]
        if d.empty:
            mismatches.append(f"{code}: package empty but raw row exists")
            continue
        row = d.iloc[0]
        for pkg_col, raw_col, factor in (
            ("close", "close", 1.0),
            ("vol_shares", "vol", 100.0),
            ("amount_cny", "amount", 1000.0),
        ):
            expected = round(
                float(raw[raw_col]) * factor, 2 if pkg_col == "vol_shares" else 3
            )
            if abs(float(row[pkg_col]) - expected) > max(1e-6, abs(expected) * 1e-9):
                mismatches.append(
                    f"{code} {pkg_col}: pkg={row[pkg_col]} raw*{factor}={expected}"
                )
        f = pd.read_parquet(package_dir / "factors" / f"{code}.parquet")
        raw_f = found["fund_adj"].get(f"{prefix}:{decision8}", [])
        if (
            raw_f
            and abs(float(f.iloc[0]["adj_factor"]) - float(raw_f[-1]["adj_factor"]))
            > 1e-12
        ):
            mismatches.append(
                f"{code} adj_factor pkg={f.iloc[0]['adj_factor']} raw={raw_f[-1]['adj_factor']}"
            )
    check(
        f"{tag}.archive_reconciliation",
        not mismatches,
        f"{len(want)} codes reconciled; {len(mismatches)} mismatches; first={mismatches[:2]}",
    )


def frozen_regression(registry: dict):
    for uri, expected_sha in FROZEN_EXPECTED.items():
        entry = registry["packages"].get(uri)
        ok, detail = False, "registry entry missing"
        if entry:
            frozen = Path(entry["absolute_path"])
            actual = sha256_file(frozen / "manifest.json")
            sums_ok = True
            n = 0
            for line in (frozen / "SHA256SUMS.txt").read_text().splitlines():
                digest, rel = line.split("  ", 1)
                n += 1
                if not (frozen / rel).is_file() or sha256_file(frozen / rel) != digest:
                    sums_ok = False
                    break
            ok = actual == expected_sha and sums_ok
            detail = f"files={n} sums_ok={sums_ok} sha_match={actual == expected_sha}"
        check(f"frozen.{uri.rsplit('/', 1)[-1]}", ok, detail)


def revision_flow(args, registry_path: Path, day8: str, tag: str):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_registry = Path(tmp) / "registry.json"
        shutil.copy(registry_path, tmp_registry)
        cmd = [
            sys.executable,
            str(Path(__file__).parent / "publish_r01_daily_inputs.py"),
            "--decision-date",
            day8,
            "--revision",
            "r2",
            "--output-root",
            str(Path(tmp) / "out"),
            "--registry",
            str(tmp_registry),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        check(
            f"{tag}.revision_publish_exit",
            proc.returncode == 0,
            proc.stderr[-300:] if proc.returncode else "",
        )
        if proc.returncode:
            return
        rev_dir = Path(tmp) / "out" / f"d{day8}r2"
        m = json.loads((rev_dir / "manifest.json").read_text())
        registry = json.loads(tmp_registry.read_text())
        orig_entry = json.loads(registry_path.read_text())["packages"][
            f"node://mac/r01-etf-daily/d{day8}"
        ]
        orig_sha = sha256_file(Path(orig_entry["absolute_path"]) / "manifest.json")
        check(
            f"{tag}.revision_fields",
            (
                m["revised"] is True
                and m["supersedes"]["package_version"] == f"d{day8}"
                and m["supersedes"]["manifest_sha256"] == orig_sha
                and m["package_version"] == f"d{day8}r2"
            ),
            f"supersedes={m.get('supersedes')}",
        )
        ready = pub.evaluate_data_readiness(m, sha256_file(rev_dir / "manifest.json"))
        check(f"{tag}.revision_ready", ready["ready"], str(ready["blocked_reasons"]))
        # original untouched
        now_sha = sha256_file(Path(orig_entry["absolute_path"]) / "manifest.json")
        check(f"{tag}.revision_original_untouched", now_sha == orig_sha)
        check(
            f"{tag}.revision_registry_entry",
            f"node://mac/r01-etf-daily/d{day8}r2" in registry["packages"],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=base.DEFAULT_REGISTRY)
    parser.add_argument("--archive-root", type=Path, default=base.DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--skip-archive", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text())
    daily = {
        u: e
        for u, e in registry["packages"].items()
        if e.get("kind") == "daily_increment"
    }
    check("registry.has_daily", bool(daily), f"{len(daily)} daily packages")
    baseline_entry = registry["packages"].get(V2_URI)
    check("baseline.v2_registered", baseline_entry is not None)
    baseline_dir = Path(baseline_entry["absolute_path"])

    report = {"daily_packages": {}}
    primary_manifest = None
    primary_sha = None
    primary_dir = None
    for uri, entry in sorted(daily.items()):
        package_dir = Path(entry["absolute_path"])
        tag = entry["package_version"]
        manifest, manifest_sha = check_daily_package(
            package_dir, entry, baseline_dir, tag
        )
        report["daily_packages"][uri] = {
            "manifest_sha256": manifest_sha,
            "readiness": pub.evaluate_data_readiness(manifest, manifest_sha),
        }
        if (
            primary_manifest is None
            or manifest["decision_date"] > primary_manifest["decision_date"]
        ):
            primary_manifest, primary_sha, primary_dir = (
                manifest,
                manifest_sha,
                package_dir,
            )

    negative_gate_cases(primary_manifest, primary_sha)
    tamper_detection(primary_dir, "d-primary")
    if not args.skip_archive:
        reconcile_archive(
            primary_dir,
            primary_manifest,
            args.archive_root.expanduser().resolve(),
            "d-primary",
        )
    revision_flow(
        args,
        args.registry,
        primary_manifest["decision_date"].replace("-", ""),
        "d-primary",
    )
    frozen_regression(registry)

    report["checks"] = CHECKS
    report["failures"] = FAILURES
    report["ok"] = not FAILURES
    report_path = args.report or (
        Path.home()
        / "Library/Application Support/QuantMind/r01/etf-daily"
        / "test-report-daily.json"
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
