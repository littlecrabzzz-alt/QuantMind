#!/usr/bin/env python3
"""Sole producer of paper-readiness v1 (contract: quantmind-aline backend/README.md
`唯一日更契约：paper-readiness v1`).

Reads the managed Tushare archive and the frozen artifact tree read-only, verifies
row-level dates from real release partitions (cached per release so 15-minute ticks
stay cheap), and writes the readiness JSON consumed by the paper tick. Never issues
vendor requests and never writes inside the archive or artifact roots.

All emitted paths are relative to the two contract roots (archive-root, artifact-root);
no absolute host paths, no `..` escapes.
"""

import argparse
import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.compute as pc

ACCOUNTS = ("lowvol", "b2_lowvol_vt", "b3_lqv_buf_vt", "i7_turn_of_month",
            "s1_invvol_etf", "cb_double_low", "cta_combined", "cta_trend")
ASSET_KEYS = ("i7_turn_of_month", "s1_invvol_etf", "cb_double_low",
              "cta_combined", "cta_trend")
BAR_APIS = ("daily", "daily_basic", "adj_factor", "fund_daily", "index_daily", "stk_limit")
DIMENSION_APIS = ("fund_basic", "index_basic", "index_classify", "index_member_all",
                  "stock_basic", "sw_daily")
RESEARCH_APIS = BAR_APIS + DIMENSION_APIS + ("ci_daily", "moneyflow", "suspend_d",
                                             "trade_cal", "index_weight")
ETF_LIMIT_CODES = ("510300.SH", "511010.SH", "518880.SH")


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _relative_under(root, path):
    rel = Path(path).resolve().relative_to(Path(root).resolve())
    text = rel.as_posix()
    if text.startswith("/") or ".." in text.split("/"):
        raise ValueError(f"path escapes root: {text}")
    return text


def _release_manifest(archive, pointer_name):
    pointer = archive / pointer_name
    body = json.loads(pointer.read_bytes())
    release_id = body["release_id"]
    manifest = archive / "releases" / release_id / "manifest.json"
    if not manifest.is_file():
        return {"valid": False, "release_id": release_id,
                "reasons": [f"manifest missing: releases/{release_id}/manifest.json"]}
    actual = _sha256_file(manifest)
    expected = body.get("manifest_sha256")
    valid = expected is None or actual == expected
    return {"valid": valid, "release_id": release_id, "manifest": manifest,
            "manifest_sha256": actual,
            "reasons": [] if valid else ["manifest sha256 mismatch with pointer"]}


def _dataset_files(archive, manifest, api):
    body = json.loads(manifest.read_bytes())
    out = []
    for entry in body.get("datasets", []):
        if entry.get("api_name") != api:
            continue
        path = archive / entry["path"]
        if path.is_file():
            out.append(path)
    return out


def _row_extremes(files, date_cols=("trade_date", "cal_date")):
    if not files:
        return None
    dataset = ds.dataset(files, format="parquet")
    names = dataset.schema.names
    column = next((c for c in date_cols if c in names), None)
    if column is None:
        return {"date_col": None, "min": None, "max": None}
    values = dataset.to_table(columns=[column]).column(0).drop_null()
    if len(values) == 0:
        return {"date_col": column, "min": None, "max": None}
    return {"date_col": column, "min": str(pc.min(values).as_py()),
            "max": str(pc.max(values).as_py())}


def _cached_scan(cache, key, produce):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{key}.json"
    if path.is_file():
        try:
            return json.loads(path.read_bytes())
        except ValueError:
            pass
    value = produce()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
    temporary.replace(path)
    return value


def api_cutoffs(archive, release, cache):
    manifest = release["manifest"]
    results = _cached_scan(cache, f"cutoffs-{release['release_id']}",
                           lambda: {api: _row_extremes(_dataset_files(archive, manifest, api))
                                    for api in RESEARCH_APIS})
    cutoffs = {}
    for api, info in results.items():
        if info is None or info.get("date_col") is None:
            cutoffs[api] = None
        else:
            cutoffs[api] = _iso(info.get("max"))
    return cutoffs


def _iso(yyyymmdd):
    if not yyyymmdd:
        return None
    text = str(yyyymmdd)
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text


