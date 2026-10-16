#!/usr/bin/env python3
"""Freeze actual native supplement rows into the existing paper asset schemas.

Consumes a completed ashare_input_supplements operation. No supplier requests,
strategy evaluation, guessed multipliers/limits or QA readiness decisions.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import sys

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ashare_input_supplements import PRODUCTS, SUFFIX, sha, dump, raw_rows


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def make_view(con, name, paths):
    if not paths:
        return None
    con.read_parquet([str(p) for p in paths], union_by_name=True).create_view(name)
    cols = {r[0] for r in con.execute(f"DESCRIBE {name}").fetchall()}
    # The supplier code column is authoritative; never reverse engineer symbols.
    code = ('COALESCE("source_ts_code","ts_code")' if {"source_ts_code", "ts_code"} <= cols
            else '"source_ts_code"' if "source_ts_code" in cols else '"ts_code"')
    fields = [f'"{c}"' for c in sorted(cols) if c not in ("ts_code",)]
    fields.append(f'{code} AS ts_code')
    con.execute(f"CREATE TEMP VIEW {name}_raw AS SELECT {','.join(fields)} FROM {name}")
    return cols


def dedup(con, name, keys):
    cols = {r[0] for r in con.execute(f"DESCRIBE {name}_raw").fetchall()}
    order = ','.join(f'"{c}" DESC NULLS LAST' for c in ("_fetched_at", "_observation") if c in cols) or "1"
    key = ','.join(f'"{c}"' for c in keys)
    con.execute(f"CREATE TEMP VIEW {name}_latest AS SELECT * EXCLUDE(_row) FROM "
                f"(SELECT *,row_number() OVER(PARTITION BY {key} ORDER BY {order}) _row FROM {name}_raw) WHERE _row=1")


def copy_query(con, query, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({query}) TO {literal(path)} (FORMAT PARQUET)")




def paths_for(root, refs, api):
    result = []
    seen = set()
    for item in refs.get(api, []):
        if item["path"] in seen:
            continue
        path = root / item["path"]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("Native source identity mismatch: " + item["path"])
        result.append(path)
        seen.add(item["path"])
    return result


def inventory(root, artifact_root, source, details, manifest, *,
              staging_root=None, canonical_root=None, data_key=None):
    def published(path):
        return canonical_root / path.relative_to(staging_root) if canonical_root is not None else path
    files = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root] if root.is_file() else []:
        files[str(published(path).relative_to(artifact_root))] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    # Audit timestamps belong to operation receipts, never the data manifest.
    body = {"schema_version": 2, "data_identity": data_key,
            "source": source, "files": files, "details": details,
            "policy": "Actual frozen source rows only; source QA alone decides account readiness"}
    dump(manifest, body)
    return {"path": str(published(root).relative_to(artifact_root)) if root.exists() else None,
            "manifest_path": str(published(manifest).relative_to(artifact_root)),
            "manifest_sha256": sha(manifest), "version": "asset-" + sha(manifest), "evidence": details}


OFFICIAL_FUTURES_SCHEMA = "https://tushare.pro/document/2?doc_id=135"
PHYSICAL_UNITS = {
    "吨": ("mass", Decimal("1000"), "kg"),
    "千克": ("mass", Decimal("1"), "kg"),
    "公斤": ("mass", Decimal("1"), "kg"),
    "克": ("mass", Decimal("0.001"), "kg"),
    "t": ("mass", Decimal("1000"), "kg"),
    "kg": ("mass", Decimal("1"), "kg"),
    "g": ("mass", Decimal("0.001"), "kg"),
    # Do not assume a commodity-dependent barrel/litre conversion.
    "桶": ("barrel", Decimal("1"), "barrel"),
}


def normalized_contract_multiplier(row):
    """CNY nominal value per quoted price point, from physical dimensions only."""
    try:
        quantity = Decimal(str(row.get("per_unit")))
    except InvalidOperation:
        raise ValueError("Missing/invalid source per_unit") from None
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("Missing/nonpositive source per_unit")
    trade = re.sub(r"\s+", "", str(row.get("trade_unit", ""))).lower()
    quote = re.sub(r"\s+", "", str(row.get("quote_unit", ""))).replace("／", "/")
    match = re.fullmatch(r"(?:人民币元|元|CNY|RMB)/(?:(\d+(?:\.\d+)?))?(.+)", quote)
    if not match:
        raise ValueError("Unknown/non-CNY source quote currency or denominator")
    amount = Decimal(match.group(1) or "1")
    denominator = match.group(2).lower()
    if trade not in PHYSICAL_UNITS or denominator not in PHYSICAL_UNITS:
        raise ValueError(f"Unknown physical unit: {trade!r}/{denominator!r}")
    trade_dimension, trade_scale, base = PHYSICAL_UNITS[trade]
    quote_dimension, quote_scale, _ = PHYSICAL_UNITS[denominator]
    if trade_dimension != quote_dimension or amount <= 0:
        raise ValueError("Incompatible physical dimensions or nonpositive quote denominator")
    value = quantity * trade_scale / (amount * quote_scale)
    if not math.isfinite(float(value)) or value <= 0:
        raise ValueError("Invalid normalized nominal multiplier")
    return {
        "normalized_multiplier": float(value), "currency": "CNY", "base_unit": base,
        "trade_quantity": str(quantity), "trade_unit_scale": str(trade_scale),
        "quote_quantity": str(amount), "quote_unit_scale": str(quote_scale),
        "formula": f"{quantity} * {trade_scale} / ({amount} * {quote_scale}) = {value}",
        "official_source": OFFICIAL_FUTURES_SCHEMA,
        "raw_multiplier_semantics": "Only applicable to Treasury/index futures; not a commodity input",
    }


def _ymd(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    value = str(value).replace("-", "")[:8]
    return value if len(value) == 8 and value.isdigit() else None


def contract_unit_closure(con, basic_rows, mapping_path, root, refs, artifact, start, end):
    calendar_path = artifact / "ashare-takeover/trees/ashare-lab/data/panel/calendar.parquet"
    days = {_ymd(row["date"]) for row in pq.read_table(calendar_path).to_pylist()}
    days.update(_ymd(row["cal_date"]) for row in raw_rows(root, refs["trade_cal"])
                if row.get("exchange") == "SSE" and int(row.get("is_open", 0)) == 1)
    days = sorted(day for day in days if day is not None and day <= end)
    before = [day for day in days if day < start]
    if len(before) < 251:
        raise ValueError("Actual SSE calendar lacks 251 sessions for frozen 250-return warmup")
    warmup_start = before[-251]
    anchor = before[-252] if len(before) > 251 else warmup_start
    products = {f"{p}.{SUFFIX[e]}" for e, ps in PRODUCTS.items() for p in ps}
    mappings = defaultdict(list)
    for code, day, contract in con.execute(
        f"SELECT ts_code,CAST(trade_date AS VARCHAR),mapping_ts_code FROM read_parquet({literal(mapping_path)}) "
        f"WHERE CAST(trade_date AS VARCHAR)<={literal(end)} ORDER BY ts_code,trade_date").fetchall():
        if code in products and isinstance(contract, str) and contract:
            mappings[code].append((day, contract))
    indices = {code: [day for day, _ in values] for code, values in mappings.items()}
    def near(code, day):
        pos = bisect_right(indices.get(code, []), day) - 1
        return mappings[code][pos][1] if pos >= 0 else None
    required = set()
    for day in days:
        if anchor <= day <= end:
            required.update(value for code in products if (value := near(code, day)))
    by_code = {row["ts_code"]: row for row in basic_rows}
    by_product = defaultdict(list)
    for row in basic_rows:
        by_product[row["fut_code"]].append(row)
    oi = {(code, day): float(value) for code, day, value in con.execute(
        "SELECT ts_code,CAST(trade_date AS VARCHAR),oi FROM fut_quotes_raw "
        f"WHERE CAST(trade_date AS VARCHAR)>={literal(start)} AND CAST(trade_date AS VARCHAR)<={literal(end)} "
        "AND oi IS NOT NULL AND oi>0").fetchall()}
    # A conservative dependency closure includes the frozen carry candidate on
    # each replay session; it does not select a new strategy or instrument pool.
    for day in [day for day in days if start <= day <= end]:
        for code in products:
            held = near(code, day)
            info = by_code.get(held)
            if not info:
                continue
            delivery = str(info.get("d_month", "")).split(".")[0]
            far = [row for row in by_product[info["fut_code"]]
                   if str(row.get("d_month", "")).split(".")[0] > delivery
                   and (_ymd(row.get("list_date")) or "99999999") <= day
                   and (_ymd(row.get("delist_date")) or "00000000") > day
                   and oi.get((row["ts_code"], day), 0) > 0]
            if far:
                chosen = min(far, key=lambda row: (
                    str(row["d_month"]).split(".")[0], _ymd(row["delist_date"]), row["ts_code"]))
                required.add(chosen["ts_code"])
    return {
        "replay_start": start, "replay_end": end, "warmup_start": warmup_start,
        "warmup_sessions": 251, "return_window": 250, "held_anchor_session": anchor,
        "required_contracts": sorted(required), "required_contract_count": len(required),
        "missing_required_metadata": sorted(required - set(by_code)),
        "missing_mapping_products": sorted(products - set(mappings)),
        "calendar": {"path": str(calendar_path.relative_to(artifact)), "sha256": sha(calendar_path)},
    }


def normalize_basic_units(path, root, closure):
    rows = pq.read_table(path).to_pylist()
    observations, objects, evidence = {}, {}, {}
    fields = ("multiplier", "per_unit", "trade_unit", "quote_unit", "quote_unit_desc")
    for row in rows:
        code = row["ts_code"]
        proof = {"ts_code": code, "required_for_window": code in closure["required_contracts"],
                 "official_source": OFFICIAL_FUTURES_SCHEMA, "source_object_sha256": None,
                 "raw_fields": {key: row.get(key) for key in fields}}
        row.update(normalized_multiplier=None, normalized_multiplier_formula=None,
                   normalized_multiplier_object_sha256=None, normalized_multiplier_currency=None)
        try:
            name = row.get("_observation")
            if not isinstance(name, str) or "/" in name or "\\" in name:
                raise ValueError("Missing native observation provenance for unit fields")
            if name not in observations:
                obs_path = root / "observations" / name
                observation = json.loads(obs_path.read_bytes())
                observations[name] = (observation["object_sha256"], sha(obs_path))
            object_sha, observation_sha = observations[name]
            if object_sha not in objects:
                object_path = root / "objects" / (object_sha + ".json")
                if sha(object_path) != object_sha:
                    raise ValueError("Native unit source object hash mismatch")
                payload = json.loads(object_path.read_bytes())["data"]
                objects[object_sha] = {
                    raw["ts_code"]: raw for values in payload["items"]
                    if (raw := dict(zip(payload["fields"], values))).get("ts_code")}
            raw = objects[object_sha].get(code)
            if raw is None:
                raise ValueError("Unit source object lacks this contract identity")
            proof.update(source_object_sha256=object_sha,
                         source_observation_path="observations/" + name,
                         source_observation_sha256=observation_sha,
                         raw_fields={key: raw.get(key) for key in fields})
            result = normalized_contract_multiplier(raw)
            proof.update(result)
            row.update(normalized_multiplier=result["normalized_multiplier"],
                       normalized_multiplier_formula=result["formula"],
                       normalized_multiplier_object_sha256=object_sha,
                       normalized_multiplier_currency="CNY")
        except (ValueError, KeyError) as exc:
            proof["blocked_reason"] = str(exc)
        evidence[code] = proof
    pq.write_table(pa.Table.from_pylist(rows), path)
    missing = sorted(code for code in closure["required_contracts"]
                     if not evidence.get(code, {}).get("normalized_multiplier"))
    return {"official_source": OFFICIAL_FUTURES_SCHEMA, "closure": closure,
            "canonical_column": "normalized_multiplier", "contracts": evidence,
            "required_missing_normalized_multiplier": missing,
            "unneeded_historical_missing_normalized_multiplier": sorted(
                code for code, proof in evidence.items()
                if not proof["required_for_window"] and not proof.get("normalized_multiplier"))}


def _has_codes(path, codes, *, field="source_ts_code", cutoff=None, after=None):
    schema = pq.read_schema(path).names
    if field not in schema:
        field = "ts_code" if field == "source_ts_code" and "ts_code" in schema else field
    if field not in schema:
        return False
    date_field = "trade_date" if "trade_date" in schema else "ex_date" if "ex_date" in schema else None
    columns = [field] + ([date_field] if date_field and cutoff else [])
    table = pq.read_table(path, columns=columns)
    selected = pc.is_in(table[field], value_set=pa.array(sorted(codes)))
    if date_field and cutoff:
        dates = pc.utf8_slice_codeunits(pc.replace_substring(
            pc.cast(table[date_field], pa.string()), "-", ""), 0, 8)
        selected = pc.and_(selected, pc.less_equal(dates, cutoff))
        if after:
            selected = pc.and_(selected, pc.greater(dates, after))
    return bool(pc.any(selected).as_py())


def bundle_identity(root, artifact, refs, cutoff, replay_start):
    """Only consumed asset families/identifiers, not CURRENT or audit clocks."""
    selected = {}
    product_names = {p for products in PRODUCTS.values() for p in products}
    continuous = {f"{p}.{SUFFIX[e]}" for e, products in PRODUCTS.items() for p in products}
    contract_codes = {row["ts_code"] for row in pq.read_table(
        artifact / "ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures/basic.parquet",
        columns=["ts_code"]).to_pylist()}
    selected["fut_basic"] = [ref for ref in {item["path"]: item for item in refs.get("fut_basic", [])}.values()
                             if _has_codes(root / ref["path"], product_names, field="fut_code")]
    for ref in selected["fut_basic"]:
        for row in pq.read_table(root / ref["path"]).to_pylist():
            if row.get("fut_code") in product_names:
                code = row.get("source_ts_code") or row.get("ts_code")
                if code:
                    contract_codes.add(code)
    for api, items in refs.items():
        if api in selected:
            continue
        chosen = []
        for ref in {item["path"]: item for item in items}.values():
            path = root / ref["path"]
            if api in ("fund_daily", "fund_adj", "etf_limit", "fund_div"):
                relevant = _has_codes(path, {"510300.SH", "511010.SH", "518880.SH"}, cutoff=cutoff)
            elif api == "fut_mapping":
                relevant = _has_codes(path, continuous, cutoff=cutoff)
            elif api == "fut_daily":
                relevant = _has_codes(path, contract_codes, cutoff=cutoff, after="20260930")
            elif api == "trade_cal":
                relevant = True
            elif api in ("cb_daily", "cb_basic", "cb_call"):
                relevant = True
            else:
                relevant = False
            if relevant:
                chosen.append(ref)
        selected[api] = chosen
    records = [list(row) for row in sorted({(api, item["path"], item["sha256"], item["bytes"])
                                           for api, items in selected.items() for item in items})]
    repo = Path(__file__).resolve().parents[1]
    programs = ("scripts/ashare_export_supplement_inputs.py",
                "scripts/ashare_input_supplements.py",
                "vendor/ashare-lab/src/ashare_lab/paper_inputs.py",
                "vendor/ashare-lab/src/ashare_lab/data/build.py")
    identity = {"schema_version": 2, "cutoff": cutoff, "replay_start": replay_start,
                "frozen_archive_identity_sha256": sha(artifact / "ashare-takeover/identity.json"),
                "normalizer_code": {name: sha(repo / name) for name in programs},
                "source_refs": records, "frozen_products": PRODUCTS}
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()
    return key, identity


def merged_calendar(root, refs, operation, cutoff):
    """Reuse the existing calendar merger only after semantic conflict checks."""
    selected = sorted({item["path"]: item for item in refs["trade_cal"]}.values(),
                      key=lambda item: item["path"])
    rows = raw_rows(root, selected)
    unique, previous_dates = {}, {}
    source_rows = 0
    for row in rows:
        if row.get("exchange") != "SSE":
            continue
        day = _ymd(row["cal_date"])
        if day is None:
            raise ValueError("Invalid native calendar date")
        datetime.strptime(day, "%Y%m%d")
        flag = Decimal(str(row["is_open"]))
        if flag not in (0, 1):
            raise ValueError(f"Invalid native calendar is_open: SSE/{day}")
        key = ("SSE", day)
        if key in unique and unique[key] != int(flag):
            raise ValueError(f"Conflicting native calendar is_open: SSE/{day}")
        unique[key] = int(flag)
        previous = _ymd(row.get("pretrade_date"))
        if previous is not None:
            if key in previous_dates and previous_dates[key] != previous:
                raise ValueError(f"Conflicting native calendar pretrade_date: SSE/{day}")
            previous_dates[key] = previous
        source_rows += 1
    if not unique:
        raise ValueError("No verified real SSE calendar rows")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/ashare-lab/src"))
    from ashare_lab.data.build import _cache_api
    cache = operation / "merged-calendar"
    cache.mkdir(exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute("SET threads=2")
        _cache_api(connection, "trade_cal", [str(root / item["path"]) for item in selected], cache)
    merged = cache / "trade_cal.parquet"
    actual = {("SSE", _ymd(row["date"])): int(row["is_open"])
              for row in pq.read_table(merged).to_pylist() if row["exchange"] == "SSE"}
    if actual != unique:
        raise ValueError("Existing calendar merger did not preserve the verified source union")
    folder = root / "derived/ashare-input-supplements/calendars"
    folder.mkdir(parents=True, exist_ok=True)
    digest = sha(merged)
    destination = folder / (digest + ".parquet")
    if destination.exists():
        if sha(destination) != digest:
            raise ValueError("Immutable merged calendar checksum mismatch")
    else:
        temporary = folder / f".{digest}.{os.getpid()}.tmp"
        shutil.copyfile(merged, temporary)
        os.replace(temporary, destination)
    destination.chmod(0o444)
    days = sorted(day for exchange, day in unique)
    future = sorted(day for (exchange, day), flag in unique.items() if flag == 1 and day > cutoff)
    repo = Path(__file__).resolve().parents[1]
    source_refs = [{k: item[k] for k in ("path", "sha256", "bytes")} for item in selected]
    closure = {
        "schema_version": 1, "kind": "verified-calendar-union", "exchange": "SSE",
        "merge_keys": ["exchange", "cal_date"],
        "consistency_fields": ["is_open", "pretrade_date when present"],
        "conflicts": 0, "source_rows": source_rows, "unique_rows": len(unique),
        "duplicate_source_rows": source_rows - len(unique),
        "first_date": days[0], "last_date": days[-1], "source_refs": source_refs,
        "merger_code": {name: sha(repo / name) for name in (
            "scripts/ashare_export_supplement_inputs.py",
            "vendor/ashare-lab/src/ashare_lab/data/build.py")},
        "merged": {"path": str(destination.relative_to(root)), "sha256": digest,
                   "bytes": destination.stat().st_size},
        "policy": "Union of verified real rows; identical duplicate dates only; no synthesized weekdays"}
    encoded = (json.dumps(closure, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    closure_digest = hashlib.sha256(encoded).hexdigest()
    closure_path = folder / (closure_digest + ".json")
    if closure_path.exists():
        if sha(closure_path) != closure_digest:
            raise ValueError("Immutable calendar source closure checksum mismatch")
    else:
        temporary = folder / f".{closure_digest}.{os.getpid()}.tmp"
        temporary.write_bytes(encoded)
        os.replace(temporary, closure_path)
    closure_path.chmod(0o444)
    return {"api_name": "trade_cal", "kind": "verified-calendar-union", **closure["merged"],
            "source_closure_path": str(closure_path.relative_to(root)),
            "source_closure_sha256": closure_digest, "source_closure_bytes": len(encoded),
            "confirmed_next_session": datetime.strptime(future[0], "%Y%m%d").date().isoformat() if future else None}


def verified_bundle(canonical, artifact, key, identity, root):
    path = canonical / "bundle.json"
    if not path.exists():
        return None
    body = json.loads(path.read_bytes())
    if body["data_identity"] != key or body["identity"] != identity:
        raise ValueError("Immutable asset bundle identity mismatch")
    checked = set()
    for entry in body["evidence"]["inputs"].values():
        manifest = (artifact / entry["manifest_path"]).resolve()
        if not manifest.is_relative_to(canonical) or sha(manifest) != entry["manifest_sha256"]:
            raise ValueError("Immutable asset manifest checksum mismatch")
        for relative, expected in json.loads(manifest.read_bytes())["files"].items():
            target = (artifact / relative).resolve()
            if not target.is_relative_to(canonical):
                raise ValueError("Immutable asset payload escaped its data key")
            if relative in checked:
                continue
            if target.stat().st_size != expected["bytes"] or sha(target) != expected["sha256"]:
                raise ValueError("Immutable asset payload checksum mismatch")
            checked.add(relative)
    calendars = body["evidence"]["calendar_candidates"]
    if len(calendars) != 1 or calendars[0].get("kind") != "verified-calendar-union":
        raise ValueError("Canonical source requires one merged historical/future calendar")
    calendar = calendars[0]
    for prefix, suffix in (("path", "sha256"), ("source_closure_path", "source_closure_sha256")):
        path = (root / calendar[prefix]).resolve()
        size = calendar["bytes" if prefix == "path" else "source_closure_bytes"]
        if not path.is_relative_to(root) or path.stat().st_size != size or sha(path) != calendar[suffix]:
            raise ValueError("Immutable merged calendar or source closure checksum mismatch")
    closure = json.loads((root / calendar["source_closure_path"]).read_bytes())
    expected = {(path, digest, size) for api, path, digest, size in identity["source_refs"] if api == "trade_cal"}
    actual = {(item["path"], item["sha256"], item["bytes"]) for item in closure["source_refs"]}
    if closure["conflicts"] != 0 or actual != expected:
        raise ValueError("Merged calendar source closure differs from the canonical source key")
    for item in closure["source_refs"]:
        path = root / item["path"]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise ValueError("Merged calendar raw source checksum mismatch")
    return body


def publish_current_bundle(artifact, canonical, key):
    """One atomic data entrypoint; operation directories are audit-only."""
    pointer = artifact / "ashare-input-supplements/CURRENT.json"
    value = {"schema_version": 1, "data_identity": key,
             "bundle_path": str((canonical / "bundle.json").relative_to(artifact)),
             "bundle_sha256": sha(canonical / "bundle.json")}
    temporary = pointer.with_name(f".CURRENT-{os.getpid()}.json")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, pointer)
    return value


def current_bundle(artifact, root):
    """Read exactly CURRENT; never discover an epoch or old-schema fallback."""
    pointer = json.loads((artifact / "ashare-input-supplements/CURRENT.json").read_bytes())
    key = pointer["data_identity"]
    if pointer["schema_version"] != 1 or not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("Unsupported canonical source pointer")
    relative = f"ashare-input-supplements/assets-{key}/bundle.json"
    if pointer["bundle_path"] != relative:
        raise ValueError("Canonical source pointer is not content-addressed")
    path = artifact / relative
    if sha(path) != pointer["bundle_sha256"]:
        raise ValueError("Canonical source bundle checksum mismatch")
    body = json.loads(path.read_bytes())
    identity = body["identity"]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    if identity["schema_version"] != 2 or digest != key:
        raise ValueError("Canonical source identity mismatch")
    body = verified_bundle(path.parent, artifact, key, identity, root)
    if set(body["evidence"]["inputs"]) != {
            "i7_turn_of_month", "s1_invvol_etf", "cb_double_low", "cta_combined", "cta_trend"}:
        raise ValueError("Canonical source bundle lacks the five asset entries")
    return pointer, body


def record_operation_evidence(operation, evidence):
    path = operation / "asset-evidence.json"
    if path.exists():
        prior = json.loads(path.read_bytes())
        actual = {k: v for k, v in prior.items() if k != "derivation_performed"}
        expected = {k: v for k, v in evidence.items() if k != "derivation_performed"}
        if actual != expected:
            raise ValueError("Immutable operation evidence is not this canonical bundle")
    else:
        dump(path, evidence)


def export(args):
    root, operation, artifact = args.root.resolve(), args.operation.resolve(), args.artifact_root.resolve()
    plan = json.loads((operation / "plan.json").read_bytes())
    publication = json.loads((operation / "native-publication.json").read_bytes())
    refs = json.loads((operation / "source-refs.json").read_bytes())
    added = json.loads((operation / "new-source-refs.json").read_bytes())
    for api, items in added.items():
        refs.setdefault(api, []).extend(items)
    key, identity = bundle_identity(root, artifact, refs, args.end,
                                    getattr(args, "replay_start", "20261013"))
    canonical = artifact / "ashare-input-supplements" / ("assets-" + key)
    cached = verified_bundle(canonical, artifact, key, identity, root)
    if cached:
        evidence = {**cached["evidence"], "derivation_performed": False}
        record_operation_evidence(operation, evidence)
        publish_current_bundle(artifact, canonical, key)
        print(json.dumps({"evidence": str((operation / "asset-evidence.json").relative_to(artifact)),
                          "data_identity": key, "derivation_performed": False}))
        return
    source = {"base": plan["source"], "supplement": {k: publication[k] for k in ("release_id", "manifest_path", "manifest_sha256")},
              "root_contract": "archive-root", "window": plan["window"]}
    source["native_observations"] = []
    outcomes = json.loads((operation / "native-outcomes.json").read_bytes())
    for item in outcomes["outcomes"]:
        result = item["result"]
        if not result.get("parquet"):
            continue
        observation = "observations/" + result["observation"]
        object_path = "objects/" + result["object_sha256"] + ".json"
        if sha(root / observation) != result["observation_sha256"] or sha(root / object_path) != result["object_sha256"]:
            raise ValueError("Committed native observation/object closure identity mismatch")
        source["native_observations"].append({
            "api": item["api"], "task_id": item["task_id"], "params": item["params"],
            "observation_path": observation, "observation_sha256": result["observation_sha256"],
            "object_path": object_path, "object_sha256": result["object_sha256"],
            "parquet": result["parquet"]})
    observations = {}
    calendars = []
    for api, items in added.items():
        rows = raw_rows(root, items)
        axes = {}
        for field in ("trade_date", "cal_date", "list_date", "ann_date"):
            values = sorted({str(r[field]) for r in rows if r.get(field) is not None})
            if values:
                axes[field] = {"min": values[0], "max": values[-1], "distinct": len(values)}
        observations[api] = {
            "rows": len(rows), "date_axes": axes,
            "nonnull_fields": {field: sum(r.get(field) is not None for r in rows)
                               for field in ("multiplier", "settle", "cb_over_rate", "up_limit", "down_limit")},
            "source_refs": items,
        }
    calendars = [merged_calendar(root, refs, operation, args.end)]
    if not (operation / "observed-source-fields.json").exists():
        dump(operation / "observed-source-fields.json", observations)
    out = operation / ("asset-staging-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(exist_ok=False)
    def record_asset(asset_root, details, manifest_name):
        return inventory(asset_root, artifact, source, details, out / manifest_name,
                         staging_root=out, canonical_root=canonical, data_key=key)
    inputs, errors = {}, {}
    cb_old = artifact / "ashare-takeover/trees/ashare-lab-ideas-cb/data/extra"
    fut_old = artifact / "ashare-takeover/trees/ashare-lab-ideas-cta/data/extra/i9_futures"
    cutoff = f"{args.end[:4]}-{args.end[4:6]}-{args.end[6:]}"
    with duckdb.connect() as con:
        con.execute("SET threads=2")
        # Use bounded spill inside this new derivative only, never native config/cache.
        con.execute(f"SET temp_directory={literal(operation / 'export-spill')}")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/ashare-lab/src"))
            from ashare_lab.paper_inputs import _etf_panel
            etf_refs = []
            for api in ("fund_daily", "fund_adj", "etf_limit", "fund_div"):
                paths_for(root, refs, api)
                etf_refs.extend(refs.get(api, []))
            etf = out / "etf.parquet"
            cache = operation / "etf-cache"
            cache.mkdir(exist_ok=True)
            dividend_evidence = _etf_panel(root / publication["manifest_path"], etf, cache, cutoff,
                       source_root=root, dataset_refs=etf_refs)
            evidence = con.execute(f"SELECT code,COUNT(*) AS row_count,MIN(date)::VARCHAR first_date,MAX(date)::VARCHAR last_date,"
                "COUNT(*) FILTER(WHERE adj IS NULL) missing_adj,COUNT(*) FILTER(WHERE up_limit IS NULL OR down_limit IS NULL) missing_limits,"
                "COUNT(*) FILTER(WHERE date>=DATE '2026-10-13' AND (up_limit IS NULL OR down_limit IS NULL)) execution_missing_limits "
                f"FROM read_parquet({literal(etf)}) GROUP BY code ORDER BY code").fetchall()
            details = {"rows_by_code": [dict(zip(("code", "rows", "first_date", "last_date", "missing_adj", "missing_limits", "execution_missing_limits"), r)) for r in evidence],
                       "limit_api": "etf_limit", "units": {"amount": "CNY source thousand CNY*1000", "volume": "shares source lots*100"},
                       **dividend_evidence,
                       "inference": "none; absent real limits remain NULL"}
            entry = record_asset(etf, details, "etf-manifest.json")
            for name in ("i7_turn_of_month", "s1_invvol_etf"):
                inputs[name] = entry
        except (ValueError, duckdb.Error) as exc:
            error = f"{type(exc).__name__}: {exc}".replace(str(out), "<asset-staging>").replace(str(root), "<archive-root>").replace(str(artifact), "<artifact-root>")
            errors["i7_turn_of_month"] = errors["s1_invvol_etf"] = error
            entry = record_asset(out / "etf.parquet", {"source_blocker": error}, "etf-blocked-manifest.json")
            inputs["i7_turn_of_month"] = inputs["s1_invvol_etf"] = entry
        try:
            cb = out / "convertible-bonds"
            cb.mkdir()
            shutil.copytree(cb_old / "cb_daily", cb / "cb_daily", copy_function=shutil.copyfile)
            for api, keys in (("cb_basic", ("ts_code",)), ("cb_call", ("ts_code", "ann_date", "call_type", "is_call"))):
                make_view(con, api, [cb_old / f"{api}.parquet", *paths_for(root, refs, api)])
                dedup(con, api, keys)
                copy_query(con, f"SELECT * FROM {api}_latest", cb / f"{api}.parquet")
            new_daily = paths_for(root, refs, "cb_daily")
            actual_days = []
            if new_daily:
                make_view(con, "cb_new", new_daily)
                dedup(con, "cb_new", ("ts_code", "trade_date"))
                actual_days = [str(r[0]) for r in con.execute(
                    "SELECT DISTINCT trade_date FROM cb_new_latest WHERE CAST(trade_date AS VARCHAR)>'20260930' "
                    f"AND CAST(trade_date AS VARCHAR)<={literal(args.end)} ORDER BY 1").fetchall()]
                for day in actual_days:
                    target = cb / "cb_daily" / f"{day}.parquet"
                    if target.exists():
                        raise ValueError("Supplement would replace preserved CB day: " + day)
                    copy_query(con, f"SELECT * FROM cb_new_latest WHERE CAST(trade_date AS VARCHAR)={literal(day)}", target)
            paths = sorted((cb / "cb_daily").glob("*.parquet"))
            make_view(con, "cb_all", paths)
            stats = con.execute("SELECT MIN(trade_date)::VARCHAR,MAX(trade_date)::VARCHAR,COUNT(*),"
                                "COUNT(*) FILTER(WHERE cb_over_rate IS NULL) FROM cb_all_raw").fetchone()
            details = {"actual_min_trade_date": stats[0], "actual_max_trade_date": stats[1], "rows": stats[2],
                       "missing_cb_over_rate_rows": stats[3], "new_actual_trade_dates": actual_days,
                       "requested_actual_dates": plan["window"]["observed_sse_dates"], "original_daily_cutoff": "20260930"}
            inputs["cb_double_low"] = record_asset(cb, details, "convertible-bonds-manifest.json")
        except (ValueError, duckdb.Error) as exc:
            error = f"{type(exc).__name__}: {exc}".replace(str(out), "<asset-staging>").replace(str(root), "<archive-root>").replace(str(artifact), "<artifact-root>")
            errors["cb_double_low"] = error
            inputs["cb_double_low"] = record_asset(out / "convertible-bonds", {"source_blocker": error}, "convertible-bonds-blocked-manifest.json")
        try:
            fut = out / "commodities"
            fut.mkdir()
            shutil.copytree(fut_old / "contracts", fut / "contracts", copy_function=shutil.copyfile)
            make_view(con, "fut_meta", [fut_old / "basic.parquet", *paths_for(root, refs, "fut_basic")])
            dedup(con, "fut_meta", ("ts_code",))
            products = ','.join(literal(p) for ps in PRODUCTS.values() for p in ps)
            fresh = paths_for(root, refs, "fut_daily")
            con.read_parquet(str(fut_old / "basic.parquet")).create_view("frozen_original_contracts")
            contract_scope = "SELECT ts_code FROM frozen_original_contracts"
            if fresh:
                make_view(con, "fut_new", fresh)
                dedup(con, "fut_new", ("ts_code", "trade_date"))
                contract_scope += (
                    " UNION SELECT ts_code FROM fut_new_latest WHERE CAST(trade_date AS VARCHAR)>'20260930' "
                    f"AND CAST(trade_date AS VARCHAR)<={literal(args.end)}")
            basic = fut / "basic.parquet"
            copy_query(con, f"SELECT * FROM fut_meta_latest WHERE fut_code IN({products}) "
                f"AND CAST(list_date AS VARCHAR)<={literal(args.end)} AND ts_code IN({contract_scope})", basic)
            codes = [r[0] for r in con.execute(f"SELECT ts_code FROM read_parquet({literal(basic)})").fetchall()]
            actual_daily = []
            if fresh:
                actual_daily = [str(r[0]) for r in con.execute(
                    "SELECT DISTINCT trade_date FROM fut_new_latest WHERE CAST(trade_date AS VARCHAR)>'20260930' "
                    f"AND CAST(trade_date AS VARCHAR)<={literal(args.end)} ORDER BY 1").fetchall()]
                present = {r[0] for r in con.execute(
                    "SELECT DISTINCT ts_code FROM fut_new_latest WHERE CAST(trade_date AS VARCHAR)>'20260930' "
                    f"AND CAST(trade_date AS VARCHAR)<={literal(args.end)}").fetchall()}
                for i, code in enumerate(codes):
                    if code not in present:
                        continue
                    target = fut / "contracts" / f"{code}.parquet"
                    new = con.execute("SELECT * FROM fut_new_latest WHERE ts_code=? AND CAST(trade_date AS VARCHAR)>'20260930' "
                                      f"AND CAST(trade_date AS VARCHAR)<={literal(args.end)}", [code]).fetch_arrow_table()
                    if target.exists():
                        # DuckDB performs the same natural-key latest-observation merge.
                        old = con.read_parquet(str(target)).fetch_arrow_table()
                        con.register("contract_new", new)
                        con.register("contract_old", old)
                        table = con.execute("SELECT * EXCLUDE(_row) FROM (SELECT *,row_number() OVER(PARTITION BY ts_code,trade_date ORDER BY _is_new DESC) _row FROM (SELECT *,0 _is_new FROM contract_old UNION ALL BY NAME SELECT *,1 _is_new FROM contract_new)) WHERE _row=1").fetch_arrow_table()
                        table = table.drop(["_is_new"])
                        pq.write_table(table, target)
                    else:
                        pq.write_table(new, target)
            maps = [fut_old / "mapping.parquet", *paths_for(root, refs, "fut_mapping")]
            make_view(con, "fut_map", maps)
            dedup(con, "fut_map", ("ts_code", "trade_date"))
            continuous = ','.join(literal(f"{p}.{SUFFIX[e]}") for e, ps in PRODUCTS.items() for p in ps)
            copy_query(con, f"SELECT * FROM fut_map_latest WHERE ts_code IN({continuous}) ORDER BY ts_code,trade_date", fut / "mapping.parquet")
            quote_paths = [fut / "contracts" / f"{code}.parquet" for code in codes]
            absent = [p.name for p in quote_paths if not p.exists()]
            make_view(con, "fut_quotes", [p for p in quote_paths if p.exists()])
            stats = con.execute("SELECT MIN(trade_date)::VARCHAR,MAX(trade_date)::VARCHAR,COUNT(*),COUNT(*) FILTER(WHERE settle IS NULL) FROM fut_quotes_raw").fetchone()
            required_mapped = {r[0] for r in con.execute(
                f"SELECT DISTINCT mapping_ts_code FROM read_parquet({literal(fut / 'mapping.parquet')}) "
                f"WHERE CAST(trade_date AS VARCHAR)>'20260930' AND CAST(trade_date AS VARCHAR)<={literal(args.end)}").fetchall()}
            missing_mapped_metadata = sorted(required_mapped - set(codes))
            closure = contract_unit_closure(con, pq.read_table(basic).to_pylist(),
                fut / "mapping.parquet", root, refs, artifact,
                getattr(args, "replay_start", "20261013"), args.end)
            unit_evidence = normalize_basic_units(basic, root, closure)
            unit_path = fut / "contract-unit-evidence.json"
            dump(unit_path, unit_evidence)
            missing_multiplier = len(unit_evidence["required_missing_normalized_multiplier"])
            details = {"frozen_products": PRODUCTS, "products": 45, "contracts": len(codes),
                       "actual_min_trade_date": stats[0], "actual_max_trade_date": stats[1], "quote_rows": stats[2],
                       "missing_settle_rows": stats[3], "missing_normalized_multiplier_contracts": missing_multiplier,
                       "missing_contract_files": absent, "new_actual_trade_dates": actual_daily,
                       "contract_selection": "Frozen original contract set plus actually quoted current contracts within the same frozen 45 products",
                       "missing_mapped_metadata": missing_mapped_metadata,
                       "canonical_multiplier_column": "normalized_multiplier",
                       "unit_evidence_path": str((canonical / unit_path.relative_to(out)).relative_to(artifact)),
                       "unit_evidence_sha256": sha(unit_path), "unit_closure": closure,
                       "raw_multiplier_semantics": "doc135: only Treasury/index futures; NULL is normal for commodities",
                       "inference": "none; missing multipliers/settlements remain missing, no CFFEX substitution"}
            entry = record_asset(fut, details, "commodities-manifest.json")
            inputs["cta_combined"] = inputs["cta_trend"] = entry
        except (ValueError, duckdb.Error) as exc:
            error = f"{type(exc).__name__}: {exc}".replace(str(out), "<asset-staging>").replace(str(root), "<archive-root>").replace(str(artifact), "<artifact-root>")
            errors["cta_combined"] = errors["cta_trend"] = error
            entry = record_asset(out / "commodities", {"source_blocker": error}, "commodities-blocked-manifest.json")
            inputs["cta_combined"] = inputs["cta_trend"] = entry
    evidence = {"schema_version": 1, "inputs": inputs, "errors": errors,
                "calendar_candidates": calendars, "data_identity": key,
                "contract": "Calendar paths relative to archive-root; asset paths relative to artifact-root; source QA alone decides admission"}
    dump(out / "bundle.json", {"data_identity": key, "identity": identity, "evidence": evidence})
    try:
        out.rename(canonical)
    except OSError:
        existing = verified_bundle(canonical, artifact, key, identity, root)
        if existing is None:
            raise
        evidence = existing["evidence"]
    for path in canonical.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    record_operation_evidence(operation, {**evidence, "derivation_performed": True})
    publish_current_bundle(artifact, canonical, key)
    print(json.dumps({"evidence": str((operation / 'asset-evidence.json').relative_to(artifact)),
                      "inputs": sorted(inputs), "errors": errors, "data_identity": key,
                      "derivation_performed": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--end", default="20261015")
    export(parser.parse_args())


if __name__ == "__main__":
    main()
