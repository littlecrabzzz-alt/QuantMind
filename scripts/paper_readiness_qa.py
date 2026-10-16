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
# The base research whitelist of exactly 18 apis (RESEARCH_CURRENT
# selected_api_names); etf_limit is a supplement, not part of the base 18.
RESEARCH_APIS = BAR_APIS + DIMENSION_APIS + ("ci_daily", "fund_adj", "moneyflow",
                                             "suspend_d", "trade_cal", "index_weight")
ETF_LIMIT_CODES = ("510300.SH", "511010.SH", "518880.SH")
ETF_COLUMNS = ("date", "code", "open", "close", "adj", "amount", "volume",
               "up_limit", "down_limit")
EVIDENCE_REL = "ashare-input-supplements"
# Parent-frozen I7 replay start (runtime prepare_release default), not a
# guess; a delivered evidence value still overrides this default.
REPLAY_START_DEFAULT = "2026-10-14"
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
        cache, f"cutoffs2-{release['release_id']}",
        lambda: {api: _row_extremes(dataset_paths(archive, release, cache, api))
                 for api in RESEARCH_APIS})
    cutoffs = {}
    for api, info in results.items():
        cutoffs[api] = _iso(info.get("max")) if info and info.get("date_col") else None
    return cutoffs


def _calendar_open_days(files):
    return _calendar_days(files)["open"]


def _calendar_days(files):
    """Open days plus the calendar's real coverage through-day (closed days
    count as coverage: a month is complete only if the calendar spans past
    its month end, which closed days prove as well as open ones)."""
    days, through, day_map, duplicates = set(), None, {}, 0
    for path in files:
        dataset = ds.dataset([path], format="parquet")
        names = dataset.schema.names
        date_col = next((c for c in ("cal_date", "date") if c in names), None)
        if date_col is None or "is_open" not in names:
            continue
        columns = [date_col, "is_open"] + (
            ["exchange"] if "exchange" in names else [])
        table = dataset.to_table(columns=columns)
        exchanges = (table.column("exchange").to_pylist()
                     if "exchange" in names else [None] * table.num_rows)
        for day, is_open, exchange in zip(table.column(date_col).to_pylist(),
                                          table.column("is_open").to_pylist(),
                                          exchanges, strict=False):
            if exchange not in (None, "SSE"):
                continue
            day = str(day).replace("-", "")  # DATE objects render dashed
            through = day if through is None or day > through else through
            if day in day_map:
                duplicates += 1
            day_map[day] = is_open
            if is_open == 1:
                days.add(day)
    return {"open": sorted(days), "through": through,
            "day_map": day_map, "duplicates": duplicates}


def _next_session(open_days, usable_date):
    compact = _compact(usable_date)
    if not compact:
        return None
    for day in open_days:
        if day > compact:
            return _iso(day)
    return None


def _month_end(day):
    import calendar
    year, month = int(day[:4]), int(day[4:6])
    return f"{year:04d}{month:02d}{calendar.monthrange(year, month)[1]:02d}"


def _next_day(day):
    import datetime as _dt
    return (_dt.date(int(day[:4]), int(day[4:6]), int(day[6:8]))
            + _dt.timedelta(days=1)).strftime("%Y%m%d")


