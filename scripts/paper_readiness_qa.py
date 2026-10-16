#!/usr/bin/env python3
"""Sole producer of paper-readiness v1 (contract: quantmind-aline backend/README.md
`唯一日更契约：paper-readiness v1`).

Reads the managed Tushare archive and the delivered input supplements
(ashare-input-supplements/<epoch>/asset-evidence.json, schema agreed with the
platform source executor) strictly read-only. Every readiness decision comes
from independently re-verified facts -- file byte hashes against the delivered
manifest, row-level dates from real parquet rows (never file names or mtime,
never declared values) -- so states move with the data, not with hardcoded
copy. Writes the JSON consumed by the paper tick; never issues vendor requests
and never writes inside the archive or artifact roots.

All emitted paths are relative to the two contract roots (archive-root,
artifact-root); no absolute host paths, no `..` escapes. The artifact root is
resolved explicitly (CLI, ASHARE_PAPER_ARTIFACT_ROOT, or the deployment marker
under market-source); there is no built-in candidate-worktree default.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.compute as pc

try:  # shared native manifest iterator; deployed alongside in the scripts tree
    from ashare_input_supplements import datasets as _native_datasets
except ImportError as exc:  # pragma: no cover - deployment guard
    raise SystemExit(
        "ashare_input_supplements not importable; set PYTHONPATH to the "
        "deployed scripts directory (shared datasets() iterator)") from exc
CONSUMABLE_QUALITY_STATES = ("sample_ok", "schema_gap", "possibly_truncated")

ACCOUNTS = ("lowvol", "b2_lowvol_vt", "b3_lqv_buf_vt", "i7_turn_of_month",
            "s1_invvol_etf", "cb_double_low", "cta_combined", "cta_trend")
ASSET_KEYS = ("i7_turn_of_month", "s1_invvol_etf", "cb_double_low",
              "cta_combined", "cta_trend")
BAR_APIS = ("daily", "daily_basic", "adj_factor", "fund_daily", "index_daily",
            "stk_limit")
DIMENSION_APIS = ("fund_basic", "index_basic", "index_classify",
                  "index_member_all", "stock_basic", "sw_daily")
RESEARCH_APIS = BAR_APIS + DIMENSION_APIS + ("ci_daily", "etf_limit", "moneyflow",
                                             "suspend_d", "trade_cal", "index_weight")
ETF_LIMIT_CODES = ("510300.SH", "511010.SH", "518880.SH")
ETF_COLUMNS = ("date", "code", "open", "close", "adj", "amount", "volume",
               "up_limit", "down_limit")
EVIDENCE_REL = "ashare-input-supplements"
MARKER_ENV = "ASHARE_PAPER_ARTIFACT_ROOT"


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _relative_under(root, path):
    rel = Path(path).resolve().relative_to(Path(root).resolve())
    text = rel.as_posix()
    if text.startswith("/") or ".." in text.split("/"):
        raise ValueError(f"path escapes root: {text}")
    return text


def _iso(value):
    if not value:
        return None
    text = str(value)
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text


def _compact(iso_value):
    return str(iso_value).replace("-", "") if iso_value else ""


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


def dataset_paths(archive, release, cache, api):
    """Archive-relative dataset paths for one api, built once per release from
    the shared native datasets() iterator and cached. Entries whose
    quality_state is not consumable are rejected, per contract; the full
    manifest SHA is verified separately by the release pointer check."""
    def build():
        entries = {}
        for item in _native_datasets(release["manifest"]):
            entries.setdefault(item.get("api_name"), []).append(
                {"path": item.get("path"),
                 "quality_state": item.get("quality_state")})
        return {"entries": entries}
    payload = _cached_scan(cache, f"datasets2-{release['release_id']}", build)
    return [archive / entry["path"]
            for entry in payload["entries"].get(api, [])
            if entry.get("quality_state") in CONSUMABLE_QUALITY_STATES
            and (archive / entry["path"]).is_file()]


def api_cutoffs(archive, release, cache):
    results = _cached_scan(
        cache, f"cutoffs-{release['release_id']}",
        lambda: {api: _row_extremes(dataset_paths(archive, release, cache, api))
                 for api in RESEARCH_APIS})
    cutoffs = {}
    for api, info in results.items():
        cutoffs[api] = _iso(info.get("max")) if info and info.get("date_col") else None
    return cutoffs


def _calendar_open_days(files):
    days = set()
    for path in files:
        dataset = ds.dataset([path], format="parquet")
        names = dataset.schema.names
        if "cal_date" not in names or "is_open" not in names:
            continue
        table = dataset.to_table(columns=["cal_date", "is_open"])
        days.update(str(d) for d, o in zip(table.column("cal_date").to_pylist(),
                                           table.column("is_open").to_pylist(),
                                           strict=False) if o == 1)
    return sorted(days)


def _next_session(open_days, usable_date):
    compact = _compact(usable_date)
    if not compact:
        return None
    for day in open_days:
        if day > compact:
            return _iso(day)
    return None


def calendar_from_candidates(archive, candidates, usable_date):
    """Verify each delivered calendar candidate from its real rows; accept the
    first whose sha256 matches and whose rows confirm a session after usable."""
    for candidate in candidates or []:
        rel = candidate.get("path") or ""
        if ".." in rel.split("/"):
            continue
        path = archive / rel
        if not path.is_file():
            continue
        if candidate.get("sha256") and _sha256_file(path) != candidate["sha256"]:
            continue
        nxt = _next_session(_calendar_open_days([path]), usable_date)
        if nxt:
            return {"path": rel, "sha256": _sha256_file(path),
                    "confirmed_next_session": nxt}, []
    return ({"path": None, "sha256": None, "confirmed_next_session": None},
            ["no verified calendar candidate confirms a session after usable_date"])


def calendar_from_release(archive, fundamentals, cache, usable_date):
    files = dataset_paths(archive, fundamentals, cache, "trade_cal")
    days = _cached_scan(
        cache, f"calendar2-{fundamentals['release_id']}",
        lambda: {"open_days": [d for d in _calendar_open_days(files)
                               if d >= "20200101"]})["open_days"]
    best = None
    for path in files:
        best = str(path)
        break
    nxt = _next_session(days, usable_date)
    entry = {"path": _relative_under(archive, best) if best else None,
             "sha256": _sha256_file(best) if best else None,
             "confirmed_next_session": nxt}
    reasons = [] if nxt else [
        "trade_cal in current releases ends before the next session after "
        "usable_date; awaiting the delivered future-calendar supplement"]
    return entry, reasons


def etf_limit_facts(archive, release, cache):
    def produce():
        codes = {code: {"rows": 0, "max": None} for code in ETF_LIMIT_CODES}
        columns = []
        for api in ("etf_limit", "stk_limit"):
            files = dataset_paths(archive, release, cache, api)
            if not files:
                continue
            dataset = ds.dataset(files, format="parquet")
            names = dataset.schema.names
            if "ts_code" not in names or "trade_date" not in names:
                continue
            wanted = ["ts_code", "trade_date"] + [c for c in ("up_limit", "down_limit")
                                                  if c in names]
            table = dataset.to_table(
                columns=wanted,
                filter=ds.field("ts_code").isin(list(ETF_LIMIT_CODES)))
            for code, date in zip(table.column("ts_code").to_pylist(),
                                  table.column("trade_date").to_pylist(),
                                  strict=False):
                info = codes.get(code)
                if info is not None:
                    info["rows"] += 1
                    if info["max"] is None or str(date) > info["max"]:
                        info["max"] = str(date)
            columns = [c for c in ("up_limit", "down_limit") if c in names]
            if all(v["rows"] for v in codes.values()):
                break
        return {"codes": codes, "columns": columns}
    facts = _cached_scan(cache, f"etf-limits2-{release['release_id']}", produce)
    for info in facts["codes"].values():
        info["max"] = _iso(info["max"])
    return facts


def load_evidence(artifact):
    base = artifact / EVIDENCE_REL
    if not base.is_dir():
        return None, [f"no {EVIDENCE_REL}/ delivery under artifact root"]
    latest = sorted(p for p in base.iterdir() if p.is_dir())
    if not latest:
        return None, [f"no epoch directory under {EVIDENCE_REL}/"]
    epoch = latest[-1]
    evidence = epoch / "asset-evidence.json"
    if not evidence.is_file():
        return None, [f"delivery epoch {epoch.name} has no asset-evidence.json yet "
                      "(supplement in progress)"]
    return json.loads(evidence.read_bytes()), []


def _verify_entry(artifact, entry):
    """Byte-verify a delivered input against its manifest; returns reasons."""
    reasons = []
    manifest_path = artifact / entry.get("manifest_path", "")
    if not entry.get("manifest_path") or not manifest_path.is_file():
        return ["manifest missing at delivered manifest_path"]
    if entry.get("manifest_sha256") != _sha256_file(manifest_path):
        return ["manifest sha256 mismatch"]
    manifest = json.loads(manifest_path.read_bytes())
    files = manifest.get("files", {})
    rel = entry.get("path")
    if not rel:
        return ["delivered entry has no path"]
    target = artifact / rel
    if not target.exists():
        return [f"delivered path missing: {rel}"]
    if target.is_file():
        spec = files.get(rel)
        if not spec:
            reasons.append(f"{rel} not declared in manifest files")
        else:
            if spec.get("bytes") is not None and spec["bytes"] != target.stat().st_size:
                reasons.append(f"{rel} byte size mismatch")
            if spec.get("sha256") and spec["sha256"] != _sha256_file(target):
                reasons.append(f"{rel} sha256 mismatch")
    else:
        declared = sum(1 for key in files if key.startswith(f"{rel}/"))
        if declared == 0:
            reasons.append(f"no manifest-declared files under {rel}/")
    return reasons


def _parquet_table(path_or_files, columns=None):
    dataset = ds.dataset([str(p) for p in path_or_files], format="parquet")
    return dataset.to_table(columns=columns) if columns else dataset.to_table()


def verify_etf_asset(artifact, rel, usable_date, required_codes):
    path = artifact / rel
    table = _parquet_table([path])
    names = set(table.schema.names)
    missing_cols = [c for c in ETF_COLUMNS if c not in names]
    reasons = [f"normalized parquet missing columns {missing_cols}"] if missing_cols else []
    codes = table.column("code").to_pylist()
    dates = table.column("date").to_pylist()
    if "up_limit" in names and "down_limit" in names:
        ups = table.column("up_limit").to_pylist()
        downs = table.column("down_limit").to_pylist()
    else:
        ups = downs = [None] * len(codes)
    compact_usable = _compact(usable_date)
    per_code = {code: {"rows": 0, "last": None} for code in required_codes}
    execution_missing = 0
    for code, date, up, down in zip(codes, dates, ups, downs, strict=False):
        info = per_code.get(code)
        if info is None:
            continue
        info["rows"] += 1
        day = _compact(str(date))
        if day > (info["last"] or ""):
            info["last"] = day
        if compact_usable and day >= compact_usable and (up is None or down is None):
            execution_missing += 1
    for code, info in per_code.items():
        if info["rows"] == 0:
            reasons.append(f"{code} absent from normalized parquet")
        elif usable_date and (info["last"] or "") < compact_usable:
            reasons.append(f"{code} rows end {info['last']} before usable {usable_date}")
    if execution_missing:
        reasons.append(f"{execution_missing} rows at/after usable_date lack real "
                       "up_limit/down_limit")
    return reasons, per_code


def verify_cta_asset(artifact, rel):
    root = artifact / rel
    reasons = []
    # Real consumer shape: basic.parquet, mapping.parquet and
    # contracts/<ts_code>.parquet files; basic must cover the actual running
    # contract set with real multipliers, not merely exist.
    basic = root / "basic.parquet"
    mapping = root / "mapping.parquet"
    contracts_dir = root / "contracts"
    if not basic.is_file():
        return ["basic.parquet missing under delivered root"], None
    if not mapping.is_file():
        reasons.append("mapping.parquet missing under delivered root")
    if not contracts_dir.is_dir():
        reasons.append("contracts/ directory missing under delivered root")
        return reasons, None
    contract_files = sorted(contracts_dir.glob("*.parquet"))
    if not contract_files:
        reasons.append("no contract daily parquet under contracts/")
        return reasons, None
    table = _parquet_table([basic])
    names = set(table.schema.names)
    if "multiplier" not in names:
        reasons.append("multiplier column missing from basic.parquet")
    else:
        rows = dict(zip(table.column("ts_code").to_pylist(),
                        table.column("multiplier").to_pylist(), strict=False))
        missing = [code for code in rows if rows[code] is None or rows[code] <= 0]
        if missing:
            reasons.append(f"{len(missing)} basic rows lack a positive multiplier")
        uncovered = [path.stem for path in contract_files
                     if not any(code == path.stem or code.startswith(path.stem + ".")
                                for code in rows)]
        if uncovered:
            reasons.append(f"running contracts without basic multiplier coverage: "
                           f"{uncovered[:5]}")
    tail = _row_extremes(contract_files[-20:])
    actual_max = _iso(tail.get("max")) if tail else None
    settle_table = _parquet_table(contract_files[-5:])
    if "settle" not in settle_table.schema.names:
        reasons.append("settle column missing from contract dailies")
    else:
        nulls = sum(1 for v in settle_table.column("settle").to_pylist() if v is None)
        if nulls:
            reasons.append(f"{nulls} recent settle values null")
    return reasons, actual_max


def verify_cb_asset(artifact, rel, usable_date):
    root = artifact / rel
    reasons = []
    if not (root / "cb_daily").is_dir():
        return ["cb_daily directory missing"], None
    files = sorted((root / "cb_daily").glob("*.parquet"))
    if not files:
        return ["cb_daily has no parquet files"], None
    # Row-level truth from the most recent files only; file names are never
    # treated as data dates.
    latest_rows = _row_extremes(files[-10:])
    actual_max = _iso(latest_rows.get("max")) if latest_rows else None
    if usable_date and (not actual_max or actual_max < usable_date):
        reasons.append(f"cb_daily row-level max trade_date {actual_max} < usable "
                       f"{usable_date}")
    table = _parquet_table([files[-1]])
    if "cb_over_rate" not in table.schema.names:
        reasons.append("cb_over_rate column missing")
    return reasons, actual_max


def asset_inputs(artifact, evidence, usable_date):
    assets = {}
    if evidence is None:
        reason = "delivered input supplements not yet present under artifact root"
        for key in ASSET_KEYS:
            assets[key] = {"state": "pending", "reasons": [reason],
                           "path": None, "version": None,
                           "manifest_path": None, "manifest_sha256": None}
        return assets
    inputs = evidence.get("inputs", {})
    errors = evidence.get("errors", {})
    for key in ASSET_KEYS:
        entry = inputs.get(key)
        if entry is None:
            assets[key] = {"state": "blocked",
                           "reasons": [f"source reported: {errors.get(key, 'not delivered')}"],
                           "path": None, "version": None,
                           "manifest_path": None, "manifest_sha256": None}
            continue
        reasons = _verify_entry(artifact, entry)
        notes = []
        rel = entry.get("path")
        if key in ("i7_turn_of_month", "s1_invvol_etf") and not reasons:
            required = ("510300.SH",) if key == "i7_turn_of_month" else ETF_LIMIT_CODES
            etf_reasons, _ = verify_etf_asset(artifact, rel, usable_date, required)
            reasons += etf_reasons
            if not reasons:
                details = _manifest_details(artifact, entry)
                if details is not None and details.get(
                        "cash_dividend_history_verified") is False:
                    # Informational only: unverified dividend events are not
                    # evidence of "no dividend"; the panel keeps adj handling.
                    notes.append(
                        "note: source reports cash dividend history not yet "
                        "verified (unverified events are not no-dividend proof)")
        elif key == "cb_double_low" and not reasons:
            cb_reasons, actual = verify_cb_asset(artifact, rel, usable_date)
            reasons += cb_reasons
        elif key in ("cta_combined", "cta_trend") and not reasons:
            cta_reasons, _actual = verify_cta_asset(artifact, rel)
            reasons += cta_reasons
        assets[key] = {"state": "ready" if not reasons else "blocked",
                       "reasons": reasons + notes,
                       "path": rel, "version": entry.get("version"),
                       "manifest_path": entry.get("manifest_path"),
                       "manifest_sha256": entry.get("manifest_sha256")}
    return assets


def _manifest_details(artifact, entry):
    path = artifact / (entry.get("manifest_path") or "")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_bytes()).get("details")
    except ValueError:
        return None


def resolve_artifact_root(explicit=None):
    if explicit:
        return Path(explicit), None
    env = os.environ.get(MARKER_ENV)
    if env:
        return Path(env), None
    marker = (Path.home() / "Library/Application Support/QuantMind"
              "/market-source/paper-artifact-root")
    if marker.is_file():
        return Path(marker.read_text().strip()), None
    return None, (f"artifact root unresolved: pass --artifact-root, set "
                  f"{MARKER_ENV}, or deploy the market-source marker file")


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
                         manifest_path=_relative_under(archive, release["manifest"]),
                         manifest_sha256=release["manifest_sha256"])
        else:
            block.update(release_id=release.get("release_id"),
                         manifest_path=None, manifest_sha256=None)
            reasons += [f"{name}: {r}" for r in release["reasons"]]

    cutoffs = api_cutoffs(archive, market_release, cache) \
        if market_release["valid"] else {}
    usable_date = None
    missing_bars = [api for api in BAR_APIS if not cutoffs.get(api)]
    if market_release["valid"]:
        if missing_bars:
            reasons.append(f"required bar apis missing row-level dates: {missing_bars}")
        else:
            usable_date = min(cutoffs[api] for api in BAR_APIS)

    evidence, evidence_reasons = load_evidence(artifact) if artifact else (None, [
        "artifact root unresolved; cannot read delivered input supplements"])
    reasons += evidence_reasons

    if evidence and evidence.get("calendar_candidates"):
        calendar, calendar_reasons = calendar_from_candidates(
            archive, evidence.get("calendar_candidates"), usable_date)
    elif fundamentals_release["valid"]:
        calendar, calendar_reasons = calendar_from_release(
            archive, fundamentals_release, cache, usable_date)
    else:
        calendar = {"path": None, "sha256": None, "confirmed_next_session": None}
        calendar_reasons = ["fundamentals release invalid"]
    reasons += calendar_reasons

    base_ok = bool(market_release["valid"] and fundamentals_release["valid"]
                   and usable_date)
    calendar_ok = calendar.get("confirmed_next_session") is not None

    assets = asset_inputs(artifact, evidence, usable_date)
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

    return {
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


def write_report(report, output):
    encoded = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True)
    for bad in ("/Users/", ".."):
        if bad in encoded:
            raise ValueError(f"contract violation: {bad!r} in report")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(encoded)
    temporary.replace(output)


def main(argv=None):
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root",
                        default=str(home / "Library/Application Support/QuantMind/tushare"))
    parser.add_argument("--artifact-root", default=None)
    parser.add_argument("--output",
                        default=str(home / "Library/Application Support/QuantMind"
                                    "/market-source/paper-readiness.json"))
    parser.add_argument("--cache", default=None,
                        help="defaults to <output dir>/paper-readiness-cache")
    args = parser.parse_args(argv)
    archive = Path(args.archive_root)
    output = Path(args.output)
    cache = Path(args.cache) if args.cache else output.parent / "paper-readiness-cache"
    artifact, root_reason = resolve_artifact_root(args.artifact_root)
    report = build_report(archive, artifact, cache)
    if root_reason:
        report["reasons"].append(root_reason)
    write_report(report, output)
    summary = {"output": str(output), "state": report["state"],
               "usable_date": report["usable_date"],
               "calendar_next": report["calendar"]["confirmed_next_session"],
               "accounts": {k: v["state"] for k, v in report["accounts"].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
