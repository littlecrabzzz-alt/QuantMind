"""Pure read-only supplier contracts for options, spot metals, FX and rates.

No network, credentials or data writes. Source identifiers remain unchanged only
at this supplier boundary. The common pipeline owns capture, splits and limits.
"""

from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "opt_basic": [
        "ts_code",
        "symbol",
        "exchange",
        "name",
        "per_unit",
        "opt_code",
        "opt_type",
        "call_put",
        "exercise_type",
        "exercise_price",
        "opt_multiplier",
        "s_month",
        "maturity_date",
        "list_price",
        "list_date",
        "delist_date",
        "last_edate",
        "last_ddate",
        "quote_unit",
        "min_price_chg",
    ],
    "opt_daily": [
        "ts_code",
        "trade_date",
        "exchange",
        "pre_settle",
        "pre_close",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "vol",
        "amount",
        "oi",
    ],
    "sge_basic": [
        "ts_code",
        "ts_name",
        "trade_type",
        "t_unit",
        "p_unit",
        "min_change",
        "price_limit",
        "min_vol",
        "max_vol",
        "trade_mode",
        "margin_rate",
        "liq_rate",
        "trade_time",
        "list_date",
    ],
    "sge_daily": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "price_avg",
        "change",
        "pct_change",
        "vol",
        "amount",
        "oi",
        "settle_vol",
        "settle_dire",
    ],
    "fx_obasic": [
        "ts_code",
        "name",
        "classify",
        "exchange",
        "min_unit",
        "max_unit",
        "pip",
        "pip_cost",
        "traget_spread",
        "min_stop_distance",
        "trading_hours",
        "break_time",
    ],
    "fx_daily": [
        "ts_code",
        "trade_date",
        "bid_open",
        "bid_close",
        "bid_high",
        "bid_low",
        "ask_open",
        "ask_close",
        "ask_high",
        "ask_low",
        "tick_qty",
        "exchange",
    ],
    "libor": ["date", "curr_type", "on", "1w", "1m", "2m", "3m", "6m", "12m"],
    "hibor": ["date", "on", "1w", "2w", "1m", "2m", "3m", "6m", "12m"],
    "wz_index": [
        "date",
        "comp_rate",
        "center_rate",
        "micro_rate",
        "cm_rate",
        "sdb_rate",
        "om_rate",
        "aa_rate",
        "m1_rate",
        "m3_rate",
        "m6_rate",
        "m12_rate",
        "long_rate",
    ],
    "gz_index": [
        "date",
        "d10_rate",
        "m1_rate",
        "m3_rate",
        "m6_rate",
        "m12_rate",
        "long_rate",
    ],
    "us_tycr": [
        "date",
        "m1",
        "m2",
        "m3",
        "m4",
        "m6",
        "y1",
        "y2",
        "y3",
        "y5",
        "y7",
        "y10",
        "y20",
        "y30",
    ],
    "us_trycr": ["date", "y5", "y7", "y10", "y20", "y30"],
    "us_tbr": [
        "date",
        "w4_bd",
        "w4_ce",
        "w8_bd",
        "w8_ce",
        "w13_bd",
        "w13_ce",
        "w17_bd",
        "w17_ce",
        "w26_bd",
        "w26_ce",
        "w52_bd",
        "w52_ce",
    ],
    "us_tltr": ["date", "ltc", "cmt", "e_factor"],
    "us_trltr": ["date", "ltr_avg"],
}