def _month_facts(open_days, through, source_sha256, usable_date, day_map=None,
                 duplicates=0, replay_start=None):
    """Shared calendar_context proof (PaperLedger I7 contract): real SSE rows
    including closed days. I7 needs every natural day from the replay_start
    month's first to the usable month's end present exactly once, the next
    month's first session with day-by-day coverage, and two real opens after
    usable (frozen TOM needs i+2). No weekday generation."""
    day_map = day_map or {}
    month = _compact(usable_date)[:6] if usable_date else ""
    after_usable = [d for d in open_days if _compact(usable_date) and d > _compact(usable_date)]
    after_month = [d for d in open_days if month and d[:6] > month]
    complete, reason = False, None
    if not usable_date:
        reason = "usable_date missing"
    elif not after_month:
        reason = (f"calendar covers only through {_iso(through)}; the usable "
                  f"month {month} is not fully covered plus next-month open")
    elif replay_start is None:
        reason = ("replay_start not provided in the delivered evidence; the "
                  "I7 month-coverage proof cannot start without it")
    else:
        start = _compact(replay_start)[:6] + "01"
        end = _next_day(_month_end(_compact(usable_date)))
        end = min(end, _next_day(through)) if through else end
        cursor, missing = start, []
        while cursor < end:
            if cursor not in day_map:
                missing.append(cursor)
            cursor = _next_day(cursor)
        # November prefix: every natural day from the next month's first to
        # its first open session must also carry a real row.
        if after_month:
            cursor = after_month[0][:6] + "01"
            while cursor <= after_month[0]:
                if cursor not in day_map:
                    missing.append(cursor)
                cursor = _next_day(cursor)
        if duplicates:
            reason = f"{duplicates} duplicate calendar rows for SSE days"
        elif missing:
            reason = (f"{len(missing)} natural days lack a real SSE calendar "
                      f"row (first missing {_iso(missing[0])})")
        elif len(after_usable) < 2:
            reason = "fewer than two real opens after usable_date (frozen TOM needs i+2)"
        else:
            complete = True
    return {"calendar_context": {
        "exchange": "SSE",
        "replay_start": replay_start,
        "usable_date": usable_date,
        "calendar_through": _iso(through),
        "required_month_end": _iso(_month_end(_compact(usable_date)))
        if usable_date else None,
        "next_month_first_session": _iso(after_month[0]) if after_month else None,
        "next_two_sessions": [_iso(d) for d in after_usable[:2]],
        "complete": complete,
        "state": "ready" if complete else "pending",
        "reason": reason,
        "calendar_sha256": source_sha256,
    }}


def _scan_facts(days_scan, sha):
    return {"open": days_scan["open"], "through": days_scan.get("through"),
            "day_map": days_scan.get("day_map", {}),
            "duplicates": days_scan.get("duplicates", 0), "sha": sha}


def _verify_closure(archive, candidate):
    """Verify the merged calendar's source closure sidecar bytes+sha."""
    rel = candidate.get("source_closure_path") or ""
    if not rel:
        return None
    if ".." in rel.split("/"):
        return ["closure path escapes the archive root"]
    path = archive / rel
    if not path.is_file():
        return [f"closure sidecar missing: {rel}"]
    reasons = []
    if candidate.get("source_closure_sha256") and \
            _sha256_file(path) != candidate["source_closure_sha256"]:
        reasons.append("closure sidecar sha256 mismatch")
    if (candidate.get("source_closure_bytes") is not None
            and path.stat().st_size != candidate["source_closure_bytes"]):
        reasons.append("closure sidecar byte size mismatch")
    return reasons