def calendar_info(archive, fundamentals, cache, usable_date):
    files = _dataset_files(archive, fundamentals["manifest"], "trade_cal")

    def scan():
        best_abs, best_open, tail = None, None, []
        for path in files:
            dataset = ds.dataset([path], format="parquet")
            names = dataset.schema.names
            if "cal_date" not in names or "is_open" not in names:
                continue
            table = dataset.to_table(columns=["cal_date", "is_open"])
            open_days = sorted({str(d) for d, o in zip(table.column("cal_date").to_pylist(),
                                                       table.column("is_open").to_pylist(), strict=False)
                                if o == 1})
            if not open_days:
                continue
            if best_open is None or open_days[-1] > best_open:
                best_open, best_abs = open_days[-1], str(path)
            tail.extend(d for d in open_days if d > "20260901")
        tail = sorted(set(tail))
        return {"best_abs": best_abs, "open_tail": tail[-15:]}

    facts = _cached_scan(cache, f"calendar-{fundamentals['release_id']}", scan)
    entry = {"path": None, "sha256": None, "confirmed_next_session": None}
    reasons = []
    best_abs = facts.get("best_abs")
    if best_abs and Path(best_abs).is_file():
        entry["path"] = _relative_under(archive, best_abs)
        entry["sha256"] = _sha256_file(best_abs)
    else:
        reasons.append("no trade_cal partition with open days in full release")
    tail = facts.get("open_tail", [])
    usable_compact = usable_date.replace("-", "") if usable_date else None
    nxt = next((d for d in tail if usable_compact and d > usable_compact), None)
    if nxt:
        entry["confirmed_next_session"] = _iso(nxt)
    else:
        reasons.append(
            "trade_cal does not confirm an SSE session after usable_date "
 f"(latest open day {_iso(tail[-1]) if tail else 'unknown'}); "
            "future-calendar supplement pending")
    return entry, reasons


def etf_limit_facts(archive, release, cache, usable_date):
    def produce():
        files = _dataset_files(archive, release["manifest"], "stk_limit")
        if not files:
            return {"codes": {}, "columns": []}
        dataset = ds.dataset(files, format="parquet")
        names = dataset.schema.names
        wanted = ["ts_code", "trade_date"] + [c for c in ("up_limit", "down_limit")
                                              if c in names]
        table = dataset.to_table(
            columns=wanted, filter=ds.field("ts_code").isin(list(ETF_LIMIT_CODES)))
        codes = {code: {"rows": 0, "max": None} for code in ETF_LIMIT_CODES}
        ts = table.column("ts_code").to_pylist()
        dates = table.column("trade_date").to_pylist()
        for code, date in zip(ts, dates, strict=False):
            info = codes.get(code)
            if info is not None:
                info["rows"] += 1
                if info["max"] is None or str(date) > info["max"]:
                    info["max"] = str(date)
        return {"codes": codes,
                "columns": [c for c in ("up_limit", "down_limit") if c in names]}
    facts = _cached_scan(cache, f"etf-limits-{release['release_id']}", produce)
    for _code, info in facts["codes"].items():
        info["max"] = _iso(info["max"])
    facts.setdefault("columns", [])
    return facts


def artifact_tree(root, rel_dir, required=()):
    base = Path(root) / rel_dir
    if not base.is_dir():
        return None, [f"missing artifact dir {rel_dir}"]
    missing = [name for name in required if not (base / name).exists()]
    return base, ([f"missing {name}" for name in missing] if missing else [])


def cb_daily_max(base):
    days = sorted(p.stem for p in (base / "cb_daily").glob("*.parquet")) \
        if (base / "cb_daily").is_dir() else []
    return _iso(days[-1]) if days else None


