"""Verified fixed-release reads and exports; observation time is not PIT proof.

Queries never call providers, refresh CURRENT, install extensions or open remote
Parquet files. A caller must pin release_id and inspect coverage independently.
"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from backend.shared.tushare_registry import (
    REALTIME_RUNTIME_CONTRACTS,
    ACCOUNT_HISTORY_RUNTIME_CONTRACTS,
    SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS,
    HISTORY_MINUTES_RUNTIME_CONTRACTS,
    CALENDAR_EXTRA_RUNTIME_CONTRACTS,
    FACTOR_LIBRARY_RUNTIME_CONTRACTS,
    BOND_EXTRA_RUNTIME_CONTRACTS,
    CROSS_ASSET_RUNTIME_CONTRACTS,
    MARKET_SENTIMENT_RUNTIME_CONTRACTS,
    FOREIGN_FINANCIAL_RUNTIME_CONTRACTS,
    CONNECT_RUNTIME_CONTRACTS,
    LEGACY_CONNECT_RUNTIME_CONTRACTS,
    OFFCATALOG_RUNTIME_CONTRACTS,
    TRADING_EVENT_RUNTIME_CONTRACTS,
    LISTING_EXTRA_RUNTIME_CONTRACTS,
    LIMIT_EXTRA_RUNTIME_CONTRACTS,
    CONCEPT_EXTRA_RUNTIME_CONTRACTS,
    DC_EXTRA_RUNTIME_CONTRACTS,
    RISK_EVENT_RUNTIME_CONTRACTS,
    TECHNICAL_EXTRA_RUNTIME_CONTRACTS,
    STOCK_CONTEXT_RUNTIME_CONTRACTS,
)
from backend.shared.tushare_credit_extra_contracts import CREDIT_EXTRA_CONTRACTS
from backend.shared.tushare_etf_basket_contracts import ETF_BASKET_CONTRACTS
from backend.shared.tushare_market_contracts import MARKET_CONTRACTS
from backend.shared.tushare_global_contracts import GLOBAL_CONTRACTS
from backend.shared.tushare_other_contracts import OTHER_CONTRACTS
from backend.shared.tushare_supplement_contracts import SUPPLEMENT_CONTRACTS
from backend.shared.tushare_equity_event_contracts import EQUITY_EVENT_CONTRACTS
from backend.shared.tushare_futures_extra_contracts import FUTURES_EXTRA_CONTRACTS
from backend.shared.tushare_research_extra_contracts import RESEARCH_EXTRA_CONTRACTS
from backend.shared.tushare_pipeline import manifest_at
from backend.shared.tushare_structured_contracts import STRUCTURED_CONTRACTS
from backend.shared.tushare_text_contracts import TEXT_CONTRACTS
from backend.shared.tushare_rrg_contracts import RRG_CONTRACTS

KEYS = {}
CONTRACTS = {
    **RRG_CONTRACTS,
    **REALTIME_RUNTIME_CONTRACTS,    **ACCOUNT_HISTORY_RUNTIME_CONTRACTS,
    **SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS,
    **HISTORY_MINUTES_RUNTIME_CONTRACTS,
    **CALENDAR_EXTRA_RUNTIME_CONTRACTS,
    **FACTOR_LIBRARY_RUNTIME_CONTRACTS,
    **BOND_EXTRA_RUNTIME_CONTRACTS,
    **CROSS_ASSET_RUNTIME_CONTRACTS,
    **MARKET_SENTIMENT_RUNTIME_CONTRACTS,
    **FOREIGN_FINANCIAL_RUNTIME_CONTRACTS,
    **STOCK_CONTEXT_RUNTIME_CONTRACTS,
    **RISK_EVENT_RUNTIME_CONTRACTS,
    **TECHNICAL_EXTRA_RUNTIME_CONTRACTS,
    **DC_EXTRA_RUNTIME_CONTRACTS,
    **CONCEPT_EXTRA_RUNTIME_CONTRACTS,
    **LIMIT_EXTRA_RUNTIME_CONTRACTS,
    **LISTING_EXTRA_RUNTIME_CONTRACTS,
    **TRADING_EVENT_RUNTIME_CONTRACTS,
    **CONNECT_RUNTIME_CONTRACTS,
    **LEGACY_CONNECT_RUNTIME_CONTRACTS,
    **OFFCATALOG_RUNTIME_CONTRACTS,
    **ETF_BASKET_CONTRACTS,
    **CREDIT_EXTRA_CONTRACTS,
    **TEXT_CONTRACTS,
    **STRUCTURED_CONTRACTS,
    **MARKET_CONTRACTS,
    **GLOBAL_CONTRACTS,
    **OTHER_CONTRACTS,
    **SUPPLEMENT_CONTRACTS,
    **EQUITY_EVENT_CONTRACTS,
    **FUTURES_EXTRA_CONTRACTS,
    **RESEARCH_EXTRA_CONTRACTS,
}
IDENTITIES = {}
for _api, _contract in CONTRACTS.items():
    KEYS[_api] = tuple(_contract["keys"])
    _identity = _contract.get("dataset_identity", _api)
    IDENTITIES[_api] = _identity
    KEYS.setdefault(_identity, KEYS[_api])
    IDENTITIES[_identity] = _identity

DATE_FIELDS = (
    "trade_date",
    "ann_date",
    "date",
    "datetime",
    "pub_time",
    "pubtime",
    "pub_date",
    "nav_date",
    "cal_date",
    "publish_date",
    "report_date",
    "surv_date",
    "week_date",
    "end_date",
    "in_date",
    "start_date",
    "ipo_date",
    "list_date",
    "begin_date",
    "rate_start_date",
    "month",
    "quarter",
)
TEXT_FIELDS = (
    "title",
    "content",
    "content_html",
    "q",
    "a",
    "abstr",
    "name",
    "file_name",
)
OBSERVATION_NOTE = "as_of filters this system's observation time; it is not historical publication-time or PIT proof"


def _identifier(name, columns):
    if not isinstance(name, str) or name not in columns:
        raise ValueError(f"Unknown stored field: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _metadata(manifest, release_id, api_name, aliases):
    return {
        "release_id": release_id,
        "api_name": api_name,
        "source_api_names": sorted(aliases),
        "historical_versions_complete": manifest.get("historical_versions_complete")
        is True,
        "history_complete": manifest.get("history_complete") is True,
        "coverage": [
            r
            for r in manifest.get("coverage_by_api", [])
            if r.get("api_name") in aliases
        ],
        "as_of_semantics": OBSERVATION_NOTE,
        "upstream_calls": 0,
    }


@contextmanager
def _dataset(root, release_id, api_name):
    import duckdb

    if api_name not in KEYS:
        raise ValueError("Unknown dataset; no upstream fallback")
    root = Path(root).resolve()
    manifest = manifest_at(root, release_id)
    identity = IDENTITIES.get(api_name, api_name)
    aliases = {name for name, value in IDENTITIES.items() if value == identity} | {
        api_name
    }
    paths, source_apis = [], set()
    for dataset in manifest["datasets"]:
        if dataset["api_name"] not in aliases:
            continue
        source_apis.add(dataset["api_name"])
        name = dataset["path"]
        if name not in manifest["files"] or not re.fullmatch(
            r"parquet/[a-f0-9]{64}\.parquet", name
        ):
            raise ValueError("Dataset missing from verified file inventory")
        path = root / name
        if (
            path.is_symlink()
            or path.parent.is_symlink()
            or path.resolve().parent != root / "parquet"
        ):
            raise ValueError("Invalid stored partition path")
        expected = manifest["files"][name]
        if path.stat().st_size != expected["bytes"]:
            raise ValueError("Stored partition size mismatch")
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(block)
        if sha.hexdigest() != expected["sha256"] or sha.hexdigest() != path.stem:
            raise ValueError("Stored partition checksum mismatch")
        paths.append(str(path))
    if not paths:
        raise ValueError("Dataset unavailable in fixed release; no upstream fallback")
    with (
        tempfile.TemporaryDirectory(prefix="tushare-query-") as spill,
        duckdb.connect(
            config={
                "temp_directory": spill,
                "memory_limit": "512MB",
                "threads": "2",
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
            }
        ) as db,
    ):
        relation = db.read_parquet(sorted(set(paths)), union_by_name=True)
        columns = relation.columns
        keys = list(KEYS[api_name])
        if not set(keys + ["_fetched_at", "_observation"]).issubset(columns):
            raise ValueError("Stored dataset lacks natural-key or observation fields")
        spec = CONTRACTS.get(api_name, {})
        identity_fields = spec.get("request_identity_fields", [])
        identity_observations = 0
        if not isinstance(identity_fields, (list, tuple)) or any(
            not isinstance(field, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field)
            for field in identity_fields
        ):
            raise ValueError("Invalid contract request identity fields")
        if identity_fields:
            # Verify immutable request provenance, including for legacy Parquet
            # that hashed only the raw payload. This is a query-local projection;
            # no old partitions or observation files are rewritten.
            if "_row_identity" not in columns:
                raise ValueError("Request identity gap: missing raw row identity")
            db.execute(
                "CREATE TEMP TABLE request_identity_map(observation VARCHAR PRIMARY KEY, identity_json VARCHAR)"
            )
            observations = relation.project('"_observation"').distinct().fetchall()
            for (observation,) in observations:
                if not isinstance(observation, str) or not re.fullmatch(
                    r"[a-f0-9]{32,64}\.json", observation
                ):
                    raise ValueError(
                        "Request identity gap: invalid observation reference"
                    )
                name = "observations/" + observation
                expected = manifest["files"].get(name)
                if not isinstance(expected, dict):
                    raise ValueError(
                        "Request identity gap: observation outside fixed release"
                    )
                path = root / name
                if (
                    path.is_symlink()
                    or path.parent.is_symlink()
                    or path.resolve().parent != root / "observations"
                ):
                    raise ValueError("Request identity gap: unsafe observation path")
                try:
                    raw = path.read_bytes()
                except OSError as exc:
                    raise ValueError(
                        "Request identity gap: observation unavailable"
                    ) from exc
                if len(raw) != expected.get("bytes") or hashlib.sha256(
                    raw
                ).hexdigest() != expected.get("sha256"):
                    raise ValueError(
                        "Request identity gap: observation checksum mismatch"
                    )
                observed = json.loads(raw)
                request = (
                    observed.get("request") if isinstance(observed, dict) else None
                )
                if (
                    not isinstance(request, dict)
                    or request.get("api_name") not in aliases
                ):
                    raise ValueError("Request identity gap: observation API mismatch")
                params = request.get("params")
                if not isinstance(params, dict):
                    raise ValueError(
                        "Request identity gap: request parameters unavailable"
                    )
                missing = [
                    field
                    for field in identity_fields
                    if (params.get(field) is None or params.get(field) == "")
                    and field not in spec.get("optional_request_identity_fields", [])
                ]
                if missing:
                    raise ValueError(
                        "Request identity gap: missing request fields "
                        + ",".join(missing)
                    )
                identity_json = json.dumps(
                    {field: params.get(field) for field in identity_fields},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                db.execute(
                    "INSERT INTO request_identity_map VALUES (?,?)",
                    [observation, identity_json],
                )
                identity_observations += 1
            relation.create_view("request_identity_source")
            raw_identity = 's."_row_identity"'
            if "_raw_row_identity" in columns:
                # Null generated fields on union_by_name legacy rows identify the
                # old payload-hash protocol. A partially populated modern row is
                # not silently reinterpreted as that legacy protocol.
                legacy = (
                    " AND ".join(
                        "s." + _identifier(field, columns) + " IS NULL"
                        for field in (
                            "_request_identity",
                            "_request_identity_status",
                            "_request_identity_missing",
                        )
                        if field in columns
                    )
                    or "TRUE"
                )
                raw_identity = (
                    'CASE WHEN s."_raw_row_identity" IS NOT NULL THEN s."_raw_row_identity" WHEN '
                    + legacy
                    + ' THEN s."_row_identity" ELSE NULL END'
                )
            if db.execute(
                "SELECT 1 FROM request_identity_source s WHERE "
                + raw_identity
                + " IS NULL OR NOT regexp_full_match(CAST("
                + raw_identity
                + " AS VARCHAR), '[a-f0-9]{64}') LIMIT 1"
            ).fetchone():
                raise ValueError(
                    "Request identity gap: missing or malformed raw row hash"
                )
            modern_fields = (
                "_request_identity",
                "_request_identity_status",
                "_request_identity_missing",
            )
            if "_raw_row_identity" not in columns:
                populated = " OR ".join(
                    _identifier(field, columns) + " IS NOT NULL"
                    for field in modern_fields
                    if field in columns
                )
                if populated and relation.filter(populated).limit(1).fetchone():
                    raise ValueError(
                        "Request identity gap: modern row lacks raw payload hash"
                    )
            elif not all(field in columns for field in modern_fields):
                if (
                    relation.filter('"_raw_row_identity" IS NOT NULL')
                    .limit(1)
                    .fetchone()
                ):
                    raise ValueError("Request identity gap: partial modern provenance")
            else:
                incomplete = " OR ".join(
                    "s." + _identifier(field, columns) + " IS NULL"
                    for field in modern_fields
                )
                inconsistent = (
                    "(s._raw_row_identity IS NOT NULL AND ("
                    + incomplete
                    + " OR s._row_identity IS NULL OR s._row_identity <> sha256(CAST(s._raw_row_identity AS VARCHAR) || chr(10) || m.identity_json) OR s._request_identity_missing <> '[]'))"
                )
                if db.execute(
                    "SELECT 1 FROM request_identity_source s JOIN request_identity_map m ON s._observation=m.observation WHERE "
                    + inconsistent
                    + " LIMIT 1"
                ).fetchone():
                    raise ValueError(
                        "Request identity gap: partial or inconsistent modern provenance"
                    )
            if "_request_identity" in columns:
                invalid = 's."_request_identity" IS NOT NULL AND s."_request_identity" <> m.identity_json'
                if "_request_identity_status" in columns:
                    invalid += " OR (s._request_identity_status IS NOT NULL AND s._request_identity_status <> 'complete')"
                if db.execute(
                    "SELECT 1 FROM request_identity_source s JOIN request_identity_map m ON s._observation=m.observation WHERE "
                    + invalid
                    + " LIMIT 1"
                ).fetchone():
                    raise ValueError(
                        "Request identity gap: stored provenance conflicts with observation"
                    )
            derived = {
                "_raw_row_identity",
                "_row_identity",
                "_request_identity",
                "_request_identity_status",
                "_request_identity_missing",
            }
            preserved = [
                "s." + _identifier(field, columns)
                for field in columns
                if field not in derived
            ]
            relation = db.sql(
                "SELECT "
                + ",".join(preserved)
                + ","
                + raw_identity
                + ' AS "_raw_row_identity", '
                + "sha256(CAST("
                + raw_identity
                + ' AS VARCHAR) || chr(10) || m.identity_json) AS "_row_identity", '
                + "m.identity_json AS _request_identity, 'complete' AS _request_identity_status, '[]' AS _request_identity_missing "
                + 'FROM request_identity_source s JOIN request_identity_map m ON s."_observation"=m.observation'
            )
            columns = relation.columns
        distinct_rows = bool(
            spec.get("preserve_distinct_rows", False) or identity_fields
        )
        if distinct_rows:
            if "_row_identity" not in columns:
                raise ValueError("Stored event dataset lacks source row identity")
            if (
                relation.filter(
                    '"_row_identity" IS NULL OR length(CAST("_row_identity" AS VARCHAR)) = 0'
                )
                .limit(1)
                .fetchone()
            ):
                raise ValueError("Stored event dataset has missing source row identity")
            # Some event APIs expose no stable event identifier. Preserve differing
            # source rows; repeated observations of exactly the same row dedupe.
            keys.append("_row_identity")
        if api_name in TEXT_CONTRACTS:
            # Text bodies and complete raw row identity survive latest-key views.
            # Existing files without row identity still retain differing bodies.
            keys += [
                f
                for f in ("_row_identity",) + TEXT_FIELDS
                if f in columns and f not in keys
            ]
        if (
            "ts_code" in columns
            and api_name not in CONCEPT_EXTRA_RUNTIME_CONTRACTS
            and api_name not in DC_EXTRA_RUNTIME_CONTRACTS
            and not api_name.startswith(("opt_", "sge_", "fx_", "us_"))
        ):
            # Canonicalize the old stored supplier spelling without rewriting
            # immutable partitions or merging its distinct historical identity.
            relation = relation.project(
                "* REPLACE (CASE WHEN regexp_full_match(ts_code, 'T[0-9]{6}[.](SH|SZ|BJ)') "
                "THEN split_part(ts_code, '.', 2) || split_part(ts_code, '.', 1) "
                "ELSE ts_code END AS ts_code)"
            )
        if api_name.startswith("hk_") and "ts_code" in columns:
            # Older captured HK delistings retained the supplier suffix. Project
            # only this known legacy shape before key deduplication and filters;
            # ! distinguishes retired listings from later reuse of the same code.
            relation = relation.project(
                "* REPLACE (CASE WHEN regexp_full_match(ts_code, '[0-9]{5}(![A-Z]{0,8})?[.]HK') "
                "THEN 'HK' || left(ts_code, length(ts_code) - 3) "
                "ELSE ts_code END AS ts_code)"
            )
        relation.create_view("stored")
        metadata = _metadata(manifest, release_id, api_name, aliases)
        metadata["source_api_names"] = sorted(source_apis)
        if api_name in ETF_BASKET_CONTRACTS:
            if "_raw_numeric_json" in columns:
                if (
                    relation.filter(
                        '"_raw_numeric_json" IS NULL OR NOT json_valid("_raw_numeric_json")'
                    )
                    .limit(1)
                    .fetchone()
                ):
                    raise ValueError(
                        "PCF numeric provenance missing or invalid; mixed legacy encoding gap"
                    )
                if (
                    relation.filter("json_type(\"_raw_numeric_json\") <> 'OBJECT'")
                    .limit(1)
                    .fetchone()
                ):
                    raise ValueError("PCF numeric provenance must be a JSON object")
                metadata["source_scalar_encodings"] = {
                    field: "text_with_row_raw_numeric_json_v1"
                    for field in spec["raw_numeric_fields"]
                    if field in columns
                }
                metadata["source_scalar_note"] = (
                    "Numeric source fields are nullable text; json.loads(row['_raw_numeric_json']) "
                    "recovers original scalar types, including 0, 0.0, '-' and null. "
                    "Arrow and JSONL do not automatically restore them. Select _raw_numeric_json "
                    "when projecting fields to retain exact scalar provenance."
                )
            else:
                metadata["source_scalar_encodings"] = {}
                metadata["source_scalar_note"] = (
                    "Legacy PCF numeric encoding unknown; never assume strings are encoded JSON."
                )
        if (
            api_name in LISTING_EXTRA_RUNTIME_CONTRACTS
            or api_name in CONCEPT_EXTRA_RUNTIME_CONTRACTS
            or api_name in DC_EXTRA_RUNTIME_CONTRACTS
            or api_name in RISK_EVENT_RUNTIME_CONTRACTS
        ):
            for note in ("date_axis_note", "namespace_note", "history_gap", "cap_note"):
                if spec.get(note):
                    metadata[note] = spec[note]
        if (
            api_name in DC_EXTRA_RUNTIME_CONTRACTS
            or api_name in RISK_EVENT_RUNTIME_CONTRACTS
        ):
            for note in (
                "history_note",
                "pit_gap",
                "saturation_gap",
                "category_gap",
                "member_namespace_note",
                "unit_note",
                "source_consistency_gap",
                "future_gap",
            ):
                if spec.get(note):
                    metadata[note] = spec[note]
        if api_name in FOREIGN_FINANCIAL_RUNTIME_CONTRACTS:
            for note in (
                "date_filter_semantics",
                "source_namespace",
                "history_gap",
                "discovery_gap",
                "coverage_gap",
                "pit_gap",
                "refresh_gap",
                "unit_gap",
                "cap_gap",
                "period_gap",
                "saturation_gap",
                "field_coverage_gap",
                "independent_permission",
                "permission_status",
            ):
                if spec.get(note):
                    metadata[note] = spec[note]
        if api_name in ACCOUNT_HISTORY_RUNTIME_CONTRACTS:
            for name, value in spec.items():
                if name.endswith(("_gap", "_note")) or name in (
                    "field_metadata", "hidden_fields", "permission_status", "date_field",
                    "stopped_updates", "history_bound_verified", "row_cap_verified",
                    "documented_row_cap", "documented_history_start_month", "documented_history_end",
                ):
                    metadata[name] = value
            if api_name == "stk_account_old":
                period_columns = {"_period_start", "_period_end", "_period_projection_status"}
                metadata["period_projection_columns_present"] = period_columns.issubset(columns)
                metadata["period_projection_unverified_rows"] = (
                    db.execute("SELECT count(*) FROM stored WHERE _period_projection_status IS DISTINCT FROM 'projected' OR _period_start IS NULL OR _period_end IS NULL").fetchone()[0]
                    if period_columns.issubset(columns) else relation.count("*").fetchone()[0]
                )
                metadata["period_date_semantics"] = spec["local_date_filter_note"]
        if api_name in SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS:
            for name, value in spec.items():
                if name.endswith(("_gap", "_note")) or name in (
                    "field_metadata", "hidden_fields", "permission_status", "date_field",
                    "stop_date", "update_status", "history_start", "history_bound_verified",
                    "row_cap", "row_cap_verified", "minimum_points", "independent_permission",
                ):
                    metadata[name] = value
        if api_name in REALTIME_RUNTIME_CONTRACTS or api_name in BOND_EXTRA_RUNTIME_CONTRACTS or api_name in CALENDAR_EXTRA_RUNTIME_CONTRACTS or api_name in FACTOR_LIBRARY_RUNTIME_CONTRACTS or api_name in HISTORY_MINUTES_RUNTIME_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_gaps", "field_metadata", "hidden_fields", "permission_status",
                    "date_field", "source_namespace", "independent_permission",
                ):
                    metadata[note] = value
        if api_name in CROSS_ASSET_RUNTIME_CONTRACTS or api_name in MARKET_SENTIMENT_RUNTIME_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_metadata",
                    "hidden_fields",
                    "source_namespace",
                    "history_bound_verified",
                    "documented_minimum_points",
                    "documented_rate_tiers",
                    "field_gaps",
                    "permission_status",
                    "date_field",
                ):
                    metadata[note] = value
        if api_name in STOCK_CONTEXT_RUNTIME_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_gaps",
                    "hidden_fields",
                    "permission_status",
                    "date_field",
                    "documented_update_time",
                ):
                    metadata[note] = value
        if api_name in TECHNICAL_EXTRA_RUNTIME_CONTRACTS:
            for note in (
                "namespace_note",
                "history_gap",
                "pit_gap",
                "unit_note",
                "adjustment_note",
                "formula_gap",
                "pre_close_gap",
                "pagination_gap",
                "saturation_gap",
                "refresh_gap",
                "field_gaps",
            ):
                if spec.get(note):
                    metadata[note] = spec[note]
        if api_name in RRG_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_gaps",
                    "hidden_fields",
                    "permission_status",
                    "date_field",
                    "history_bound_verified",
                    "row_cap_verified",
                ):
                    metadata[note] = value
        if api_name in LEGACY_CONNECT_RUNTIME_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_gaps",
                    "hidden_fields",
                    "permission_status",
                    "date_field",
                    "history_bound_verified",
                    "row_cap_verified",
                    "source_content_status",
                    "documented_requests_per_minute",
                ):
                    metadata[note] = value
        if api_name in OFFCATALOG_RUNTIME_CONTRACTS:
            for note, value in spec.items():
                if note.endswith(("_gap", "_note")) or note in (
                    "field_gaps",
                    "hidden_fields",
                    "permission_status",
                    "date_field",
                    "history_bound_verified",
                    "row_cap_verified",
                    "minimum_points",
                ):
                    metadata[note] = value
        if identity_fields:
            metadata["request_identity_fields"] = list(identity_fields)
            metadata["request_identity_status"] = "verified_from_immutable_observations"
            metadata["request_identity_observations"] = identity_observations
            metadata["request_identity_note"] = (
                "Legacy identity is reconstructed only in this query; no Parquet files are rewritten. Missing identity raises an explicit gap."
            )
        if distinct_rows:
            metadata["deduplication_mode"] = "distinct_supplier_rows"
            metadata["row_identity_note"] = spec.get(
                "row_identity_note",
                spec.get("revision_gap", "Differing source rows are retained."),
            )
        yield db, columns, keys, metadata


def _date(value):
    if isinstance(value, datetime):
        raise ValueError("Date filters require a calendar date, not a timestamp")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError("Expected YYYYMMDD or YYYY-MM-DD date")
    try:
        if re.fullmatch(r"[0-9]{8}", value):
            return datetime.strptime(value, "%Y%m%d").date().isoformat()
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("Expected a valid calendar date") from exc


def _minute_time(value, *, end=False):
    """Naive supplier wall time only; dates select the whole wall-clock day."""
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.microsecond:
            raise ValueError("Minute bounds require seconds and no inferred timezone")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        return datetime.strptime(value.replace("T", " "), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    return _date(value) + (" 23:59:59" if end else " 00:00:00")


def _as_of(value):
    if value is None:
        return None
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise ValueError("as_of requires an ISO timestamp with timezone") from exc
    if (
        not isinstance(parsed, datetime)
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError("as_of requires an ISO timestamp with timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _date_expression(field, columns):
    column = "CAST(" + _identifier(field, columns) + " AS VARCHAR)"
    if field == "month":
        return "CAST(TRY_STRPTIME(" + column + ", '%Y%m') AS DATE)"
    if field == "report_date":
        return (
            "COALESCE(CAST(TRY_STRPTIME("
            + column
            + ", '%Y%m%d') AS DATE),CAST(TRY_STRPTIME("
            + column
            + ", '%Y%m') AS DATE),TRY_CAST("
            + column
            + " AS DATE))"
        )
    if field == "year":
        return (
            "TRY_CAST(CASE WHEN regexp_full_match("
            + column
            + ", '[0-9]{4}') THEN "
            + column
            + " || '-01-01' END AS DATE)"
        )
    if field == "quarter":
        return (
            "TRY_CAST(CASE WHEN regexp_full_match("
            + column
            + ", '[0-9]{4}Q[1-4]') THEN "
            "substr("
            + column
            + ",1,4) || '-' || lpad(CAST((CAST(right("
            + column
            + ",1) AS INTEGER)-1)*3+1 AS VARCHAR),2,'0') || '-01' END AS DATE)"
        )
    return (
        "COALESCE(CAST(TRY_STRPTIME("
        + column
        + ", '%Y%m%d') AS DATE),TRY_CAST("
        + column
        + " AS DATE))"
    )


def _default_date_field(api_name, columns):
    if api_name in RRG_CONTRACTS:
        return RRG_CONTRACTS[api_name]["date_field"]
    if api_name in REALTIME_RUNTIME_CONTRACTS:
        return REALTIME_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in ACCOUNT_HISTORY_RUNTIME_CONTRACTS:
        return "date"
    if api_name in HISTORY_MINUTES_RUNTIME_CONTRACTS:
        return "trade_time"
    if api_name in CALENDAR_EXTRA_RUNTIME_CONTRACTS:
        return CALENDAR_EXTRA_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in FACTOR_LIBRARY_RUNTIME_CONTRACTS:
        return FACTOR_LIBRARY_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in BOND_EXTRA_RUNTIME_CONTRACTS:
        return BOND_EXTRA_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in CROSS_ASSET_RUNTIME_CONTRACTS or api_name in MARKET_SENTIMENT_RUNTIME_CONTRACTS:
        return "trade_date"
    if api_name in FOREIGN_FINANCIAL_RUNTIME_CONTRACTS:
        return "end_date"
    if api_name in STOCK_CONTEXT_RUNTIME_CONTRACTS:
        return STOCK_CONTEXT_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in RISK_EVENT_RUNTIME_CONTRACTS:
        return RISK_EVENT_RUNTIME_CONTRACTS[api_name]["date_field"]
    if api_name in OFFCATALOG_RUNTIME_CONTRACTS:
        return OFFCATALOG_RUNTIME_CONTRACTS[api_name]["date_field"]
    return next((field for field in DATE_FIELDS if field in columns), None)


def _default_code_field(api_name, columns):
    keys = KEYS.get(api_name, ())
    return (
        "index_code"
        if "ts_code" not in keys and "index_code" in keys and "index_code" in columns
        else "ts_code"
    )


def _query(
    db,
    columns,
    keys,
    api_name,
    *,
    fields=None,
    date_field=None,
    start_date=None,
    end_date=None,
    codes=None,
    code_field=None,
    keyword=None,
    keyword_fields=None,
    as_of=None,
    limit=None,
):
    selected = list(columns) if fields is None else fields
    if (
        not isinstance(selected, (list, tuple))
        or not selected
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("fields must be a nonempty list of unique stored field names")
    projection = ",".join(_identifier(f, columns) for f in selected)
    params, observed_filter, filters = [], "", []
    cutoff = _as_of(as_of)
    if cutoff:
        observed_filter = (
            'WHERE TRY_CAST("_fetched_at" AS TIMESTAMPTZ) <= CAST(? AS TIMESTAMPTZ)'
        )
        params.append(cutoff)
    if start_date is not None or end_date is not None:
        date_field = date_field or _default_date_field(api_name, columns)
        old_period = api_name == "stk_account_old"
        if old_period:
            if date_field not in ("date", "_period_start", "_period_end"):
                raise ValueError("Choose date overlap, _period_start or _period_end for old account periods")
            if not {"_period_start", "_period_end", "_period_projection_status"}.issubset(columns):
                raise ValueError("period_projection_unverified: stored projection missing; raw data remains available")
            invalid = "(_period_projection_status IS DISTINCT FROM 'projected' OR _period_start IS NULL OR _period_end IS NULL)"
            check_params = []
            if cutoff:
                invalid += ' AND TRY_CAST("_fetched_at" AS TIMESTAMPTZ) <= CAST(? AS TIMESTAMPTZ)'
                check_params.append(cutoff)
            if db.execute("SELECT 1 FROM stored WHERE " + invalid + " LIMIT 1", check_params).fetchone():
                raise ValueError("period_projection_unverified: date filtering could omit unrecognized source periods; raw unfiltered read remains available")
        minute = (api_name in HISTORY_MINUTES_RUNTIME_CONTRACTS and date_field == "trade_time") or (api_name in REALTIME_RUNTIME_CONTRACTS and date_field in ("time", "trade_time"))
        if minute:
            column = "CAST(" + _identifier(date_field, columns) + " AS VARCHAR)"
            expression = "TRY_STRPTIME(replace(" + column + ", 'T', ' '), '%Y-%m-%d %H:%M:%S')"
            if api_name in REALTIME_RUNTIME_CONTRACTS and db.execute("SELECT 1 FROM stored WHERE " + expression + " IS NULL LIMIT 1").fetchone():
                raise ValueError("realtime_timestamp_unverified: cannot filter unknown source timestamp without inventing date/timezone")
        elif api_name == "fund_sales_vol" and date_field == "year" and "quarter" in columns:
            year = "CAST(" + _identifier("year", columns) + " AS VARCHAR)"
            quarter = "CAST(" + _identifier("quarter", columns) + " AS VARCHAR)"
            expression = (
                "TRY_CAST(CASE WHEN regexp_full_match("
                + year
                + ", '[0-9]{4}') AND regexp_full_match("
                + quarter
                + ", 'Q[1-4]') THEN "
                + year
                + " || '-' || lpad(CAST((CAST(right("
                + quarter
                + ",1) AS INTEGER)-1)*3+1 AS VARCHAR),2,'0') || '-01' END AS DATE)"
            )
        else:
            expression = _date_expression(
                "_period_end" if old_period and date_field == "date" else date_field, columns
            )
        start = (_minute_time(start_date) if minute else _date(start_date)) if start_date is not None else None
        end = (_minute_time(end_date, end=True) if minute else _date(end_date)) if end_date is not None else None
        if start and end and start > end:
            raise ValueError("start_date is after end_date")
        for value, operator in ((start, ">="), (end, "<=")):
            if value:
                boundary = (
                    _date_expression("_period_start", columns)
                    if old_period and date_field == "date" and operator == "<="
                    else expression
                )
                filters.append(boundary + operator + ("CAST(? AS TIMESTAMP)" if minute else "CAST(? AS DATE)"))
                params.append(value)
    elif date_field is not None:
        _identifier(date_field, columns)
    if codes is not None:
        codes = [codes] if isinstance(codes, str) else codes
        if not isinstance(codes, (list, tuple)) or any(
            not isinstance(c, str) or not c for c in codes
        ):
            raise ValueError("codes must contain stored identifiers")
        code_field = code_field or _default_code_field(api_name, columns)
        column = _identifier(code_field, columns)
        mapping_source = code_field in ("o_code", "n_code") and {
            "o_code",
            "n_code",
        }.issubset(columns)
        concept_source = (api_name == "limit_cpt_list" and code_field == "ts_code") or (
            (
                api_name in CONCEPT_EXTRA_RUNTIME_CONTRACTS
                or api_name in DC_EXTRA_RUNTIME_CONTRACTS
            )
            and code_field in ("ts_code", "con_code", "leading_code")
        )
        source_identifier = code_field.startswith("source_")
        if not (mapping_source or concept_source or source_identifier) and any(
            re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", c) for c in codes
        ):
            raise ValueError("Use internal prefix stock codes, for example SH600036")
        filters.append(
            column + " IN (" + ",".join("?" for _ in codes) + ")" if codes else "false"
        )
        params.extend(codes)
    if keyword is not None:
        if not isinstance(keyword, str) or not keyword:
            raise ValueError("keyword must be nonempty text")
        search_fields = (
            keyword_fields
            if keyword_fields is not None
            else [f for f in TEXT_FIELDS if f in columns]
        )
        if not isinstance(search_fields, (list, tuple)) or not search_fields:
            raise ValueError("Choose at least one stored keyword field")
        expressions = []
        for field in search_fields:
            expressions.append(
                "contains(lower(COALESCE(CAST("
                + _identifier(field, columns)
                + " AS VARCHAR),'')),lower(?))"
            )
            params.append(keyword)
        filters.append("(" + " OR ".join(expressions) + ")")
    elif keyword_fields is not None:
        raise ValueError("keyword_fields requires keyword")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit < 2**63
    ):
        raise ValueError("limit must be a nonnegative integer")
    partition = ",".join(_identifier(key, columns) for key in keys)
    order = 'TRY_CAST("_fetched_at" AS TIMESTAMPTZ) DESC NULLS LAST,"_observation" DESC'
    sql = (
        "WITH observed AS (SELECT * FROM stored "
        + observed_filter
        + "), latest AS (SELECT * FROM observed QUALIFY row_number() OVER (PARTITION BY "
        + partition
        + " ORDER BY "
        + order
        + ")=1) SELECT "
        + projection
        + " FROM latest"
    )
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    # Stable output independent of file inventory order; all keys remain in latest
    # even when callers request a narrower projection.
    sql += " ORDER BY " + partition + "," + order
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params)


def dataset_schema(root, release_id, api_name):
    """Return verified schema, keys and coverage without acquiring missing data."""
    with _dataset(root, release_id, api_name) as (db, columns, keys, metadata):
        table = db.execute("SELECT * FROM stored LIMIT 0").fetch_arrow_table()
        return {
            **metadata,
            "fields": [
                {"name": f.name, "type": str(f.type), "nullable": f.nullable}
                for f in table.schema
            ],
            "keys": keys,
            "default_date_field": _default_date_field(api_name, columns),
            "default_code_field": _default_code_field(api_name, columns),
            "period_date_semantics": metadata.get("period_date_semantics", "month and quarter filters use the period's first calendar day"),
        }


def read_dataset(root, release_id, api_name, **filters):
    """Return an Arrow table; fields/date/codes/keyword/as_of/limit are optional.

    as_of must include a timezone and applies BEFORE latest-version selection;
    date/code/keyword filters apply afterwards. Default returns all raw/source
    fields. Arrow schema metadata carries coverage, pinned release and the
    observation-time caveat. Legacy releases mark observation history incomplete.
    """
    with _dataset(root, release_id, api_name) as (db, columns, keys, metadata):
        table = _query(db, columns, keys, api_name, **filters).fetch_arrow_table()
        metadata["as_of"] = _as_of(filters.get("as_of"))
        return table.replace_schema_metadata(
            {b"tushare": json.dumps(metadata, ensure_ascii=False).encode("utf-8")}
        )


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        import base64

        return {"$binary_base64": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Unsupported JSONL value: {type(value).__name__}")


def export_jsonl(root, release_id, api_name, destination, **filters):
    """Stream a local query to atomic JSONL outside the immutable dataset root."""
    destination = Path(destination).expanduser().absolute()
    if (
        destination.is_symlink()
        or Path(root).resolve() in destination.resolve().parents
    ):
        raise ValueError(
            "Export must not overwrite immutable dataset storage or symlinks"
        )
    with _dataset(root, release_id, api_name) as (db, columns, keys, metadata):
        batches = _query(db, columns, keys, api_name, **filters).fetch_record_batch(
            65536
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".tushare-export-", dir=destination.parent
        )
        count, size, digest = 0, 0, hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as stream:
                for batch in batches:
                    for row in batch.to_pylist():
                        payload = (
                            json.dumps(
                                row,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                default=_json_default,
                                allow_nan=False,
                            )
                            + "\n"
                        ).encode("utf-8")
                        stream.write(payload)
                        digest.update(payload)
                        count += 1
                        size += len(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {
            **metadata,
            "path": str(destination),
            "rows": count,
            "bytes": size,
            "sha256": digest.hexdigest(),
            "as_of": _as_of(filters.get("as_of")),
        }