def calendar_from_candidates(archive, candidates, usable_date):
    """Verify calendar candidates from real rows (sha256 + row-level days).

    A candidate carrying source_closure fields is the canonical merged
    calendar: it is verified exclusively (bytes, closure sidecar, and an
    independent duplicate-day check that must agree with the declared merge
    having zero conflicts). Otherwise -- legacy lists -- the longest actual
    coverage wins, never a max_date single shard.
    """
    best = None
    for candidate in candidates or []:
        rel = candidate.get("path") or ""
        if ".." in rel.split("/"):
            continue
        path = archive / rel
        if not path.is_file():
            continue
        if candidate.get("sha256") and _sha256_file(path) != candidate["sha256"]:
            continue
        closure_reasons = _verify_closure(archive, candidate)
        facts = _calendar_days([path])
        nxt = _next_session(facts["open"], usable_date)
        if candidate.get("source_closure_path"):
            # canonical merged calendar: verify exclusively and independently
            reasons = list(closure_reasons or [])
            if facts.get("duplicates"):
                reasons.append(
                    f"{facts['duplicates']} duplicate (exchange, cal_date) rows "
                    f"in the merged calendar contradict the zero-conflict merge")
            if not nxt:
                reasons.append("merged calendar does not confirm the next "
                               "session after usable_date")
            entry = {"path": rel, "sha256": _sha256_file(path),
                     "confirmed_next_session": nxt}
            if reasons:
                return entry, reasons, _scan_facts(facts, entry["sha256"])
            return entry, [], _scan_facts(facts, entry["sha256"])
        if not nxt:
            continue
        entry = {"path": rel, "sha256": _sha256_file(path),
                 "confirmed_next_session": nxt}
        if best is None or (facts.get("through") or "") > (best[2]["through"] or ""):
            best = (entry, [], _scan_facts(facts, entry["sha256"]))
    if best:
        return best
    return ({"path": None, "sha256": None, "confirmed_next_session": None},
            ["no verified calendar candidate confirms a session after usable_date"],
            {"open": [], "through": None, "day_map": {}, "duplicates": 0,
             "sha": None})


def calendar_from_release(archive, fundamentals, cache, usable_date):
    files = dataset_paths(archive, fundamentals, cache, "trade_cal")
    scan = _cached_scan(
        cache, f"calendar4-{fundamentals['release_id']}",
        lambda: {k: ([d for d in v if d >= "20200101"]
                     if isinstance(v, list) else v)
                 for k, v in _calendar_days(files).items()})
    facts = scan
    best = None
    for path in files:
        best = str(path)
        break
    nxt = _next_session(facts["open"], usable_date)
    entry = {"path": _relative_under(archive, best) if best else None,
             "sha256": _sha256_file(best) if best else None,
             "confirmed_next_session": nxt}
    reasons = [] if nxt else [
        "trade_cal in current releases ends before the next session after "
        "usable_date; awaiting the delivered future-calendar supplement"]
    return entry, reasons, _scan_facts(facts, entry["sha256"])


def load_evidence(artifact):
    """Read ONLY the canonical supplement pointer (clean cutover contract):
    ashare-input-supplements/CURRENT.json = {schema_version, data_identity,
    bundle_path, bundle_sha256}; the bundle bytes must match the recorded
    sha256. A missing pointer means pending -- no directory scanning, no
    newest-glob, no legacy epoch fallback. Returns (evidence, reasons,
    binding) where binding is the verified pointer identity for transparent
    passthrough, or None when unverified."""
    binding = None
    if artifact is None:
        return None, ["artifact root unresolved"], None
    pointer = artifact / EVIDENCE_REL / "CURRENT.json"
    if not pointer.is_file():
        return None, ["canonical supplement pointer CURRENT.json missing "
                      "(pending; source publishes it only after verification)"], None
    try:
        spec = json.loads(pointer.read_bytes())
    except ValueError:
        return None, ["canonical supplement pointer unreadable"], None
    if spec.get("schema_version") != 1:
        return None, [f"unsupported pointer schema_version "
                      f"{spec.get('schema_version')!r}"], None
    rel = spec.get("bundle_path") or ""
    if ".." in rel.split("/"):
        return None, ["pointer bundle_path escapes the artifact root"], None
    bundle = artifact / rel
    if not bundle.is_file():
        return None, [f"pointer bundle missing: {rel}"], None
    if spec.get("bundle_sha256") and _sha256_file(bundle) != spec["bundle_sha256"]:
        return None, ["bundle sha256 mismatch against the canonical pointer"], None
    binding = {"pointer_path": f"{EVIDENCE_REL}/CURRENT.json",
               "schema_version": spec.get("schema_version"),
               "data_identity": spec.get("data_identity"),
               "bundle_path": rel,
               "bundle_sha256": spec.get("bundle_sha256")}
    return json.loads(bundle.read_bytes()).get("evidence"), [], binding


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


