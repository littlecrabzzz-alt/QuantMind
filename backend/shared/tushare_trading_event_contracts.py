"""Pure daily leaderboard/hot-money contracts; no account or runtime side effects."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "top_list": "trade_date ts_code name close pct_change turnover_rate amount l_sell l_buy l_amount net_amount net_rate amount_rate float_values reason".split(),
    "top_inst": "trade_date ts_code exalter side buy buy_rate sell sell_rate net_buy reason".split(),
    "hm_list": "name desc orgs".split(),
    "hm_detail": "trade_date ts_code ts_name buy_amount sell_amount net_amount hm_name hm_orgs tag".split(),
}
INPUT_FIELDS = {
    "top_list": ["trade_date", "ts_code"],
    "top_inst": ["trade_date", "ts_code"],
    "hm_list": ["name"],
    "hm_detail": ["trade_date", "ts_code", "hm_name", "start_date", "end_date"],
}
_DOCS = {
    "top_list": (106, 10000, 2000, "20050101", ("trade_date", "ts_code", "reason")),
    "top_inst": (
        107,
        10000,
        5000,
        None,
        ("trade_date", "ts_code", "exalter", "side", "reason"),
    ),
    "hm_list": (311, 1000, 5000, None, ("name",)),
    "hm_detail": (
        312,
        2000,
        10000,
        "20220801",
        ("trade_date", "ts_code", "hm_name", "hm_orgs", "tag"),
    ),
}
TRADING_EVENT_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start, _keys) in _DOCS.items():
    _nonnull = ("name",) if _api == "hm_list" else ("trade_date", "ts_code")
    # Require column presence for the complete reviewed schema; nullable source
    # values remain valid. In particular an omitted hidden tag is not a null tag.
    _spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[field for field in FIELDS[_api] if field not in _nonnull],
        extra=FIELDS[_api],
        start=_start,
        split=_api == "hm_detail",
        rpm=50,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        permission_note="Published points threshold is not verified account entitlement. Operational 50 rpm is not a documented account rate.",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=["tag"] if _api == "hm_detail" else [],
        dependencies=[],
        preserve_distinct_rows=True,
        date_field=None if _api == "hm_list" else "trade_date",
        snapshot_only=_api == "hm_list",
        history_bound_verified=False,
        history_precision="year"
        if _api == "top_list"
        else "month"
        if _api == "hm_detail"
        else None,
        history_gap="Documented year/month floor is a planning boundary, not a verified earliest observation. Earlier coverage and supplier omissions remain unverified."
        if _start
        else "No earliest date or historical lower bound is documented.",
        pagination_gap="No offset/limit input is documented. A response at the cap is unresolved until legal partitions and their discovery coverage are audited.",
        row_identity_note="Natural keys are candidates, not supplier event IDs. Preserve different source rows with derived _row_identity; never request that derived field upstream.",
        multiplicity_gap="Content-hash deduplication cannot certify separate identical-valued event multiplicity. Preserve raw response ordering/counts and do not infer event counts from deduplicated views.",
        refresh_gap="Seven-day overlap does not certify older revisions, deletions or point-in-time availability; preserve source observations and audit older windows separately.",
        field_selection_note="Use the complete requested_fields string explicitly. fields='' asks for defaults and is insufficient for hidden columns. Audit returned fields and preserve newly observed unknown columns; a reviewed schema is not a closed supplier schema.",
    )
    if _api != "hm_list":
        _spec.update(
            saturation_fallback="stocks",
            saturation_param="ts_code",
            saturation_dependencies=["stocks", "trading_event_securities"],
            discovery_gap="Exact-date all-market discovery does not require a current stock universe. A capped date needs source-code partitions from historical/retired/T stock master plus observed event securities; completeness of that union is unverified. Never discard a source code solely because it is no longer listed.",
        )
    TRADING_EVENT_CONTRACTS[_api] = _spec

TRADING_EVENT_CONTRACTS["top_list"].update(
    required_params=["trade_date"],
    field_note="Multiple reasons per stock/date are valid (official sample 002219.SZ, 20180928). Preserve reason and signed net/rate fields; the output table does not establish amount units.",
)
TRADING_EVENT_CONTRACTS["top_inst"].update(
    required_params=["trade_date"],
    field_note="side is source string 0 (buy top five) or 1 (sell top five); the same institution can occur on both sides and for multiple reasons. buy/sell/net_buy are CNY; preserve source rate scaling.",
)
TRADING_EVENT_CONTRACTS["hm_list"].update(
    required_params=[],
    field_note="Official schema is name/desc/orgs only. orgs has unspecified type (None); preserve its opaque source value. zhouyu1933, bike770 and Asking are example names, not columns.",
    discovery_gap="Unfiltered snapshot limit is 1000. The page's current count below 500 is not a permanent completeness guarantee. Queries for already observed names cannot prove omitted names absent; name changes/aliases and historical memberships have no documented coverage contract.",
    history_gap="No date/valid_from/known_at or stable ID is exposed: current name/organization descriptions cannot be backdated or treated as verified account ownership.",
)
TRADING_EVENT_CONTRACTS["hm_detail"].update(
    required_params=[],
    field_note="tag is default N and must be explicitly requested, present as a column, and allowed null. buy_amount/sell_amount/net_amount are CNY. Vendor hm_name/hm_orgs labels are not verified ownership or PIT evidence.",
    secondary_partition={"param": "hm_name", "discovery": "hot_money_names"},
    secondary_partition_gap="Optional hm_name partitions require separate complete discovery from hm_list and observed details; neither a capped list nor labels found in a capped detail response prove full coverage.",
)


def _enabled(config):
    values = config.get("trading_event_apis", tuple(TRADING_EVENT_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(api, str) or api not in TRADING_EVENT_CONTRACTS for api in values
    ):
        raise ValueError("trading_event_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("trading_event_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "trading_event_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - TRADING_EVENT_CONTRACTS.keys():
        raise ValueError("Unknown API in trading_event_history_start")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        configured = _parse(value) if value is not None else None
        floor = TRADING_EVENT_CONTRACTS[api]["history_start"]
        floor = _parse(floor) if floor else None
        result[api] = (
            None
            if api == "hm_list"
            else max(configured or floor, floor)
            if floor
            else configured
        )
    return result


def trading_event_prerequisites(identifiers=None, enabled_apis=None, config=None):
    """Report unresolved coverage; identifiers cannot certify a complete universe."""
    config = dict(config or {})
    if enabled_apis is not None:
        config["trading_event_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = TRADING_EVENT_CONTRACTS[api]
        for kind in (
            "history_gap",
            "pagination_gap",
            "discovery_gap",
            "refresh_gap",
            "multiplicity_gap",
            "secondary_partition_gap",
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
        if api != "hm_list":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope_or_discovery"
                    if starts[api] is None
                    else "planned_scope_does_not_prove_earlier_history_absent",
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
                    "reason": "explicit_hidden_field_request_and_response_schema_audit_required",
                    "requested_fields": spec["requested_fields"],
                }
            )
    return gaps


def iter_trading_event_jobs(config, today, identifiers=None):
    """Recent snapshots/days first, then fair lazy exact-day history.

    No calendar-open filter or dependence on a currently listed universe. Preserve
    holidays/empty dates as observations; neither is a completeness certificate.
    """
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
        fields = ",".join(FIELDS[api])
        if api == "hm_list":
            yield {
                "api_name": api,
                "params": {},
                "fields": fields,
                "priority": 20,
                "epoch": epoch,
            }
            continue
        start = starts[api]
        day = max(recent, start or recent)
        while day <= today:
            yield {
                "api_name": api,
                "params": {"trade_date": day.strftime("%Y%m%d")},
                "fields": fields,
                "priority": 20,
                "epoch": epoch,
            }
            day += timedelta(days=1)
        if start and start < recent:
            histories[api] = start
    while histories:
        for api, day in tuple(histories.items()):
            yield {
                "api_name": api,
                "params": {"trade_date": day.strftime("%Y%m%d")},
                "fields": ",".join(FIELDS[api]),
                "priority": 55,
                "epoch": "history",
            }
            day += timedelta(days=1)
            if day >= recent:
                del histories[api]
            else:
                histories[api] = day