def build_report(archive, artifact, cache):
    reasons = []
    market_release = _release_manifest(archive, "RESEARCH_CURRENT.json")
    fundamentals_release = _release_manifest(archive, "CURRENT.json")
    market = {"mode": "managed", "pointer_path": "RESEARCH_CURRENT.json"}
    fundamentals = {"mode": "managed", "pointer_path": "CURRENT.json"}
    for name, release, block in (("market", market_release, market),
                                 ("fundamentals", fundamentals_release, fundamentals)):
        if release["valid"]:
            block.update(release_id=release["release_id"],
                         manifest_path=_relative_under(
                             archive, release["manifest"]),
                         manifest_sha256=release["manifest_sha256"])
        else:
            block.update(release_id=release.get("release_id"),
                         manifest_path=None, manifest_sha256=None)
            reasons += [f"{name}: {r}" for r in release["reasons"]]

    cutoffs = api_cutoffs(archive, market_release, cache) \
        if market_release["valid"] else {}
    usable_date = None
    if market_release["valid"]:
        bars = [_iso_cutoff(cutoffs.get(api)) for api in BAR_APIS]
        bars = [d for d in bars if d]
        if bars:
            usable_date = min(bars)
        else:
            reasons.append("no bar api has row-level dates")

    calendar, calendar_reasons = calendar_info(archive, fundamentals_release, cache,
                                               usable_date) \
        if fundamentals_release["valid"] else ({"path": None, "sha256": None,
                                               "confirmed_next_session": None},
                                              ["fundamentals release invalid"])
    reasons += calendar_reasons

    etf = etf_limit_facts(archive, market_release, cache, usable_date) \
        if market_release["valid"] else {"codes": {}, "columns": []}
    etf_summary = {code: info["max"] for code, info in etf.get("codes", {}).items()}
    limits_ok = (all(info.get("rows", 0) > 0 for info in etf.get("codes", {}).values())
                 and {"up_limit", "down_limit"} <= set(etf.get("columns", []))
                 and all(info.get("max") and usable_date and info["max"] >= usable_date
                         for info in etf.get("codes", {}).values()))

    base_ok = bool(market_release["valid"] and fundamentals_release["valid"]
                   and usable_date)
    calendar_ok = calendar.get("confirmed_next_session") is not None

    # asset inputs (artifact-root relative)
    assets = {}
    etf_pending = ["normalized ETF parquet not yet produced (platform prepare-release pending)"]
    assets["i7_turn_of_month"] = {
        "state": "pending", "reasons": etf_pending + ["requires 510300.SH in normalized schema"],
        "path": None, "version": None, "manifest_path": None, "manifest_sha256": None}
    s1_reasons = list(etf_pending)
    if not limits_ok:
        s1_reasons.append(
            f"real stk_limit coverage insufficient (policy A: no ±10% inference; "
            f"per-code max {etf_summary}, limit columns {etf.get('columns', [])})")
    assets["s1_invvol_etf"] = {
        "state": "pending", "reasons": s1_reasons,
        "path": None, "version": None, "manifest_path": None, "manifest_sha256": None}

    cb_dir, cb_missing = artifact_tree(
        artifact, "ashare-takeover/trees/ashare-lab-ideas-cb/data/extra",
        ("cb_basic.parquet", "cb_call.parquet", "cb_daily"))
    if cb_dir is None:
        assets["cb_double_low"] = {"state": "blocked", "reasons": cb_missing,
                                   "path": None, "version": None,
                                   "manifest_path": None, "manifest_sha256": None}
    else:
        stale = cb_daily_max(cb_dir)
        cb_reasons = cb_missing + [
            f"cb_daily bars end {stale or 'unknown'} < usable {usable_date or 'unknown'}; "
            "incremental supplement owned by platform source"]
        assets["cb_double_low"] = {
            "state": "pending" if stale else "blocked", "reasons": cb_reasons,
            "path": "ashare-takeover/trees/ashare-lab-ideas-cb/data/extra",
            "version": f"cb_daily:{stale}", "manifest_path": None,
            "manifest_sha256": None}

    cta_dir, cta_missing = artifact_tree(
        artifact, "ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures",
        ("basic", "contracts", "mapping"))
    cta_reasons = cta_missing + [
        "fut_basic lacks multiplier field (fetch tool never requested it)",
        "commodity caches end 2026-09-30; unexpired contracts and current-month "
        "mapping plus real multiplier/settle supplement owned by platform source",
    ]
    assets["cta_combined"] = {
        "state": "blocked", "reasons": cta_reasons,
        "path": "ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures"
        if cta_dir else None,
        "version": None, "manifest_path": None, "manifest_sha256": None}
    assets["cta_trend"] = dict(assets["cta_combined"])

    # accounts: original three follow base+calendar; asset accounts mirror assets
    accounts = {}
    original_state, original_reasons = "ready", []
    if not base_ok:
        original_state = "blocked"
        original_reasons = [r for r in reasons if r]
    elif not calendar_ok:
        original_state = "pending"
        original_reasons = list(calendar_reasons)
    for name in ACCOUNTS[:3]:
        accounts[name] = {"state": original_state,
                          "reasons": list(original_reasons)}
    for name in ASSET_KEYS:
        accounts[name] = {"state": assets[name]["state"],
                          "reasons": list(assets[name]["reasons"])}

    report = {
        "schema_version": 1,
        "state": "ready" if base_ok else "blocked",
        "checked_at": _utcnow_iso(),
        "usable_date": usable_date,
        "reasons": reasons,
        "per_api_cutoffs": cutoffs,
        "market": market,
        "fundamentals": fundamentals,
        "calendar": calendar,
        "accounts": accounts,
        "asset_inputs": assets,
    }
    return report


def _iso_cutoff(value):
    if not value:
        return None
    text = str(value)
    return text if "-" in text else _iso(text)


def write_report(report, output):
    encoded = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True)
    for bad in ("/Users/", ".."):
        if bad in encoded:
            raise ValueError(f"contract violation: {bad!r} in report")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(encoded)
    temporary.replace(output)


def main():
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root",
                        default=str(home / "Library/Application Support/QuantMind/tushare"))
    parser.add_argument("--artifact-root",
                        default=str(home / "code/quantmind-aline/output"))
    parser.add_argument("--output",
                        default=str(home / "Library/Application Support/QuantMind"
                                    "/market-source/paper-readiness.json"))
    parser.add_argument("--cache", default=None,
                        help="defaults to <output dir>/paper-readiness-cache")
    args = parser.parse_args()
    archive, artifact, output = (Path(args.archive_root), Path(args.artifact_root),
                                 Path(args.output))
    cache = Path(args.cache) if args.cache else output.parent / "paper-readiness-cache"
    report = build_report(archive, artifact, cache)
    write_report(report, output)
    summary = {"output": str(output), "state": report["state"],
               "usable_date": report["usable_date"],
               "calendar_next": report["calendar"]["confirmed_next_session"],
               "accounts": {k: v["state"] for k, v in report["accounts"].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
