"""Pure reviewed calendar/announcement or factor-library acquisition contracts."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_technical_extra_contracts import _days

SOURCE_HTML_SHA256 = {
    "factor_list": "799b1716dd674500e499bee73be4015307df014c16064219e751bbbfb45650f2",
    "factor_value": "3328603c3cc38b1d305a1b45d2e8adefda75fe0bd37b2baea300e21b95fd0962",
}

INPUT_METADATA = {
    "factor_list": {
        "factor_name": {"type": "str", "required": "N", "description": "因子名称"},
        "asset_type": {
            "type": "str",
            "required": "N",
            "description": "资产类别：STK股票，IDX指数，ETF，CB可转债 【当前只提供STK股票】",
        },
        "factor_type": {
            "type": "str",
            "required": "N",
            "description": "因子类别，详见下方明细",
        },
    },
    "factor_value": {
        "ts_code": {"type": "str", "required": "N", "description": "股票代码"},
        "factor_name": {
            "type": "str",
            "required": "N",
            "description": "因子名称（基于因子列表的名称）",
        },
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期：YYYYMMDD格式",
        },
        "start_date": {
            "type": "str",
            "required": "N",
            "description": "开始日期：YYYYMMDD格式",
        },
        "end_date": {
            "type": "str",
            "required": "N",
            "description": "结束日期：YYYYMMDD格式",
        },
    },
}

FIELD_METADATA = {
    "factor_list": {
        "factor_name": {"type": "str", "default": "Y", "description": "因子名称"},
        "asset_type": {
            "type": "str",
            "default": "Y",
            "description": "证券类型：STK股票，IDX指数，ETF，CB可转债 【当前只提供STK股票】",
        },
        "factor_type": {"type": "str", "default": "Y", "description": "因子分类"},
        "factor_desc": {
            "type": "str",
            "default": "Y",
            "description": "因子描述及算法逻辑",
        },
    },
    "factor_value": {
        "factor_name": {"type": "str", "default": "Y", "description": "因子名称"},
        "ts_code": {"type": "str", "default": "Y", "description": "证券代码"},
        "trade_date": {
            "type": "str",
            "default": "Y",
            "description": "交易日期，格式YYYYMMDD",
        },
        "factor_value": {"type": "float", "default": "Y", "description": "因子值"},
    },
}

INPUT_FIELDS = {api: list(metadata) for api, metadata in INPUT_METADATA.items()}

FIELDS = {api: list(metadata) for api, metadata in FIELD_METADATA.items()}

FACTOR_LIBRARY_CONTRACTS = {}
for _api, _doc, _cap, _axis, _keys in (
    ("factor_list", 486, 10000, None, ("factor_name", "asset_type", "factor_type")),
    ("factor_value", 490, 6000, "trade_date", ("factor_name", "ts_code", "trade_date")),
):
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[
            f
            for f in FIELDS[_api]
            if f
            not in (("factor_name", "asset_type") if _api == "factor_list" else _keys)
        ],
        extra=FIELDS[_api],
        split=_api == "factor_value",
        rpm=30,
        cap_verified=_api == "factor_value",
    )
    spec.update(
        doc_id=_doc,
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        fields=list(FIELDS[_api]),
        requested_fields=list(FIELDS[_api]),
        hidden_fields=[],
        input_metadata=INPUT_METADATA[_api],
        field_metadata=FIELD_METADATA[_api],
        allowed_params=list(INPUT_METADATA[_api]),
        required_params=[],
        request_identity_fields=[],
        preserve_distinct_rows=True,
        date_field=_axis,
        split_axis=_axis,
        dependencies=[] if _api == "factor_list" else ["factor_library_factors"],
        permission_status="unprobed",
        minimum_points=None,
        independent_permission="Factor-library subscription: individual2000yuan/year; institution20000yuan/year. Not implied by other purchased entitlements.",
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        documented_row_cap=None if _api == "factor_list" else 6000,
        history_bound_verified=False,
        permission_gap="Independent permission remains unprobed. factor_value mentions5000-point trial with permission-center details; points alone do not establish full scope/quota. Local30rpm is only an operational ceiling.",
        history_gap="No verified earliest date or retired-factor archive is documented. Configured history_start is requested scope; examples and the advertised current factor count are not completeness evidence.",
        pagination_gap="No offset/limit/page input is documented. Keep cap results unresolved until a legal smaller partition is independently verified.",
        identity_gap="No immutable row/revision ID; retain distinct full rows and raw source values. Equal-valued multiplicity, deletions and historical definition changes remain unknown.",
        pit_gap="Factor descriptions are source data, not executable or verified formulas. Adjustment basis, financial restatements, announcement availability, warmup, constituent universe and formula versions remain unverified.",
        field_selection_note="Explicitly request all4 known columns and retain new returned columns/nulls. All documented fields defaultY.",
        field_gaps={
            f: ["actual_presence_unprobed", "historical_availability_unverified"]
            for f in FIELDS[_api]
        },
    )
    FACTOR_LIBRARY_CONTRACTS[_api] = spec
FACTOR_LIBRARY_CONTRACTS["factor_list"].update(
    catalog_note="Historical486 catalog mixed9 explanatory categories with4 real output fields. Parser/catalog correction f024021 is documented in docs/tushare-factor-catalog-schema.evidence.json with original HTML SHA and exact differences. Only the 名称/类型/默认显示/描述 schema table supplies fields; category/formula prose is not schema.",
    discovery_gap="factor_name is the actual lookup identifier; no factor_id exists. Snapshot all assets without filters, retain names/case/asset_type/factor_type/factor_desc, and discover values from actual STK rows. Current202-factor/9-category prose is neither a seed list nor a frozen universe.",
    history_scope_gap="List has no date/history filter or valid-from metadata. A snapshot cannot reconstruct old/removed definitions, and history_start must not be sent to this API.",
    saturation_gap="Page says one request returns the entire list but gives no numeric cap.10000 is a local guard, not a provider cap. Optional name/asset/type filters cannot certify the complete universe without separate evidence.",
)
FACTOR_LIBRARY_CONTRACTS["factor_value"].update(
    code_only_discovery_gap="A legal ts_code-only probe can succeed while factor_list is empty or denied. Such value rows lack asset_type and do not seed automatic names. Until actual permissions and an audited code-only partition plan are available, no factor_value auto-jobs are produced without list discovery; sample availability is not automatic readiness.",
    input_constraint="At least one of ts_code or factor_name is required. Automatic planning uses actual discovered factor_name; code-only queries are legally documented but not this candidate auto-plan.",
    exact_date_param="trade_date",
    source_namespace="mainland_equity_only_preserve_source_ts_code",
    saturation_fallback="stocks",
    saturation_param="ts_code",
    saturation_dependencies=["stocks"],
    discovery_gap="Requires actual factor_list records with factor_name and asset_type. Current source supports STK only; other assets and name collisions stay explicit gaps because factor_value has no asset_type filter. Stock fallback must include historical/delisted/T and source-observed stocks, never current listings alone.",
    date_note="trade_date is the factor observation date, not first-public availability. Source update18:30–19:30 timezone unspecified. Calendar-day planning includes holidays; empty results do not establish factor coverage.",
    documentation_gap="Page request example names MACD and20260812 but displayed rows have other names and20100104. Validate actual name/date filters; these sample values are neither seed identifiers nor historical lower bounds.",
    unit_note="factor_value is a floating source scalar whose scale/unit/adjustment depends on factor_desc and may be unspecified. Do not rescale percentages, rank values or assume equivalence to local factor implementations.",
    saturation_gap="6000-row factor/date cross-section may need legal ts_code fanout from the complete historical equity universe. Single-factor/code/day cap has no further legal cursor; keep it blocked. Do not split by undocumented asset_type or factor_type.",
    refresh_gap="Recent7 overlap does not cover all older corrections; newly discovered and removed factors need historical reconciliation, not a claim that current names represent every historical factor.",
)


def _enabled(config):
    selected = config.get("factor_library_apis", tuple(FACTOR_LIBRARY_CONTRACTS))
    if not isinstance(selected, (tuple, list)) or any(
        not isinstance(a, str) or a not in FACTOR_LIBRARY_CONTRACTS for a in selected
    ):
        raise ValueError("factor_library_apis must list known APIs")
    return tuple(dict.fromkeys(selected))


def _starts(config, enabled):
    setting = config.get("factor_library_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("factor_library_history_start must be YYYYMMDD or API mapping")
    if isinstance(setting, dict) and setting.keys() - FACTOR_LIBRARY_CONTRACTS.keys():
        raise ValueError("Unknown factor-library history API")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        result[api] = _parse(value) if value is not None else None
    return result


def _factor_names(identifiers):
    """Only caller-supplied actual factor_list records; never seed example names."""
    records = (identifiers or {}).get("factor_library_factors", ())
    if not isinstance(records, (list, tuple)):
        raise ValueError(
            "factor_library_factors must contain actual factor_list records"
        )
    assets = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Factor discovery requires source records with asset_type")
        name, asset = row.get("factor_name"), row.get("asset_type")
        if any(
            not isinstance(v, str) or not v.strip() or any(ord(c) < 32 for c in v)
            for v in (name, asset)
        ):
            raise ValueError(
                "Factor name and asset_type must be nonempty source strings without control characters"
            )
        assets.setdefault(name, set()).add(asset)
    return sorted(name for name, kinds in assets.items() if kinds == {"STK"}), assets


def factor_library_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["factor_library_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    names, assets = (
        _factor_names(identifiers) if "factor_value" in enabled else ([], {})
    )
    gaps = []
    for api in enabled:
        gaps.extend(
            {"api_name": api, "dependencies": [], "reason": k, "detail": v}
            for k, v in FACTOR_LIBRARY_CONTRACTS[api].items()
            if k.endswith("_gap")
        )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "configured_scope_not_verified_complete"
                if starts[api]
                else "unknown_history_start_requires_scope",
            }
        )
        if api == "factor_value":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["factor_library_factors"],
                    "reason": "factor_discovery_unverified"
                    if names
                    else "missing_factor_list_discovery",
                    "observed_names": len(names),
                    "universe_complete": False,
                }
            )
            for name, kinds in assets.items():
                if kinds != {"STK"}:
                    gaps.append(
                        {
                            "api_name": api,
                            "dependencies": ["factor_library_factors"],
                            "reason": "unsupported_or_ambiguous_factor_asset",
                            "factor_name": name,
                            "asset_types": sorted(kinds),
                            "universe_complete": False,
                        }
                    )
    return gaps


def iter_factor_library_jobs(config, today, identifiers=None):
    """Full list snapshot plus recent7/history daily cross-sections per observed STK name."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(v and v > today for v in starts.values()):
        raise ValueError("History start cannot be after today")
    names, _ = _factor_names(identifiers) if "factor_value" in enabled else ([], {})
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    if "factor_list" in enabled:
        yield {
            "api_name": "factor_list",
            "params": {},
            "fields": ",".join(FIELDS["factor_list"]),
            "epoch": epoch,
            "priority": 20,
        }
    if "factor_value" not in enabled or not names:
        return
    start = starts["factor_value"]
    for history in (False, True):
        if history:
            if not start or start >= recent:
                continue
            begin, end = start, recent - timedelta(days=1)
        else:
            begin, end = max(start or recent, recent), today
        for params in _days(begin, end):
            for name in names:
                yield {
                    "api_name": "factor_value",
                    "params": {**params, "factor_name": name},
                    "fields": ",".join(FIELDS["factor_value"]),
                    "epoch": "history" if history else epoch,
                    "priority": 55 if history else 20,
                }
