#!/usr/bin/env python3
"""Prepare one offline RRG membership/ETF point without granting PIT readiness."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from backend.shared.tushare_pipeline import manifest_at  # noqa: E402
from backend.shared.tushare_store import read_dataset  # noqa: E402

OUTPUTS = {
    "industry_members": "data/quantdb/2_base_sector/sector_concept/sector_members.parquet",
    "industry_member_vintages": "sources/citic-member-forward-vintages.parquet",
    "etf_universe": "sources/etf-universe.parquet",
    "etf_index_mapping": "sources/etf-index-mapping-candidates.parquet",
    "etf_prices": "data/quantdb/4_bond_etf/etf_kline/tushare-execution-point.parquet",
    "etf_holdings": "data/quantdb/4_bond_etf/etf_pcf/etf_components.parquet",
    "etf_pcf": "data/quantdb/4_bond_etf/etf_pcf/etf_pcf.parquet",
}
OBSERVATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
GAPS = [
    "ci_index_member has effective dates but no verified publication/known_at time; current observations cannot be backfilled as historical knowledge",
    "CITIC classification versions, methodology and revisions still require authoritative historical evidence",
    "ETF list records are an observed candidate universe, not a point-in-time industry-to-ETF mapping",
    "One execution-day price and factor do not prove full-history continuity, corporate-action treatment or tradability at the open",
    "fund_portfolio is a partial periodic stock disclosure; its rows are not a complete daily ETF exposure or PCF",
    "The single-point holding search is bounded to 550 days; no result in that window does not prove earlier disclosures absent",
    "PCF trade_date is applicability, while publication time and historical revisions remain unverified",
    "Without a signal timestamp, fixed observations are usable only from the next "
    "Asia/Shanghai calendar day; this does not prove earlier publication or historical availability",
    "A value episode extends backward only across retained same-scope snapshots when "
    "all API coverage is done; otherwise it starts at the selected row observation",
]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def date8(value, label, *, optional=False):
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"Invalid {label}")
    datetime.strptime(value, "%Y%m%d")
    return value


def instant(value, label):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid {label}") from exc
    else:
        raise ValueError(f"Invalid {label}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Invalid {label}")
    return parsed.astimezone(timezone.utc)


def checked_fixed_file(root, manifest, relative):
    expected = manifest.get("files", {}).get(relative)
    path = root / relative
    resolved_root = root.resolve()
    if (
        not isinstance(expected, dict)
        or not isinstance(expected.get("bytes"), int)
        or not re.fullmatch(r"[a-f0-9]{64}", str(expected.get("sha256", "")))
        or path.is_symlink()
        or not path.is_file()
        or resolved_root not in path.resolve().parents
        or path.stat().st_size != expected["bytes"]
        or sha(path) != expected["sha256"]
    ):
        raise ValueError("Fixed provenance file is missing or invalid")
    return path, expected["sha256"]


def row_key(row, fields):
    return tuple(row.get(field) for field in fields)


def fixed_observation_episodes(
    root,
    manifest,
    api_name,
    current_rows,
    current_key_fields,
    entity_fields,
    value_fields,
):
    """Return the current value's retained-observation episode provenance."""
    import pyarrow.parquet as pq

    if not current_rows:
        return {}
    current = {row_key(row, current_key_fields): row for row in current_rows}
    if len(current) != len(current_rows) or any(
        row_key(row, entity_fields)[0] in (None, "") for row in current_rows
    ):
        raise ValueError("Fixed source identity is missing")
    wanted_entities = {row_key(row, entity_fields) for row in current_rows}
    paths = sorted(
        {
            row.get("path")
            for row in manifest.get("datasets", [])
            if row.get("api_name") == api_name
        }
    )
    if not paths:
        raise ValueError("Fixed vintage partitions are unavailable")
    observations = {}
    snapshots = {}

    def observation_metadata(observation, observed_at):
        if observation in observations:
            metadata = observations[observation]
            if metadata["observed_at"] != observed_at:
                raise ValueError("Fixed observation provenance is inconsistent")
            return metadata
        relative = "observations/" + observation
        path, observation_sha = checked_fixed_file(root, manifest, relative)
        payload = json.loads(path.read_bytes())
        request = payload.get("request")
        object_sha = payload.get("object_sha256")
        if (
            not isinstance(request, dict)
            or request.get("api_name") != api_name
            or not isinstance(request.get("params"), dict)
            or not re.fullmatch(r"[a-f0-9]{64}", str(object_sha or ""))
            or instant(payload.get("fetched_at"), "observation fetched_at")
            != observed_at
        ):
            raise ValueError("Fixed observation provenance is inconsistent")
        _, stored_object_sha = checked_fixed_file(
            root, manifest, f"objects/{object_sha}.json"
        )
        if stored_object_sha != object_sha:
            raise ValueError("Fixed object content address is inconsistent")
        scope = json.dumps(
            {"fields": request.get("fields"), "params": request["params"]},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        metadata = {
            "observed_at": observed_at,
            "scope": scope,
            "source_object_sha256": object_sha,
            "source_observation": observation,
            "source_observation_sha256": observation_sha,
        }
        observations[observation] = metadata
        return metadata

    columns = list(
        dict.fromkeys(
            (*entity_fields, *value_fields, "_fetched_at", "_observation")
        )
    )
    for relative in paths:
        if not isinstance(relative, str) or not re.fullmatch(
            r"parquet/[a-f0-9]{64}\.parquet", relative
        ):
            raise ValueError("Fixed vintage partition is invalid")
        path, _ = checked_fixed_file(root, manifest, relative)
        table = pq.read_table(path, columns=columns)
        for row in table.to_pylist():
            observed_at = instant(row.get("_fetched_at"), "fixed observation time")
            observation = row.get("_observation")
            if (
                not isinstance(observation, str)
                or Path(observation).name != observation
            ):
                raise ValueError("Fixed observation reference is invalid")
            observation_metadata(observation, observed_at)
            snapshot = snapshots.setdefault(observation, {})
            entity = row_key(row, entity_fields)
            if entity not in wanted_entities:
                continue
            snapshot.setdefault(entity, set()).add(row_key(row, value_fields))

    coverage = [
        row
        for row in manifest.get("coverage_by_api", [])
        if row.get("api_name") == api_name
    ]
    continuity_provable = bool(coverage) and all(
        row.get("state") == "done" for row in coverage
    )
    result = {}
    for identity, current_row in current.items():
        entity = row_key(current_row, entity_fields)
        value = row_key(current_row, value_fields)
        selected_name = current_row.get("_observation")
        selected_at = instant(
            current_row.get("_fetched_at"), "selected fixed observation time"
        )
        if not isinstance(selected_name, str) or selected_name not in observations:
            raise ValueError("Selected current row is missing retained provenance")
        selected = observation_metadata(selected_name, selected_at)
        if snapshots.get(selected_name, {}).get(entity) != {value}:
            raise ValueError("Selected current row is ambiguous in retained snapshot")
        episode = selected
        if continuity_provable:
            sequence = sorted(
                (
                    metadata
                    for name, metadata in observations.items()
                    if metadata["scope"] == selected["scope"]
                    and (
                        metadata["observed_at"], metadata["source_observation"]
                    )
                    <= (selected_at, selected_name)
                ),
                key=lambda row: (row["observed_at"], row["source_observation"]),
            )
            selected_position = next(
                index
                for index, metadata in enumerate(sequence)
                if metadata["source_observation"] == selected_name
            )
            for prior in reversed(sequence[:selected_position]):
                values = snapshots.get(prior["source_observation"], {}).get(entity)
                if values != {value}:
                    break
                episode = prior

        observed_at = episode["observed_at"]
        observation_local_date = observed_at.astimezone(
            OBSERVATION_TIMEZONE
        ).strftime("%Y%m%d")
        selected_local_date = selected_at.astimezone(OBSERVATION_TIMEZONE).strftime(
            "%Y%m%d"
        )
        result[identity] = {
            "episode_start_observation_at": observed_at.isoformat(),
            "observation_local_date": observation_local_date,
            "forward_valid_from": (
                datetime.strptime(observation_local_date, "%Y%m%d")
                + timedelta(days=1)
            ).strftime("%Y%m%d"),
            "selected_fixed_observation_at": selected_at.isoformat(),
            "selected_observation_local_date": selected_local_date,
            "selected_forward_valid_from": (
                datetime.strptime(selected_local_date, "%Y%m%d")
                + timedelta(days=1)
            ).strftime("%Y%m%d"),
            "source_object_sha256": episode["source_object_sha256"],
            "source_observation": episode["source_observation"],
            "source_observation_sha256": episode[
                "source_observation_sha256"
            ],
            "selected_source_object_sha256": selected[
                "source_object_sha256"
            ],
            "selected_source_observation": selected["source_observation"],
            "selected_source_observation_sha256": selected[
                "source_observation_sha256"
            ],
            "episode_continuity_proven": continuity_provable,
        }
    return result


def distinct(rows, keys, label):
    result = {}
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        if any(value in (None, "") for value in key) or key in result:
            raise ValueError(f"Missing or duplicate {label} key")
        result[key] = row
    return result


def next_session(calendar, signal_date, execution_date):
    signal_date = date8(signal_date, "signal date")
    execution_date = date8(execution_date, "execution date")
    by_day = {}
    for row in calendar:
        if row.get("exchange") != "SSE":
            continue
        day = date8(row.get("cal_date"), "calendar date")
        flag = str(row.get("is_open"))
        if flag not in ("0", "1") or (day in by_day and by_day[day] != flag):
            raise ValueError("Invalid/conflicting SSE calendar")
        by_day[day] = flag
    lo, hi = (
        datetime.strptime(value, "%Y%m%d") for value in (signal_date, execution_date)
    )
    if lo >= hi:
        raise ValueError("Execution date must follow signal date")
    expected = {
        (lo + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((hi - lo).days + 1)
    }
    if expected - by_day.keys():
        raise ValueError("Missing natural-day calendar evidence")
    following = min(
        (day for day, flag in by_day.items() if day > signal_date and flag == "1"),
        default=None,
    )
    if following != execution_date:
        raise ValueError("Execution date is not the next SSE session")
    return following


def membership_inputs(rows, signal_date):
    output = []
    for row in rows:
        start = date8(row.get("in_date"), "member in_date")
        end = date8(row.get("out_date"), "member out_date", optional=True)
        if end and end < start:
            raise ValueError("Member effective interval is reversed")
        if not row.get("l1_code") or not row.get("ts_code"):
            raise ValueError("Member source identity is missing")
        output.append(
            {
                "SectorCode": row["l1_code"],
                "Symbol": row["ts_code"],
                "effective_from": start,
                "effective_to": end,
                "known_at": None,
                "SectorType": "中信一级",
                "source_symbol": row.get("source_ts_code"),
                "source_l1_code": row.get("source_l1_code"),
                "source_observation": row.get("_observation"),
                "interval_contains_signal_candidate": start <= signal_date
                and (end is None or signal_date < end),
                "effective_interval_semantics_verified": False,
                "known_at_verified": False,
            }
        )
    output.sort(
        key=lambda row: (row["SectorCode"], row["Symbol"], row["effective_from"])
    )
    return output


MEMBER_VINTAGE_KEY = (
    "l1_code",
    "l2_code",
    "l3_code",
    "ts_code",
    "in_date",
    "out_date",
)
ETF_INDEX_MAPPING_KEY = ("ts_code", "index_code", "index_name")
ETF_ENTITY_KEY = ("ts_code",)
ETF_INDEX_VALUE_KEY = ("index_code", "index_name")


def membership_vintages(rows, provenance, signal_date, release_id):
    output = []
    for row in rows:
        start = date8(row.get("in_date"), "member in_date")
        end = date8(row.get("out_date"), "member out_date", optional=True)
        identity = row_key(row, MEMBER_VINTAGE_KEY)
        source = provenance[identity]
        forward = (
            source["forward_valid_from"] <= signal_date
            and source["selected_forward_valid_from"] <= signal_date
        )
        output.append(
            {
                "SectorCode": row.get("l1_code"),
                "Symbol": row.get("ts_code"),
                "effective_from": start,
                "effective_to": end,
                "episode_start_observation_at": source[
                    "episode_start_observation_at"
                ],
                "observation_local_date": source["observation_local_date"],
                "forward_valid_from": source["forward_valid_from"],
                "selected_fixed_observation_at": source[
                    "selected_fixed_observation_at"
                ],
                "selected_observation_local_date": source[
                    "selected_observation_local_date"
                ],
                "selected_forward_valid_from": source[
                    "selected_forward_valid_from"
                ],
                "forward_usable_for_signal": forward
                and start <= signal_date
                and (end is None or signal_date < end),
                "known_at_basis": "fixed_release_observation",
                "source_release_id": release_id,
                "source_object_sha256": source["source_object_sha256"],
                "source_observation": source["source_observation"],
                "source_observation_sha256": source[
                    "source_observation_sha256"
                ],
                "selected_source_object_sha256": source[
                    "selected_source_object_sha256"
                ],
                "selected_source_observation": source[
                    "selected_source_observation"
                ],
                "selected_source_observation_sha256": source[
                    "selected_source_observation_sha256"
                ],
                "episode_continuity_proven": source[
                    "episode_continuity_proven"
                ],
                "historical_known_at_verified": False,
                "historical_mapping_verified": False,
            }
        )
    output.sort(
        key=lambda row: (
            row["SectorCode"],
            row["Symbol"],
            row["effective_from"],
            row["episode_start_observation_at"],
        )
    )
    return output


def candidate_universe(etf_basic, fund_basic, execution_date):
    etfs = distinct(etf_basic, ("ts_code",), "ETF")
    funds = distinct(fund_basic, ("ts_code",), "fund")
    output, candidates, unsupported = [], set(), set()
    for (code,), row in sorted(etfs.items()):
        fund = funds.get((code,), {})
        listed = date8(
            row.get("list_date") or fund.get("list_date"),
            "ETF list_date",
            optional=True,
        )
        delisted = date8(fund.get("delist_date"), "ETF delist_date", optional=True)
        date_eligible = bool(
            listed
            and listed <= execution_date
            and (delisted is None or execution_date <= delisted)
        )
        exchange = row.get("exchange")
        exchange_supported = exchange in ("SH", "SZ") and code.startswith(exchange)
        if date_eligible and exchange_supported:
            candidates.add(code)
        elif date_eligible:
            unsupported.add(code)
        output.append(
            {
                "EtfCode": code,
                "source_etf_code": row.get("source_ts_code"),
                "exchange": exchange,
                "index_code": row.get("index_code"),
                "index_name": row.get("index_name"),
                "list_date": listed,
                "delist_date": delisted,
                "observed_list_status": row.get("list_status"),
                "date_eligible_candidate": date_eligible and exchange_supported,
                "historical_universe_verified": False,
                "industry_mapping_verified": False,
                "source_observation": row.get("_observation"),
            }
        )
    return output, candidates, unsupported


def etf_index_mapping_candidates(rows, provenance, signal_date, release_id):
    output = []
    for row in rows:
        if not row.get("index_code"):
            continue
        source = provenance[row_key(row, ETF_INDEX_MAPPING_KEY)]
        output.append(
            {
                "EtfCode": row.get("ts_code"),
                "source_etf_code": row.get("source_ts_code"),
                "index_code": row.get("index_code"),
                "index_name": row.get("index_name"),
                "episode_start_observation_at": source[
                    "episode_start_observation_at"
                ],
                "observation_local_date": source["observation_local_date"],
                "forward_valid_from": source["forward_valid_from"],
                "selected_fixed_observation_at": source[
                    "selected_fixed_observation_at"
                ],
                "selected_observation_local_date": source[
                    "selected_observation_local_date"
                ],
                "selected_forward_valid_from": source[
                    "selected_forward_valid_from"
                ],
                "forward_usable_for_signal": (
                    source["forward_valid_from"] <= signal_date
                    and source["selected_forward_valid_from"] <= signal_date
                ),
                "mapping_basis": "etf_basic.index_code_current_observation",
                "source_release_id": release_id,
                "source_object_sha256": source["source_object_sha256"],
                "source_observation": source["source_observation"],
                "source_observation_sha256": source[
                    "source_observation_sha256"
                ],
                "selected_source_object_sha256": source[
                    "selected_source_object_sha256"
                ],
                "selected_source_observation": source[
                    "selected_source_observation"
                ],
                "selected_source_observation_sha256": source[
                    "selected_source_observation_sha256"
                ],
                "episode_continuity_proven": source[
                    "episode_continuity_proven"
                ],
                "historical_mapping_verified": False,
            }
        )
    output.sort(key=lambda row: (row["EtfCode"], row["index_code"]))
    return output


def finite(value, *, positive=False):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def etf_price_inputs(prices, adjustments, candidates, execution_date):
    price_map = distinct(prices, ("trade_date", "ts_code"), "ETF price")
    factor_map = distinct(adjustments, ("trade_date", "ts_code"), "ETF factor")
    output, valid_codes = [], set()
    for (day, code), row in sorted(price_map.items()):
        if date8(day, "ETF price date") != execution_date or code not in candidates:
            continue
        factor = factor_map.get((day, code), {}).get("adj_factor")
        valid = all(
            (
                finite(row.get("open"), positive=True),
                finite(row.get("close"), positive=True),
                finite(row.get("vol")),
                finite(row.get("amount")),
                finite(factor, positive=True),
            )
        )
        if valid:
            valid_codes.add(code)
        output.append(
            {
                "EtfCode": code,
                "time": day,
                "open": row.get("open"),
                "close": row.get("close"),
                "volume": row.get("vol"),
                "amount": row.get("amount"),
                "adj_factor": factor,
                "source_volume_unit": "lot",
                "source_amount_unit": "thousand_CNY",
                "exact_execution_row": True,
                "execution_input_valid": valid,
                "open_tradability_verified": False,
                "source_observation": row.get("_observation"),
                "factor_observation": factor_map.get((day, code), {}).get(
                    "_observation"
                ),
            }
        )
    return output, valid_codes


def holding_inputs(rows, candidates, signal_date):
    groups = {}
    for row in rows:
        code = row.get("ts_code")
        ann = date8(row.get("ann_date"), "holding announcement date")
        end = date8(row.get("end_date"), "holding report date")
        if ann >= signal_date:
            raise ValueError("Holdings query includes same-day or future announcements")
        if code in candidates:
            groups.setdefault(code, []).append((ann, end, row))
    output, selected_periods = [], {}
    for code, values in sorted(groups.items()):
        latest = max((ann, end) for ann, end, _ in values)
        selected_periods[code] = latest
        for ann, end, row in values:
            if (ann, end) != latest:
                continue
            output.append(
                {
                    "EtfCode": code,
                    "ComponentCode": row.get("symbol"),
                    "source_component_code": row.get("source_symbol"),
                    "report_date": end,
                    "announcement_date": ann,
                    "market_value": row.get("mkv"),
                    "stock_market_value_ratio": row.get("stk_mkv_ratio"),
                    "known_before_signal_day": True,
                    "complete_exposure_verified": False,
                    "source_observation": row.get("_observation"),
                }
            )
    return output, selected_periods


def pcf_inputs(rows, candidates, execution_date, source_api):
    output = []
    for row in rows:
        day = date8(row.get("trade_date"), "PCF trade date")
        code = row.get("ts_code")
        if day != execution_date or code not in candidates:
            continue
        output.append(
            {
                "EtfCode": code,
                "ComponentCode": row.get("con_code"),
                "component_name": row.get("con_name"),
                "tradingDay": day,
                "quantity_raw": row.get("qty"),
                "cash_substitution_flag_raw": row.get("sub_flag"),
                "component_exchange_raw": row.get("exchange"),
                "source_api": source_api,
                "known_before_open_verified": False,
                "portfolio_weight_interpretation_allowed": False,
                "source_observation": row.get("_observation"),
            }
        )
    return output


def _prepare(root, release_id, signal_date, execution_date, output):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root, output = Path(root).resolve(), Path(output).resolve()
    if (
        output.exists()
        or output == root
        or root in output.parents
        or output == REPO
        or REPO in output.parents
        or any((parent / ".git").exists() for parent in (output, *output.parents))
    ):
        raise ValueError("Output must be new and outside source/data trees")
    signal_date = date8(signal_date, "signal date")
    execution_date = date8(execution_date, "execution date")
    manifest = manifest_at(root, release_id)
    if manifest.get("retained_observations_included") is not True:
        raise ValueError("Fixed release must include retained observations")
    available = {row["api_name"] for row in manifest["datasets"]}
    queries = []

    def recorded_params(params):
        result = dict(params)
        codes = result.pop("codes", None)
        if codes is not None:
            encoded = json.dumps(codes, separators=(",", ":")).encode()
            result.update(
                codes_count=len(codes), codes_sha256=hashlib.sha256(encoded).hexdigest()
            )
        return result

    def read(api, **params):
        evidence_params = recorded_params(params)
        if api not in available:
            queries.append(
                {
                    "api_name": api,
                    "params": evidence_params,
                    "status": "dataset_unavailable",
                    "rows": 0,
                }
            )
            return []
        table = read_dataset(root, release_id, api, **params)
        if len(table) >= params["limit"]:
            raise ValueError(
                api + " reached explicit query cap; no truncated acceptance"
            )
        metadata = json.loads(table.schema.metadata[b"tushare"])
        if metadata["release_id"] != release_id or metadata["upstream_calls"] != 0:
            raise ValueError("Unexpected fixed-reader provenance")
        queries.append(
            {
                "api_name": api,
                "params": evidence_params,
                "status": "read",
                "rows": len(table),
                "metadata": metadata,
            }
        )
        return table.to_pylist()

    end = (datetime.strptime(signal_date, "%Y%m%d") + timedelta(days=31)).strftime(
        "%Y%m%d"
    )
    calendar = read(
        "trade_cal",
        date_field="cal_date",
        start_date=signal_date,
        end_date=end,
        limit=100,
    )
    next_session(calendar, signal_date, execution_date)
    member_rows = read("ci_index_member", limit=100000)
    members = membership_inputs(member_rows, signal_date)
    member_provenance = fixed_observation_episodes(
        root,
        manifest,
        "ci_index_member",
        member_rows,
        MEMBER_VINTAGE_KEY,
        MEMBER_VINTAGE_KEY,
        (),
    )
    member_vintages = membership_vintages(
        member_rows, member_provenance, signal_date, release_id
    )
    etf_rows = read("etf_basic", limit=10000)
    etf_mapping_rows = [row for row in etf_rows if row.get("index_code")]
    etf_provenance = fixed_observation_episodes(
        root,
        manifest,
        "etf_basic",
        etf_mapping_rows,
        ETF_INDEX_MAPPING_KEY,
        ETF_ENTITY_KEY,
        ETF_INDEX_VALUE_KEY,
    )
    universe, candidates, unsupported = candidate_universe(
        etf_rows,
        read("fund_basic", limit=100000),
        execution_date,
    )
    etf_index_mapping = etf_index_mapping_candidates(
        etf_mapping_rows, etf_provenance, signal_date, release_id
    )
    candidate_codes = sorted(candidates)
    prices, valid_price_codes = etf_price_inputs(
        read(
            "fund_daily",
            date_field="trade_date",
            start_date=execution_date,
            end_date=execution_date,
            codes=candidate_codes,
            limit=20000,
        ),
        read(
            "fund_adj",
            date_field="trade_date",
            start_date=execution_date,
            end_date=execution_date,
            codes=candidate_codes,
            limit=20000,
        ),
        candidates,
        execution_date,
    )
    previous_day = (
        datetime.strptime(signal_date, "%Y%m%d") - timedelta(days=1)
    ).strftime("%Y%m%d")
    holding_search_start = (
        datetime.strptime(signal_date, "%Y%m%d") - timedelta(days=550)
    ).strftime("%Y%m%d")
    holdings, holding_periods = holding_inputs(
        read(
            "fund_portfolio",
            date_field="ann_date",
            start_date=holding_search_start,
            end_date=previous_day,
            codes=candidate_codes,
            limit=500000,
        ),
        candidates,
        signal_date,
    )
    pcf = []
    for api in ("etf_sh_cons", "etf_sz_cons"):
        pcf.extend(
            pcf_inputs(
                read(
                    api,
                    date_field="trade_date",
                    start_date=execution_date,
                    end_date=execution_date,
                    codes=candidate_codes,
                    limit=500000,
                ),
                candidates,
                execution_date,
                api,
            )
        )
    pcf.sort(
        key=lambda row: (row["EtfCode"], row["ComponentCode"] or "", row["source_api"])
    )

    price_codes = {row["EtfCode"] for row in prices}
    pcf_codes = {row["EtfCode"] for row in pcf}
    report = {
        "schema_version": 1,
        "status": "blocked_data",
        "input_status": "pit_and_etf_point_structures_prepared",
        "release_id": release_id,
        "signal_date": signal_date,
        "execution_date": execution_date,
        "holding_announcement_search": {
            "start_date": holding_search_start,
            "end_date": previous_day,
            "earlier_history_absent_verified": False,
        },
        "upstream_calls": 0,
        "credentials_accessed": False,
        "case_state_changed": False,
        "strategy_or_returns_calculated": False,
        "membership": {
            "rows": len(members),
            "candidate_on_signal_rows": sum(
                row["interval_contains_signal_candidate"] for row in members
            ),
            "known_at_rows": 0,
            "forward_vintage_rows": len(member_vintages),
            "forward_usable_on_signal_rows": sum(
                row["forward_usable_for_signal"] for row in member_vintages
            ),
            "pit_ready": False,
        },
        "etf": {
            "observed_codes": len(universe),
            "date_eligible_candidate_codes": len(candidates),
            "execution_price_codes": len(price_codes),
            "valid_price_and_factor_codes": len(valid_price_codes),
            "invalid_price_or_factor_codes": sorted(price_codes - valid_price_codes),
            "missing_execution_price_codes": sorted(candidates - price_codes),
            "unsupported_exchange_codes": sorted(unsupported),
            "latest_pre_signal_disclosure_codes": len(holding_periods),
            "exact_execution_pcf_codes": len(pcf_codes),
            "current_index_mapping_candidates": len(etf_index_mapping),
            "forward_usable_index_mapping_candidates": sum(
                row["forward_usable_for_signal"] for row in etf_index_mapping
            ),
            "historical_universe_verified": False,
            "historical_mapping_verified": False,
            "industry_mapping_verified": False,
            "tradability_verified": False,
            "complete_exposure_verified": False,
        },
        "structures": {
            "industry_members": "prepared_with_null_known_at_semantic_block",
            "industry_member_vintages": (
                "prepared_forward_only_from_current_value_episode"
            ),
            "etf_index_mapping": (
                "prepared_current_observation_forward_only_not_historical"
            ),
            "etf_prices": "prepared_exact_execution_rows_no_fill",
            "etf_holdings": "prepared_latest_strictly_pre_signal_disclosure_partial_only",
            "etf_pcf": "prepared_exact_execution_rows_publication_time_unverified",
        },
        "gaps": GAPS,
        "queries": queries,
        "source_partition_counts": {
            api: sum(row["api_name"] == api for row in manifest["datasets"])
            for api in (
                "ci_index_member",
                "etf_basic",
                "fund_basic",
                "fund_daily",
                "fund_adj",
                "fund_portfolio",
                "etf_sh_cons",
                "etf_sz_cons",
            )
        },
        "partition_count_semantics": "Physical published observations, not unique dates, complete history or PIT proof",
    }

    schemas = {
        "industry_members": pa.schema(
            [
                ("SectorCode", pa.string()),
                ("Symbol", pa.string()),
                ("effective_from", pa.string()),
                ("effective_to", pa.string()),
                ("known_at", pa.string()),
                ("SectorType", pa.string()),
                ("source_symbol", pa.string()),
                ("source_l1_code", pa.string()),
                ("source_observation", pa.string()),
                ("interval_contains_signal_candidate", pa.bool_()),
                ("effective_interval_semantics_verified", pa.bool_()),
                ("known_at_verified", pa.bool_()),
            ]
        ),
        "industry_member_vintages": pa.schema(
            [
                ("SectorCode", pa.string()),
                ("Symbol", pa.string()),
                ("effective_from", pa.string()),
                ("effective_to", pa.string()),
                ("episode_start_observation_at", pa.string()),
                ("observation_local_date", pa.string()),
                ("forward_valid_from", pa.string()),
                ("selected_fixed_observation_at", pa.string()),
                ("selected_observation_local_date", pa.string()),
                ("selected_forward_valid_from", pa.string()),
                ("forward_usable_for_signal", pa.bool_()),
                ("known_at_basis", pa.string()),
                ("source_release_id", pa.string()),
                ("source_object_sha256", pa.string()),
                ("source_observation", pa.string()),
                ("source_observation_sha256", pa.string()),
                ("selected_source_object_sha256", pa.string()),
                ("selected_source_observation", pa.string()),
                ("selected_source_observation_sha256", pa.string()),
                ("episode_continuity_proven", pa.bool_()),
                ("historical_known_at_verified", pa.bool_()),
                ("historical_mapping_verified", pa.bool_()),
            ]
        ),
        "etf_universe": pa.schema(
            [
                ("EtfCode", pa.string()),
                ("source_etf_code", pa.string()),
                ("exchange", pa.string()),
                ("index_code", pa.string()),
                ("index_name", pa.string()),
                ("list_date", pa.string()),
                ("delist_date", pa.string()),
                ("observed_list_status", pa.string()),
                ("date_eligible_candidate", pa.bool_()),
                ("historical_universe_verified", pa.bool_()),
                ("industry_mapping_verified", pa.bool_()),
                ("source_observation", pa.string()),
            ]
        ),
        "etf_index_mapping": pa.schema(
            [
                ("EtfCode", pa.string()),
                ("source_etf_code", pa.string()),
                ("index_code", pa.string()),
                ("index_name", pa.string()),
                ("episode_start_observation_at", pa.string()),
                ("observation_local_date", pa.string()),
                ("forward_valid_from", pa.string()),
                ("selected_fixed_observation_at", pa.string()),
                ("selected_observation_local_date", pa.string()),
                ("selected_forward_valid_from", pa.string()),
                ("forward_usable_for_signal", pa.bool_()),
                ("mapping_basis", pa.string()),
                ("source_release_id", pa.string()),
                ("source_object_sha256", pa.string()),
                ("source_observation", pa.string()),
                ("source_observation_sha256", pa.string()),
                ("selected_source_object_sha256", pa.string()),
                ("selected_source_observation", pa.string()),
                ("selected_source_observation_sha256", pa.string()),
                ("episode_continuity_proven", pa.bool_()),
                ("historical_mapping_verified", pa.bool_()),
            ]
        ),
        "etf_prices": pa.schema(
            [
                ("EtfCode", pa.string()),
                ("time", pa.string()),
                ("open", pa.float64()),
                ("close", pa.float64()),
                ("volume", pa.float64()),
                ("amount", pa.float64()),
                ("adj_factor", pa.float64()),
                ("source_volume_unit", pa.string()),
                ("source_amount_unit", pa.string()),
                ("exact_execution_row", pa.bool_()),
                ("execution_input_valid", pa.bool_()),
                ("open_tradability_verified", pa.bool_()),
                ("source_observation", pa.string()),
                ("factor_observation", pa.string()),
            ]
        ),
        "etf_holdings": pa.schema(
            [
                ("EtfCode", pa.string()),
                ("ComponentCode", pa.string()),
                ("source_component_code", pa.string()),
                ("report_date", pa.string()),
                ("announcement_date", pa.string()),
                ("market_value", pa.float64()),
                ("stock_market_value_ratio", pa.float64()),
                ("known_before_signal_day", pa.bool_()),
                ("complete_exposure_verified", pa.bool_()),
                ("source_observation", pa.string()),
            ]
        ),
        "etf_pcf": pa.schema(
            [
                ("EtfCode", pa.string()),
                ("ComponentCode", pa.string()),
                ("component_name", pa.string()),
                ("tradingDay", pa.string()),
                ("quantity_raw", pa.string()),
                ("cash_substitution_flag_raw", pa.string()),
                ("component_exchange_raw", pa.string()),
                ("source_api", pa.string()),
                ("known_before_open_verified", pa.bool_()),
                ("portfolio_weight_interpretation_allowed", pa.bool_()),
                ("source_observation", pa.string()),
            ]
        ),
    }
    rows = {
        "industry_members": members,
        "industry_member_vintages": member_vintages,
        "etf_universe": universe,
        "etf_index_mapping": etf_index_mapping,
        "etf_prices": prices,
        "etf_holdings": holdings,
        "etf_pcf": pcf,
    }
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.dumps(
        {"release_id": release_id, "status": "blocked_data", "upstream_calls": 0},
        sort_keys=True,
    ).encode()
    for name, relative in OUTPUTS.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(
            rows[name], schema=schemas[name]
        ).replace_schema_metadata({b"rrg_input": metadata})
        pq.write_table(table, path, compression="zstd")
    (output / "input-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    inventory = {}
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        inventory[relative] = {"sha256": sha(path), "bytes": path.stat().st_size}
    (output / "manifest.json").write_text(
        json.dumps(
            {"release_id": release_id, "status": "blocked_data", "files": inventory},
            indent=2,
        )
        + "\n"
    )
    return report


def prepare(*args, **kwargs):
    """Block upstream, secret and source writes while reading one fixed release."""
    with ExitStack() as guards:
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "backend.shared.tushare_pipeline.get_secret",
            "backend.shared.runtime_secrets.get_secret",
        ):
            guards.enter_context(
                patch(target, side_effect=AssertionError("Offline RRG bridge"))
            )
        return _prepare(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--execution-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(
        args.root, args.release_id, args.signal_date, args.execution_date, args.output
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": report["status"],
                "membership": report["membership"],
                "etf": report["etf"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