def _required_contracts(root, contract_files=()):
    """Delivered running contracts (every quotes file) plus mapping-linked
    codes form the required closure: if the source ships quotes for a
    contract, its normalized multiplier and unit evidence must exist -- an
    unknown-unit contract stays blocked for the source normalizer to resolve,
    never substituted or guessed."""
    mapping = root / "mapping.parquet"
    if not mapping.is_file():
        return set()
    table = _parquet_table([mapping])
    names = set(table.schema.names)
    if "ts_code" not in names:
        return set()
    dates = table.column("trade_date").to_pylist() \
        if "trade_date" in names else ["99991231"] * table.num_rows
    floor = _compact(str(_utcnow_iso()[:10]))
    # recent window: the last month of mapping rows
    recent = max(str(d) for d in dates if d)
    floor = recent[:6] + "01" if recent else "00000000"
    required = set()
    for i, day in enumerate(dates):
        if str(day) >= floor:
            for col in ("ts_code", "mapping_ts_code", "source_ts_code"):
                if col in names:
                    value = table.column(col).to_pylist()[i]
                    # product-level codes (AG.SHF) carry no per-contract
                    # multiplier by design; only real contract codes (digits)
                    # join the required closure.
                    if value and any(ch.isdigit() for ch in value.split(".")[0]):
                        required.add(value)
    return required


def verify_cta_asset(artifact, rel):
    root = artifact / rel
    reasons = []
    notes_extra = []
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
    # Official doc: raw fut_basic.multiplier exists only for treasury/index
    # futures; commodity NULL is normal. The delivered basic carries the
    # canonical normalized_multiplier with per-contract unit evidence; QA
    # verifies positive values and unit evidence for the REQUIRED closure
    # (mapping-linked running contracts), not for every historical row.
    mult_col = next((c for c in ("normalized_multiplier", "multiplier",
                                 "nominal_multiplier") if c in names), None)
    unit_cols = [c for c in ("per_unit", "trade_unit", "quote_unit") if c in names]
    if mult_col is None:
        reasons.append("normalized multiplier column missing from basic.parquet")
        rows = {}
    else:
        rows = dict(zip(table.column("ts_code").to_pylist(),
                        table.column(mult_col).to_pylist(), strict=False))
    mapping_required = _required_contracts(root)
    evidence_required, unneeded_gaps = _unit_evidence_closure(root)

    def covered(code):
        return any((row == code or row.startswith(code + "."))
                   and value is not None and value > 0
                   for row, value in rows.items())
    closure = mapping_required | evidence_required
    bad = sorted(code for code in closure
                 if code not in rows or rows[code] is None or rows[code] <= 0)
    if unneeded_gaps:
        notes_extra.append(
            f"{len(unneeded_gaps)} delivered contracts outside the required "
            f"closure lack unit provenance (source-marked not required, e.g. "
            f"{sorted(unneeded_gaps)[:2]}); no values were guessed")
    if bad:
        reasons.append(
            f"{len(bad)} required (mapping-linked) contracts lack a positive "
            f"normalized multiplier: {bad[:5]} (raw commodity multiplier NULL "
            f"is normal and is not a gap)")
    if unit_cols and mult_col:
        unit_rows = dict(zip(table.column("ts_code").to_pylist(),
                             [tuple(v) for v in zip(
                                 *(table.column(c).to_pylist()
                                   for c in unit_cols), strict=False)],
                             strict=False))
        missing_units = sorted(
            code for code in closure
            if code in unit_rows and any(v is None for v in unit_rows[code]))
        if missing_units:
            reasons.append(f"{len(missing_units)} required contracts lack unit "
                           f"evidence ({', '.join(unit_cols)}): {missing_units[:5]}")
    uncovered = []
    if uncovered:
        reasons.append(f"required running contracts without normalized "
                       f"multiplier coverage: {uncovered[:5]}")
    tail = _row_extremes(contract_files[-20:])
    actual_max = _iso(tail.get("max")) if tail else None
    settle_table = _parquet_table(contract_files[-5:])
    if "settle" not in settle_table.schema.names:
        reasons.append("settle column missing from contract dailies")
    else:
        nulls = sum(1 for v in settle_table.column("settle").to_pylist() if v is None)
        if nulls:
            reasons.append(f"{nulls} recent settle values null")
    return reasons, actual_max, notes_extra


