"""Pure THS reference/price/member and DC daily category acquisition contracts."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "ths_index": "ts_code name count exchange list_date type".split(),
    "ths_daily": "ts_code trade_date close open high low pre_close avg_price change pct_change vol turnover_rate total_mv float_mv".split(),
    "ths_member": "ts_code con_code con_name weight in_date out_date is_new".split(),
    "dc_index": "ts_code trade_date name leading leading_code pct_change leading_pct total_mv turnover_rate up_num down_num idx_type level".split(),
}
INPUT_FIELDS = {
    "ths_index": "ts_code exchange type".split(),
    "ths_daily": "ts_code trade_date start_date end_date".split(),
    "ths_member": "ts_code con_code".split(),
    "dc_index": "ts_code name trade_date start_date end_date idx_type".split(),
}
DC_VARIANTS = [{"idx_type": value} for value in ("行业板块", "概念板块", "地域板块")]
_DOCS = {
    "ths_index": (259, 5000, ("ts_code", "exchange", "type")),
    "ths_daily": (260, 3000, ("ts_code", "trade_date")),
    # Operational guard only; the official member page does not state a row cap.
    "ths_member": (261, 5000, ("ts_code", "con_code")),
    "dc_index": (362, 5000, ("ts_code", "trade_date", "idx_type")),
}
CONCEPT_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _keys) in _DOCS.items():
    required = (
        ("ts_code", "con_code")
        if _api == "ths_member"
        else ("ts_code",)
        if _api == "ths_index"
        else ("ts_code", "trade_date")
    )
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in required],
        extra=FIELDS[_api],
        split=_api in ("ths_daily", "dc_index"),
        rpm=50,
        cap_verified=_api != "ths_member",
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=["total_mv", "float_mv"]
        if _api == "ths_daily"
        else ["weight", "in_date", "out_date", "is_new"]
        if _api == "ths_member"
        else [],
        permission_status="unprobed",
        minimum_points=6000,
        independent_permission=None,
        permission_note="Published 6000-point requirement is not verified account access; 50 rpm is an operational ceiling, not a measured account quota.",
        dependencies=["ths_indices"] if _api == "ths_member" else [],
        preserve_distinct_rows=True,
        date_field="trade_date" if _api in ("ths_daily", "dc_index") else None,
        snapshot_only=_api in ("ths_index", "ths_member"),
        history_bound_verified=False,
        history_gap="No earliest historical date is documented. Configured scope and sample dates do not prove earlier observations absent.",
        pagination_gap="No offset/limit inputs are documented. Legal date/code partitions still need complete discovery; terminal saturation remains a gap.",
        field_selection_note="Request all reviewed fields explicitly, require returned columns with legitimate nulls allowed, preserve unknown newly returned columns. Hidden/unavailable columns need actual response evidence, not fields='' or silent omission.",
        namespace_note="THS and DC reference codes are opaque provider identifiers, not stock/index aliases inferred from prefixes. Preserve source values and provider-specific discovery namespaces.",
        refresh_gap="Recent overlap does not certify older revisions, deletions or backdated membership changes. Immutable observations are not proof of historical knowledge timestamps.",
    )
    CONCEPT_EXTRA_CONTRACTS[_api] = spec

CONCEPT_EXTRA_CONTRACTS["ths_index"].update(
    documented_exchanges=["A", "HK", "US"],
    documented_types=["N", "I", "R", "S", "ST", "TH", "BB"],
    discovery_gap="Official instructions say one unfiltered call retrieves all and not to loop. Plan one snapshot per refresh epoch, no market/type grid or pagination. At 5000 rows keep a cap/completeness gap rather than guessing enumerated partitions prove complete.",
    history_gap="No history date input or removed-index inventory is supplied. list_date is listing date, not a quote-coverage start or historical availability certificate. Output type description lists fewer categories than the input table; retain actual values.",
)
CONCEPT_EXTRA_CONTRACTS["ths_daily"].update(
    saturation_fallback="ths_indices",
    saturation_param="ts_code",
    saturation_dependencies=["ths_indices"],
    discovery_gap="Exact trade_date requests discover all supplier-returned indices without current-market filtering. A capped day needs historical/retired THS indices and observed codes; a current ths_index snapshot cannot certify that universe complete.",
    unit_note="Prices are index points, vol is lots, hidden total_mv/float_mv are CNY. Preserve source scales, including signed change; do not treat THS volume as equity shares or DC market-cap units.",
)
CONCEPT_EXTRA_CONTRACTS["ths_member"].update(
    documented_requests_per_minute=200,
    cap_note="Single-call row limit is unpublished. 5000 is a conservative local guard only; even smaller responses do not establish completeness.",
    unavailable_fields=["weight", "in_date", "out_date"],
    history_gap="Official interface supplies latest members only; weight/in_date/out_date are documented unavailable. is_new is output-only. Do not fabricate membership periods or request historical/is_new parameters.",
    discovery_gap="Enumerate snapshots only for stored/discovered ths_indices, including removed/foreign identities when observed. Missing master, excluded historical indices and unavailable entry/exit history remain explicit gaps.",
    namespace_note="ts_code is a THS index. con_code is a source member code; THS reference markets include A/HK/US, so exchange/suffix semantics for foreign members require evidence. Never force all con_code values into A-share stock normalization.",
    saturation_gap="At a capped per-index snapshot no date split exists. con_code filtering is legal but requires independently complete cross-market member discovery; current A-share stocks or only returned members cannot prove a full fanout.",
)
CONCEPT_EXTRA_CONTRACTS["dc_index"].update(
    required_params=["idx_type"],
    request_identity_fields=["idx_type"],
    saturation_fallback="dc_indices",
    saturation_param="ts_code",
    saturation_dependencies=["dc_indices"],
    category_gap="Input table marks idx_type required while sample omits it; always request all three explicit category literals and preserve request identity. Matching output category and request acceptance remain unverified.",
    discovery_gap="Each date/category is source-specific; include previously observed removed DC labels, not a current THS index set. A capped partition never establishes the complete DC universe.",
    namespace_note="ts_code such as BK1186.DC is a DC board. Keep leading_code separate: its exchange/code format is not demonstrated in the page's sample, so it cannot populate stocks via guessed prefix conversion.",
    unit_note="total_mv is ten-thousand CNY, unlike THS daily market values in CNY; keep source units and leading/per-board percentages without guessing conversions.",
)


def _enabled(config):
    values = config.get("concept_extra_apis", tuple(CONCEPT_EXTRA_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(a, str) or a not in CONCEPT_EXTRA_CONTRACTS for a in values
    ):
        raise ValueError("concept_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _indices(identifiers):
    ids = {} if identifiers is None else identifiers
    if not isinstance(ids, dict):
        raise ValueError("identifiers must map discovery families")
    values = ids.get("ths_indices", ())
    if not isinstance(values, (tuple, list)):
        raise ValueError("ths_indices must be a sequence")
    codes = set()
    for value in values:
        code = value.get("ts_code") if isinstance(value, dict) else value
        if (
            not isinstance(code, str)
            or not code
            or any(
                c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "," for c in code
            )
        ):
            raise ValueError("Invalid source THS index identifier")
        codes.add(code)
    return sorted(codes)


def _starts(config, enabled):
    setting = config.get("concept_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "concept_extra_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - CONCEPT_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in concept_extra_history_start")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        configured = _parse(value) if value is not None else None
        result[api] = (
            None if CONCEPT_EXTRA_CONTRACTS[api]["snapshot_only"] else configured
        )
    return result


def concept_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["concept_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    codes = _indices(identifiers) if "ths_member" in enabled else []
    gaps = []
    for api in enabled:
        spec = CONCEPT_EXTRA_CONTRACTS[api]
        for kind in (
            "history_gap",
            "pagination_gap",
            "discovery_gap",
            "refresh_gap",
            "saturation_gap",
            "category_gap",
            "cap_note",
        ):
            if spec.get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": spec[kind],
                    }
                )
        if not spec["snapshot_only"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope_or_discovery"
                    if starts[api] is None
                    else "configured_scope_not_verified_complete",
                }
            )
        if spec["hidden_fields"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "hidden_fields_require_response_evidence",
                    "fields": spec["hidden_fields"],
                    "documented_unavailable": spec.get("unavailable_fields", []),
                }
            )
        if api == "ths_member":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["ths_indices"],
                    "reason": "stored_discovery_completeness_unverified"
                    if codes
                    else "awaiting_stored_ths_indices",
                    "observed_codes": len(codes),
                    "universe_complete": False,
                }
            )
    return gaps


def _days(api, begin, end):
    day = begin
    while day <= end:
        for variant in DC_VARIANTS if api == "dc_index" else [{}]:
            yield {"trade_date": day.strftime("%Y%m%d"), **variant}
        day += timedelta(days=1)


def iter_concept_extra_jobs(config, today, identifiers=None):
    """Single master snapshot, member snapshots, recent days and lazy history."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    codes = _indices(identifiers) if "ths_member" in enabled else []
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api in enabled:
        if api == "ths_index":
            params_stream = [{}]
        elif api == "ths_member":
            params_stream = ({"ts_code": code} for code in codes)
        else:
            start = starts[api]
            params_stream = _days(api, max(start or recent, recent), today)
            if start and start < recent:
                histories[api] = iter(_days(api, start, recent - timedelta(days=1)))
        for params in params_stream:
            yield {
                "api_name": api,
                "params": params,
                "fields": ",".join(FIELDS[api]),
                "priority": 20,
                "epoch": epoch,
            }
    while histories:
        for api in tuple(histories):
            params = next(histories[api], None)
            if params is None:
                del histories[api]
            else:
                yield {
                    "api_name": api,
                    "params": params,
                    "fields": ",".join(FIELDS[api]),
                    "priority": 55,
                    "epoch": "history",
                }
