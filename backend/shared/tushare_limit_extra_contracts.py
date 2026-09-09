"""Pure daily price-limit pools, limit ladders and concept heat contracts."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "limit_list_ths": "trade_date ts_code name price pct_chg open_num lu_desc limit_type tag status first_lu_time last_lu_time first_ld_time last_ld_time limit_order limit_amount turnover_rate free_float lu_limit_order limit_up_suc_rate turnover rise_rate sum_float market_type".split(),
    "limit_list_d": "trade_date ts_code industry name close pct_chg amount limit_amount float_mv total_mv turnover_ratio fd_amount first_time last_time open_times up_stat limit_times limit".split(),
    "limit_step": "ts_code name trade_date nums".split(),
    "limit_cpt_list": "ts_code name trade_date days up_stat cons_nums up_nums pct_chg rank".split(),
}
INPUT_FIELDS = {
    "limit_list_ths": "trade_date ts_code limit_type market start_date end_date".split(),
    "limit_list_d": "trade_date ts_code limit_type exchange start_date end_date".split(),
    "limit_step": "trade_date ts_code start_date end_date nums".split(),
    "limit_cpt_list": "trade_date ts_code start_date end_date".split(),
}
# Exact published supplier literals, including 连扳池 (not silently corrected).
VARIANTS = {
    "limit_list_ths": [
        {"limit_type": x} for x in ("涨停池", "连扳池", "冲刺涨停", "炸板池", "跌停池")
    ],
    "limit_list_d": [{"limit_type": x} for x in ("U", "D", "Z")],
    "limit_step": [{}],
    "limit_cpt_list": [{}],
}
HIDDEN_THS_FIELDS = (
    "first_lu_time last_lu_time first_ld_time last_ld_time rise_rate sum_float".split()
)
_DOCS = {
    "limit_list_ths": (
        355,
        4000,
        8000,
        "20231101",
        ("trade_date", "ts_code", "limit_type", "market_type"),
    ),
    "limit_list_d": (298, 2500, 5000, "20200101", ("trade_date", "ts_code", "limit")),
    "limit_step": (356, 2000, 8000, None, ("trade_date", "ts_code", "nums")),
    "limit_cpt_list": (357, 2000, 8000, None, ("trade_date", "ts_code")),
}
LIMIT_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start, _keys) in _DOCS.items():
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in ("trade_date", "ts_code")],
        extra=FIELDS[_api],
        start=_start,
        split=True,
        rpm=50,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        # Part of the existing family fingerprint: never reuse a daily cursor
        # against the shorter monthly enumeration after this planner change.
        history_partition="calendar_month_v1",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=HIDDEN_THS_FIELDS.copy() if _api == "limit_list_ths" else [],
        request_identity_fields=["limit_type"]
        if _api in ("limit_list_ths", "limit_list_d")
        else [],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        permission_note="Published points/rate tiers do not verify this account. 50 rpm is an operational ceiling, not measured entitlement.",
        documented_requests_per_minute={"8000_plus_points": 500},
        documented_daily_requests={"8000_plus_points": "unlimited"},
        date_field="trade_date",
        split_axis="trade_date",
        dependencies=[],
        preserve_distinct_rows=True,
        history_bound_verified=False,
        history_precision="day"
        if _api == "limit_list_ths"
        else "year"
        if _api == "limit_list_d"
        else None,
        history_gap="Documented planning floor is not proof of historical completeness or timestamp availability."
        if _start
        else "No earliest date is documented; a sample date must not become a fabricated history start.",
        saturation_fallback="limit_concepts"
        if _api == "limit_cpt_list"
        else "limit_securities",
        saturation_param="ts_code",
        saturation_dependencies=["limit_concepts"]
        if _api == "limit_cpt_list"
        else [
            "stocks",
            "historical_listing_securities",
            "trading_event_securities",
            "limit_securities",
        ],
        discovery_gap="Source discovery is incomplete until audited; a capped day/code partition and unknown code universe remain unresolved. Never infer all-history completion from a sampled or current listing.",
        pagination_gap="No offset/limit inputs are documented. Split only legal date ranges or source ts_code while retaining pool/market/exchange/nums filters; terminal caps remain blocked.",
        field_selection_note="Request every reviewed field explicitly, require the returned columns, allow source nulls, and preserve unknown newly returned columns. fields='' cannot prove hidden columns collected.",
        row_identity_note="Keep distinct source rows and immutable pool request identity, not just stock/date. Repeated identical observations can dedupe, but supplier event multiplicity remains unverified.",
        pit_gap="Daily close pools, rankings and retrospective labels do not establish intraday availability. Time-only columns lack a complete timestamp/timezone contract; do not invent historical knowledge from them.",
        refresh_gap="Seven-calendar-day refresh does not certify older revisions, deletions or historical category membership. Preserve immutable observations and keep earlier corrections unresolved.",
    )
    LIMIT_EXTRA_CONTRACTS[_api] = spec

LIMIT_EXTRA_CONTRACTS["limit_list_ths"].update(
    documented_markets=["HS", "GEM", "STAR"],
    documented_default_pool="涨停池",
    category_note="Explicitly request all five documented limit_type variants. Keep the literal 连扳池 and audit its acceptance/returned category instead of silently substituting 连板池. Market omission has no independently verified coverage guarantee.",
    category_gap="Pool-specific nulls are expected: lu_limit_order has values only for 涨停池/连扳池 per page. Preserve distinct requests even if returned source fields coincide or category labels differ.",
    usage_note="The official page limits use to personal study/research; commercial use requires separate vendor arrangements. Account access remains unprobed.",
    unit_note="price is CNY; sum_float is hundred-million CNY. Several order/float column descriptions say CNY but labels are ambiguous; preserve raw values, do not infer a unified volume measure. No scaling conversion is applied.",
    update_note="Page says about 16:00 daily; publication and correction times still require observation evidence.",
)
LIMIT_EXTRA_CONTRACTS["limit_list_d"].update(
    documented_exchanges=["SH", "SZ", "BJ"],
    documented_requests_per_minute={"5000_points": 200, "8000_plus_points": 500},
    documented_daily_requests={"5000_points": 10000, "8000_plus_points": "unlimited"},
    category_note="Input limit_type U/D/Z corresponds to output limit. Preserve both request provenance and supplier label, and audit consistency rather than substituting one for the other.",
    coverage_exclusions=["ST stocks"],
    category_gap="Official coverage excludes ST stocks. limit_amount is unavailable for limit-up and first_time unavailable for limit-down; these nulls are valid and do not imply the pool absent.",
    unit_note="Source output table does not fully specify amount/market-value scaling. Keep all original values and N/T up_stat strings; do not infer numeric units or convert ratios from examples.",
)
LIMIT_EXTRA_CONTRACTS["limit_step"].update(
    category_note="nums is a source string and optional multi-value filter (e.g. 2,3). Default planner leaves it unfiltered; do not invent a maximum ladder height or coerce supplier strings into counts.",
    coverage_note="The official sample includes ST names. The other limit_list_d API's ST exclusion must not be copied here; cross-source universes are not equivalent.",
)
LIMIT_EXTRA_CONTRACTS["limit_cpt_list"].update(
    namespace_note="ts_code is an opaque supplier concept identifier, e.g. 885728.TI, not a stock. Keep source labels and a dedicated limit_concepts namespace, never use stock master as the concept universe.",
    category_note="rank is documented as string; up_stat is a label such as 9天7板. Do not reinterpret ranking/label fields as stock identifiers, timestamps or independent capital-flow measurements.",
)


def _enabled(config):
    values = config.get("limit_extra_apis", tuple(LIMIT_EXTRA_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(a, str) or a not in LIMIT_EXTRA_CONTRACTS for a in values
    ):
        raise ValueError("limit_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("limit_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("limit_extra_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and setting.keys() - LIMIT_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in limit_extra_history_start")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        configured = _parse(value) if value is not None else None
        floor = LIMIT_EXTRA_CONTRACTS[api]["history_start"]
        floor = _parse(floor) if floor else None
        result[api] = max(configured or floor, floor) if floor else configured
    return result


def limit_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["limit_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = LIMIT_EXTRA_CONTRACTS[api]
        for kind in (
            "history_gap",
            "discovery_gap",
            "pagination_gap",
            "category_gap",
            "pit_gap",
            "refresh_gap",
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
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "unknown_history_start_requires_scope_or_discovery"
                if starts[api] is None
                else "planned_scope_not_verified_complete",
                "planned_start": starts[api].strftime("%Y%m%d")
                if starts[api]
                else None,
            }
        )
        if spec["hidden_fields"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "hidden_fields_require_explicit_request_and_response_audit",
                    "fields": spec["hidden_fields"],
                }
            )
    return gaps


def _days(api, begin, end):
    day = begin
    while day <= end:
        for variant in VARIANTS[api]:
            yield {"trade_date": day.strftime("%Y%m%d"), **variant}
        day += timedelta(days=1)


def _months(api, begin, end):
    day = begin
    while day <= end:
        last = min(end, date(day.year, day.month, monthrange(day.year, day.month)[1]))
        for variant in VARIANTS[api]:
            yield {
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
                **variant,
            }
        if last == end:
            return
        day = last + timedelta(days=1)


def iter_limit_extra_jobs(config, today, identifiers=None):
    """Explicit all-pool recent requests, then lazy fair historical partitions."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api in enabled:
        start = starts[api]
        for params in _days(api, max(start or recent, recent), today):
            yield {
                "api_name": api,
                "params": params,
                "fields": ",".join(FIELDS[api]),
                "priority": 20,
                "epoch": epoch,
            }
        if start and start < recent:
            histories[api] = iter(_months(api, start, recent - timedelta(days=1)))
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