# (official doc id, cap/alarm, points, documented calendar-year lower bound)
_DOCS = {
    "opt_basic": (158, 6000, 5000, None),
    "opt_daily": (159, 15000, 2000, None),
    "sge_basic": (284, 100, 5000, None),
    "sge_daily": (285, 2000, 2000, None),
    "fx_obasic": (178, 1000, 2000, None),
    "fx_daily": (179, 1000, 2000, None),
    "libor": (152, 4000, 120, "19860101"),
    "hibor": (153, 4000, 120, "20020101"),
    "wz_index": (173, 10000, 2000, None),
    "gz_index": (174, 10000, 2000, None),
    "us_tycr": (219, 2000, 120, None),
    "us_trycr": (220, 2000, 120, None),
    "us_tbr": (221, 2000, 120, None),
    "us_tltr": (222, 2000, 120, None),
    "us_trltr": (223, 2000, 120, None),
}
BASICS = ("opt_basic", "sge_basic", "fx_obasic")
DAILY = ("opt_daily", "sge_daily", "fx_daily")
CURRENCIES = ("USD", "EUR", "JPY", "GBP", "CHF")
# Keep the unfiltered request too: these are documented venues, not a closed universe.
OPTION_EXCHANGES = ("SSE", "SZSE", "CFFEX", "DCE", "SHFE", "CZCE")
FAMILIES = {
    "opt_daily": "options",
    "sge_daily": "spot_metals",
    "fx_daily": "fx_instruments",
}
OTHER_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start) in _DOCS.items():
    _keys = (
        ("ts_code",)
        if _api in BASICS
        else ("ts_code", "trade_date")
        if _api in DAILY
        else ("date",)
    )
    if _api == "libor":
        _keys += ("curr_type",)
    _spec = _contract(
        _cap,
        _keys,
        nullable=tuple(f for f in FIELDS[_api] if f not in _keys),
        split=_api not in BASICS,
        rpm=50,
        extra=FIELDS[_api],
        start=_start,
        cap_verified=_api not in ("opt_basic", "fx_obasic", "wz_index", "gz_index"),
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=False,
        documented_requests_per_minute=None,
        history_bound_verified=_start is not None,
        history_gap=None
        if _start or _api in ("sge_basic", "fx_obasic")
        else "official_earliest_date_unspecified",
        dependencies=[],
        split_axis="list_date"
        if _api == "opt_basic"
        else "trade_date"
        if _api in DAILY
        else "date",
    )
    if _api in FAMILIES:
        _spec.update(
            saturation_fallback=FAMILIES[_api],
            saturation_param="ts_code",
            saturation_dependencies=[FAMILIES[_api]],
        )
    OTHER_CONTRACTS[_api] = _spec

OTHER_CONTRACTS["opt_basic"].update(
    cap_note="6000 is an unverified saturation alarm; official numerical cap and pagination are absent.",
    discovery_note="Unfiltered, all documented exchanges and exact list_date partitions; retain expired/delisted contracts. No list_status or date-range parameters exist.",
    revision_note="exercise_price and opt_multiplier are adjusted; preserve every observation, not point-in-time originals.",
    saturation_gap="A saturated listing date requires verified venue/underlying/call_put subdivision; no invented offset or start_date parameters.",
)
OTHER_CONTRACTS["opt_daily"]["permission_note"] = (
    "Detail docs say 2000 points and opt_basic 5000; permission overview gives different thresholds. Actual account must be probed."
)
OTHER_CONTRACTS["sge_basic"]["discovery_note"] = (
    "All currently documented contracts in one unfiltered call; historical retired-contract coverage is unspecified. Preserve union of every stored discovery and daily response."
)
OTHER_CONTRACTS["sge_daily"].update(
    pagination_gap="Description mentions pagination without cursor parameters; only documented date/code splits are allowed.",
    units_note="Session includes previous night; volume and amount are two-sided. vol=kg, amount=CNY, prices=CNY/gram; do not apply equity lot conventions.",
)
OTHER_CONTRACTS["fx_obasic"].update(
    cap_note="Docs promise all records in one call without numerical cap; 1000 is a conservative alarm.",
    discovery_note="Unfiltered classification includes FX, INDEX, COMMODITY, METAL, BUND, CRYPTO, FX_BASKET and future categories. Only FXCM is documented; expired instruments have no documented status filter.",
    parameter_note="Preserve the supplier field spelling traget_spread.",
)
OTHER_CONTRACTS["fx_daily"]["time_note"] = (
    "trade_date/start_date/end_date are supplier GMT dates. Preserve source date; do not reinterpret it as Shanghai trading date. Refresh overlaps the most recent seven supplied dates."
)
for _api in ("libor", "hibor"):
    OTHER_CONTRACTS[_api].update(
        history_source_url="https://tushare.pro/document/1?doc_id=108",
        history_note="Overview gives first calendar year only; January 1 is a conservative query boundary, not a proven first row for every currency/tenor.",
        revision_note="Null, zero and negative rates are valid. Missing observations do not prove a holiday or benchmark cessation; revisions require retained observations and historical refresh.",
    )
OTHER_CONTRACTS["libor"]["currencies"] = list(CURRENCIES)
for _api in ("wz_index", "gz_index"):
    OTHER_CONTRACTS[_api].update(
        cap_note="Officially unlimited whole-history response; 10000 is an operational saturation alarm, not a supplier cap.",
        full_history_discovery=True,
    )
