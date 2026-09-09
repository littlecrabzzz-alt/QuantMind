"""Pure historical ST state, ST changes and exchange-warning contracts."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "stock_st": "ts_code name trade_date type type_name".split(),
    "st": "ts_code name pub_date imp_date st_type st_reason st_explain".split(),
    "stk_shock": "ts_code trade_date name trade_market reason period".split(),
    "stk_high_shock": "ts_code trade_date name trade_market reason period".split(),
    "stk_alert": "ts_code name start_date end_date type".split(),
}
INPUT_FIELDS = {
    api: "ts_code pub_date imp_date".split()
    if api == "st"
    else "ts_code trade_date start_date end_date".split()
    for api in FIELDS
}
_DOCS = {
    "stock_st": (397, 3000, "20000101", ("ts_code", "trade_date", "type")),
    "st": (423, 6000, None, ("ts_code", "pub_date", "imp_date", "st_type")),
    "stk_shock": (451, 6000, None, ("ts_code", "trade_date", "reason", "period")),
    "stk_high_shock": (452, 6000, None, ("ts_code", "trade_date", "reason", "period")),
    "stk_alert": (453, 6000, None, ("ts_code", "start_date", "end_date", "type")),
}
RISK_EVENT_CONTRACTS = {}
for _api, (_doc, _points, _start, _keys) in _DOCS.items():
    axis = (
        "pub_date"
        if _api == "st"
        else "start_date"
        if _api == "stk_alert"
        else "trade_date"
    )
    spec = _contract(
        1000,
        _keys,
        required=FIELDS[_api],
        nullable=[field for field in FIELDS[_api] if field not in ("ts_code", axis)],
        extra=FIELDS[_api],
        start=_start,
        split=_api != "st",
        rpm=50,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        permission_note="Published points are not tested account rights; no independent entitlement or endpoint frequency/daily quota is stated. 50 rpm is a local operating ceiling.",
        dependencies=["stocks"] if _api == "st" else [],
        saturation_fallback="risk_securities",
        saturation_param="ts_code",
        saturation_dependencies=["stocks", "funds", "etfs", "risk_securities"]
        if _api == "stk_alert"
        else ["stocks", "risk_securities"],
        preserve_distinct_rows=True,
        date_field=axis,
        split_axis=axis,
        history_bound_verified=False,
        history_gap="Only stock_st has a documented lower bound. Unknown-history sample dates are not history starts; configured scopes and stock-only discovery do not certify a complete earlier archive.",
        pagination_gap="All five pages cap requests at 1000 rows without offset/limit inputs. Retain filters in legal date/code partitions; terminal saturation remains blocked. Loop retrieval is not permission to invent pagination.",
        discovery_gap="Future risk_securities must include historical/delisted/T stock identities and source-observed risk codes. Current listings and saturated returned codes alone never certify an exhaustive historical universe.",
        pit_gap="Source date labels do not establish intraday publication timestamps or immutable historical knowledge. Do not backdate an observed event or infer past trade eligibility from a later downloaded state.",
        refresh_gap="Seven-day overlap and one stock-history sweep cannot certify older revisions/deletions. Distinct row retention does not establish multiplicity of identical supplier events.",
        field_selection_note="All reviewed output columns are default Y. Explicitly request and check all columns, retain allowed nulls and newly returned columns; preserve source explanatory strings rather than parsing them into invented dates or rules.",
        namespace_note="Preserve source_ts_code; historical T identities must not merge with reused ordinary codes. Exchange suffix and trade_market labels are source evidence, not a license to correct apparently inconsistent historical codes.",
    )
    RISK_EVENT_CONTRACTS[_api] = spec

RISK_EVENT_CONTRACTS["stock_st"].update(
    history_note="Daily ST inventory is documented from 20000101; the page explicitly says too-early history cannot be completed. Do not replace missing days with today's ST list.",
    documented_update_time="09:20",
    update_timezone_verified=False,
    date_axis_note="trade_date is the daily ST status date; the quoted morning update schedule does not prove every historical revision was known at 09:20.",
)
RISK_EVENT_CONTRACTS["st"].update(
    date_axis_note="pub_date is publication date and imp_date is implementation date. Preserve both independently; removal, overlay and partial-revocation explanations are not a simple ST boolean.",
    historical_request_axes=["ts_code"],
    recent_request_axes=["pub_date", "imp_date"],
    parameter_note="Only ts_code/pub_date/imp_date are legal filters. Recent dates query each axis separately. Stock-only history has no date bounds, deliberately preserving known future implementations and events outside configured refresh scope.",
    history_gap="No earliest date is documented. Stock-only history is unbounded by local start settings because no date-range inputs exist; missing historical/delisted stock discovery and older corrections remain gaps.",
    saturation_gap="A capped stock-only request has no legal start/end range. Exact pub_date/imp_date are possible filters but do not prove an exhaustive partition without a complete date inventory; keep blocked.",
)
for _api in ("stk_shock", "stk_high_shock"):
    RISK_EVENT_CONTRACTS[_api].update(
        date_axis_note="Input trade_date is labelled trading date, but output trade_date is explicitly announcement date. period is an abnormality interval string, not the request date axis or a machine-verified validity window.",
        documented_output_date_formats=["YYYYMMDD", "YYYY-MM-DD"],
        source_consistency_gap="Official samples contain code/exchange-label inconsistencies and examples whose requested day differs from returned rows. Preserve raw codes, market, dates and periods; real exact/range filtering must be validated before coverage is claimed.",
    )
RISK_EVENT_CONTRACTS["stk_alert"].update(
    date_axis_note="Input trade_date denotes the warning START date. Output start_date is that start, and end_date is a reference expiry, potentially after today. Never treat input end_date as an output-expiry cutoff or manufacture output trade_date.",
    documented_output_date_formats=["YYYY-MM-DD"],
    security_scope="stocks_and_etfs_at_least",
    discovery_gap="Official examples include ETF 513310.SH as well as stocks. Future risk_securities fanout must union historical stocks, ETF/fund discovery and observed risk securities; do not filter to current A-share stock_basic only. Other security types and historical completeness remain unknown.",
    future_gap="A request for a known start can return a reference end after today; keep it. Start-date observations do not prove when the notice was published or every active warning on a later day.",
    source_consistency_gap="The official exact-day sample shows several output start dates. Do not assume exact/range filter equality from documentation alone; validate real response dates before claiming coverage.",
)


def _enabled(config):
    values = config.get("risk_event_apis", tuple(RISK_EVENT_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(api, str) or api not in RISK_EVENT_CONTRACTS for api in values
    ):
        raise ValueError("risk_event_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("risk_event_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("risk_event_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and setting.keys() - RISK_EVENT_CONTRACTS.keys():
        raise ValueError("Unknown API in risk_event_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        floor = RISK_EVENT_CONTRACTS[api]["history_start"]
        candidates = [_parse(v) for v in (value, floor) if v is not None]
        starts[api] = max(candidates) if candidates else None
    return starts


def risk_event_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["risk_event_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks = (
        _stocks(identifiers if identifiers is not None else {})
        if "st" in enabled
        else []
    )
    gaps = []
    for api in enabled:
        spec = RISK_EVENT_CONTRACTS[api]
        for kind in (
            "history_gap",
            "pagination_gap",
            "discovery_gap",
            "pit_gap",
            "refresh_gap",
            "saturation_gap",
            "source_consistency_gap",
            "future_gap",
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
                else "configured_scope_not_verified_complete",
            }
        )
        if api == "st":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["stocks"],
                    "reason": "stored_discovery_completeness_unverified"
                    if stocks
                    else "awaiting_stored_stocks",
                    "observed_codes": len(stocks),
                    "universe_complete": False,
                }
            )
    return gaps


def _days(api, begin, end):
    day = begin
    while day <= end:
        for axis in ("pub_date", "imp_date") if api == "st" else ("trade_date",):
            yield {axis: day.strftime("%Y%m%d")}
        day += timedelta(days=1)


def iter_risk_event_jobs(config, today, identifiers=None):
    """Exact recent date axes, lazy historical days and unbounded stock ST events."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks = (
        _stocks(identifiers if identifiers is not None else {})
        if "st" in enabled
        else []
    )
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
        if api == "st":
            histories[api] = ({"ts_code": code} for code in stocks)
        elif start and start < recent:
            histories[api] = iter(_days(api, start, recent - timedelta(days=1)))
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
