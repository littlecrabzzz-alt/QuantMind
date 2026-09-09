"""Pure DC historical board-member and daily price acquisition contracts."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "dc_member": "trade_date ts_code con_code name".split(),
    "dc_daily": "ts_code trade_date close open high low change pct_change vol amount swing turnover_rate category".split(),
}
INPUT_FIELDS = {
    "dc_member": "ts_code con_code trade_date start_date end_date".split(),
    "dc_daily": "ts_code trade_date start_date end_date idx_type".split(),
}
DAILY_VARIANTS = [{"idx_type": value} for value in ("概念板块", "行业板块", "地域板块")]
_DOCS = {
    "dc_member": (363, 5000, "20241220", ("trade_date", "ts_code", "con_code")),
    "dc_daily": (382, 2000, "20200101", ("ts_code", "trade_date", "category")),
}
DC_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _start, _keys) in _DOCS.items():
    required = (
        ("trade_date", "ts_code", "con_code")
        if _api == "dc_member"
        else ("ts_code", "trade_date")
    )
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in required],
        extra=FIELDS[_api],
        start=_start,
        rpm=50,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[],
        permission_status="unprobed",
        minimum_points=6000,
        independent_permission=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        permission_note="The page specifies 6000 points, not verified account access. No endpoint-specific frequency/daily ceiling or independent entitlement is stated; 50 rpm is a local operational ceiling.",
        dependencies=[],
        saturation_fallback="dc_indices",
        saturation_param="ts_code",
        saturation_dependencies=["dc_indices"],
        split_axis="trade_date",
        date_field="trade_date",
        preserve_distinct_rows=True,
        request_identity_fields=["idx_type"] if _api == "dc_daily" else [],
        required_params=["idx_type"] if _api == "dc_daily" else [],
        history_bound_verified=False,
        history_start_precision="day" if _api == "dc_member" else "year",
        history_partition="exact_day_v1",
        pagination_gap="No offset/limit inputs are documented. Date bisection and per-board ts_code filters are legal, but historical/retired board discovery is not proven complete; saturated terminal partitions remain blocked.",
        discovery_gap="Plan dates without requiring a current board inventory. Future saturation fanout must use DC source identities discovered in dc_index/dc_daily/dc_member, including retired observations. Neither THS codes nor a current DC snapshot proves this historical universe complete.",
        history_gap="The documented start is a provider scope statement, not a measured first row or proof of no earlier records. Configured later scopes leave earlier documented history unrequested.",
        pit_gap="trade_date describes the historical observation date, not when a user could know the membership or closing values. Historical rows and immutable fetch timestamps do not prove point-in-time availability or intraday causality.",
        refresh_gap="Seven recent calendar days overlap; this does not certify old revisions, deletions or backdated member changes complete.",
        field_selection_note="All reviewed output columns are default Y; request them explicitly, validate presence with documented optional nulls retained, and preserve newly returned unknown columns. fields='' is not a schema-completeness certificate.",
        namespace_note="ts_code is an opaque DC board identifier, even if a future spelling resembles a stock. Preserve source_ts_code and isolate dc_indices from THS/index/stock namespaces.",
    )
    DC_EXTRA_CONTRACTS[_api] = spec

DC_EXTRA_CONTRACTS["dc_member"].update(
    history_note="Official page explicitly offers daily historical members from 2024-12-20. Do not substitute the latest THS member snapshot or synthesize in_date/out_date/weights.",
    member_namespace_note="con_code is a source constituent security; official examples include SH, SZ and BJ suffixes. Preserve source_con_code and the original value. Unknown or future foreign forms need evidence, not inferred A-share conversion.",
    saturation_gap="After a capped exact-day exact-board request, con_code is a legal second filter but requires complete historical member discovery. The current single-axis runtime cannot exhaust that second dimension; keep blocked, do not claim returned members exhaust the board.",
)
DC_EXTRA_CONTRACTS["dc_daily"].update(
    documented_idx_types=[v["idx_type"] for v in DAILY_VARIANTS],
    category_gap="idx_type is optional in the official input table. Plan all three explicit categories to avoid reliance on defaults; output category differs in name and its literal mapping is not demonstrated. Keep request identity separate, require actual filter/row evidence before claiming coverage.",
    history_note="The official historical lower bound is year 2020; 20200101 is a planning floor only, not a certified first trading day.",
    unit_note="OHLC/change are index points; vol is shares and amount is CNY. Do not inherit THS volume lots or DC index total_mv ten-thousand-CNY units. Preserve signed and nullable numeric source values.",
)


def _enabled(config):
    values = config.get("dc_extra_apis", tuple(DC_EXTRA_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(api, str) or api not in DC_EXTRA_CONTRACTS for api in values
    ):
        raise ValueError("dc_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("dc_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("dc_extra_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and setting.keys() - DC_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in dc_extra_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        floor = _parse(DC_EXTRA_CONTRACTS[api]["history_start"])
        starts[api] = max(floor, _parse(value)) if value is not None else floor
    return starts


def dc_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["dc_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = DC_EXTRA_CONTRACTS[api]
        for kind in (
            "pagination_gap",
            "discovery_gap",
            "history_gap",
            "pit_gap",
            "refresh_gap",
            "saturation_gap",
            "category_gap",
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
                "reason": "configured_scope_not_verified_complete",
                "planned_start": starts[api].strftime("%Y%m%d"),
                "documented_start": spec["history_start"],
                "documented_start_precision": spec["history_start_precision"],
            }
        )
    return gaps


def _days(api, begin, end):
    day = begin
    while day <= end:
        for variant in DAILY_VARIANTS if api == "dc_daily" else [{}]:
            yield {"trade_date": day.strftime("%Y%m%d"), **variant}
        day += timedelta(days=1)


def iter_dc_extra_jobs(config, today, identifiers=None):
    """All-board recent days followed by fair, lazy historical date partitions."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api in enabled:
        start = starts[api]
        for params in _days(api, max(start, recent), today):
            yield {
                "api_name": api,
                "params": params,
                "fields": ",".join(FIELDS[api]),
                "priority": 20,
                "epoch": epoch,
            }
        if start < recent:
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