def _unit_evidence_closure(root):
    """Per-contract required flags from the delivered unit evidence: the 370
    warmup/anchor/replay closure is the authoritative requirement set;
    delivered-but-unrequired historical contracts surface as notes only."""
    path = root / "contract-unit-evidence.json"
    if not path.is_file():
        return set(), set()
    try:
        body = json.loads(path.read_bytes())
    except ValueError:
        return set(), set()
    contracts = body.get("contracts") or {}
    required = {code for code, entry in contracts.items()
                if isinstance(entry, dict)
                and entry.get("required_for_window") is True}
    unneeded = {code for code, entry in contracts.items()
                if isinstance(entry, dict)
                and entry.get("required_for_window") is not True
                and entry.get("blocked_reason")}
    return required, unneeded


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
            cta_reasons, _actual, cta_notes = verify_cta_asset(artifact, rel)
            reasons += cta_reasons
            notes += cta_notes
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

    evidence, evidence_reasons, asset_bundle = load_evidence(artifact)
    reasons += evidence_reasons

    # Verified calendar candidates and the release trade_cal both carry real
    # rows; take the one with the longest actual coverage (through-day) so a
    # short candidate never hides a longer verified calendar.
    options = []
    if evidence and evidence.get("calendar_candidates"):
        options.append(calendar_from_candidates(
            archive, evidence.get("calendar_candidates"), usable_date))
    if fundamentals_release["valid"]:
        options.append(calendar_from_release(
            archive, fundamentals_release, cache, usable_date))
    if options:
        confirmed = [o for o in options if o[0]["confirmed_next_session"]]
        best = max(confirmed or options,
                   key=lambda o: o[2]["through"] or "")
        calendar, calendar_reasons, scan = best
    else:
        calendar = {"path": None, "sha256": None, "confirmed_next_session": None}
        calendar_reasons = ["fundamentals release invalid"]
        scan = {"open": [], "through": None, "day_map": {}, "duplicates": 0,
                "sha": None}
    reasons += calendar_reasons

    base_ok = bool(market_release["valid"] and fundamentals_release["valid"]
                   and usable_date)
    calendar_ok = calendar.get("confirmed_next_session") is not None

    assets = asset_inputs(artifact, evidence, usable_date)
    i7_entry = (evidence or {}).get("inputs", {}).get("i7_turn_of_month", {})
    replay_start = (i7_entry.get("evidence") or {}).get("replay_start") \
        or REPLAY_START_DEFAULT
    month = _month_facts(scan["open"], scan["through"], scan["sha"],
                         usable_date, day_map=scan["day_map"],
                         duplicates=scan["duplicates"],
                         replay_start=replay_start)
    # I7-only month-context gate: other accounts need confirmed_next_session,
    # while I7's month-end helper additionally requires the full usable month
    # plus next-month open context; a partial month must stay pending.
    if (assets["i7_turn_of_month"]["state"] == "ready"
            and not month["calendar_context"]["complete"]):
        assets["i7_turn_of_month"] = {
            "state": "pending",
            "reasons": [
                "I7 month-context incomplete (only I7 is gated on this): "
                + str(month["calendar_context"]["reason"])],
            **{k: assets["i7_turn_of_month"][k]
               for k in ("path", "version", "manifest_path", "manifest_sha256")}}
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
    # Shared read-only proof for the paper tick (same field contract as the
    # runtime i7_calendar_context helper).
    accounts["i7_turn_of_month"]["calendar_context"] = month["calendar_context"]

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
        "asset_bundle": asset_bundle,
        "calendar_context": month["calendar_context"],
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