OTHER_CONTRACTS["wz_index"]["history_note"] = (
    "2012-12-07 is the index publication date in docs, not an asserted first retained observation. Use unfiltered discovery and inspect earliest returned date."
)
OTHER_CONTRACTS["us_tycr"]["field_history_start"] = {"m4": "20221019"}
OTHER_CONTRACTS["us_tbr"]["field_history_start"] = {
    "w17_bd": "20221019",
    "w17_ce": "20221019",
}


def _enabled(config):
    values = config.get("other_apis", tuple(OTHER_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or v not in OTHER_CONTRACTS for v in values
    ):
        raise ValueError("other_apis must list known OTHER_CONTRACTS APIs")
    return tuple(dict.fromkeys(values))


def _identifiers(identifiers):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to records")
    result = {}
    for family in FAMILIES.values():
        values = identifiers.get(family, ())
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"{family} must be a list of codes or discovery records")
        codes = set()
        for row in values:
            code = row.get("ts_code") if isinstance(row, dict) else row
            # Spot symbols use (), + and dots; options use hyphens; no suffix rewriting.
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 64
                or any(c.isspace() or ord(c) < 32 or c in ",\\\"'" for c in code)
            ):
                raise ValueError(f"Invalid supplier identifier in {family}")
            codes.add(code)
        result[family] = sorted(codes)
    return result


def _starts(config, enabled):
    setting = config.get("other_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("other_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and set(setting) - OTHER_CONTRACTS.keys():
        raise ValueError("Unknown API in other_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        if value is None:
            value = OTHER_CONTRACTS[api]["history_start"]
        starts[api] = _parse(value) if value is not None else None
    return starts


def other_prerequisites(identifiers=None, enabled_apis=None, config=None):
    """Surface completeness gaps without preventing independent recent requests."""
    config = dict(config or {})
    if enabled_apis is not None:
        config["other_apis"] = enabled_apis
    enabled = _enabled(config)
    ids = _identifiers(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = OTHER_CONTRACTS[api]
        family = FAMILIES.get(api)
        if family and not ids[family]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [family],
                    "reason": "awaiting_complete_stored_discovery_for_saturation",
                }
            )
        if spec["history_gap"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_explicit_scope_or_evidence"
                    if starts[api] is None
                    else "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        known = spec["history_start"]
        if known and starts[api] and starts[api] > _parse(known):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "configured_start_excludes_documented_history",
                }
            )
    return gaps


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def _range_jobs(api, start, end, epoch, priority):
    for currency in CURRENCIES if api == "libor" else (None,):
        params = {
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
        }
        if currency:
            params["curr_type"] = currency
        yield _job(api, params, epoch, priority)


def _day_job(api, day, epoch, priority):
    key = "list_date" if api == "opt_basic" else "trade_date"
    return _job(api, {key: day.strftime("%Y%m%d")}, epoch, priority)


def iter_other_jobs(config, today, identifiers=None):
    """Recent first, then all configured dates, interleaved across APIs.

    Macro history uses bounded calendar years (<=366 rows/currency); market data
    and option discovery use individual dates. Missing history bounds never
    become an invented full-history start. All response versions must be retained.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    _identifiers(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    recent = today - timedelta(days=6)
    for api in enabled:
        if api in BASICS or api in ("wz_index", "gz_index"):
            yield _job(api, {}, epoch, 20)
        if api == "opt_basic":
            for exchange in OPTION_EXCHANGES:
                yield _job(api, {"exchange": exchange}, epoch, 20)
        if api not in BASICS + DAILY:
            yield from _range_jobs(
                api, max(recent, starts[api] or recent), today, epoch, 20
            )
    day = recent
    while day <= today:
        for api in enabled:
            if api in DAILY + ("opt_basic",) and day >= (starts[api] or recent):
                yield _day_job(api, day, epoch, 20)
        day += timedelta(days=1)
    cursors = {
        api: start
        for api, start in starts.items()
        if start and start < recent and api not in ("sge_basic", "fx_obasic")
    }
    # One bounded partition per API per round; avoid millions of materialized jobs.
    while cursors:
        for api, start in tuple(cursors.items()):
            if api in DAILY + ("opt_basic",):
                end = start
                yield _day_job(api, start, "history", 40)
            else:
                end = min(date(start.year, 12, 31), recent - timedelta(days=1))
                yield from _range_jobs(api, start, end, "history", 40)
            next_start = end + timedelta(days=1)
            if next_start < recent:
                cursors[api] = next_start
            else:
                del cursors[api]
