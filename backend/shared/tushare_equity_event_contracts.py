"""Pure read-only plans for equity disclosures, ownership and corporate events.

Report periods, announcement dates, execution dates and unlock dates are separate
axes. No credentials, network, storage, pagination invention or account proof.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "dividend": [
        "ts_code",
        "end_date",
        "ann_date",
        "div_proc",
        "stk_div",
        "stk_bo_rate",
        "stk_co_rate",
        "cash_div",
        "cash_div_tax",
        "record_date",
        "ex_date",
        "pay_date",
        "div_listdate",
        "imp_ann_date",
        "base_date",
        "base_share",
    ],
    "stk_holdernumber": ["ts_code", "ann_date", "end_date", "holder_num"],
    "stk_holdertrade": [
        "ts_code",
        "ann_date",
        "holder_name",
        "holder_type",
        "in_de",
        "change_vol",
        "change_ratio",
        "after_share",
        "after_ratio",
        "avg_price",
        "total_share",
        "begin_date",
        "close_date",
    ],
    "repurchase": [
        "ts_code",
        "ann_date",
        "end_date",
        "proc",
        "exp_date",
        "vol",
        "amount",
        "high_limit",
        "low_limit",
    ],
    "share_float": [
        "ts_code",
        "ann_date",
        "float_date",
        "float_share",
        "float_ratio",
        "holder_name",
        "share_type",
    ],
    "top10_holders": [
        "ts_code",
        "ann_date",
        "end_date",
        "holder_name",
        "hold_amount",
        "hold_ratio",
        "hold_float_ratio",
        "hold_change",
        "holder_type",
    ],
    "top10_floatholders": [
        "ts_code",
        "ann_date",
        "end_date",
        "holder_name",
        "hold_amount",
        "hold_ratio",
        "hold_float_ratio",
        "hold_change",
        "holder_type",
    ],
}

# doc id, cap/alarm, points, response natural-key candidates
_DOCS = {
    "dividend": (
        103,
        2000,
        2000,
        (
            "ts_code",
            "end_date",
            "ann_date",
            "div_proc",
            "imp_ann_date",
            "record_date",
            "ex_date",
            "pay_date",
        ),
    ),
    "stk_holdernumber": (166, 3000, 2000, ("ts_code", "ann_date", "end_date")),
    "stk_holdertrade": (
        175,
        3000,
        2000,
        (
            "ts_code",
            "ann_date",
            "holder_name",
            "holder_type",
            "in_de",
            "begin_date",
            "close_date",
        ),
    ),
    "repurchase": (
        124,
        2000,
        2000,
        ("ts_code", "ann_date", "end_date", "proc", "exp_date"),
    ),
    "share_float": (
        160,
        6000,
        120,
        ("ts_code", "ann_date", "float_date", "holder_name", "share_type"),
    ),
    "top10_holders": (
        61,
        1000,
        2000,
        ("ts_code", "end_date", "ann_date", "holder_name", "holder_type"),
    ),
    "top10_floatholders": (
        62,
        1000,
        2000,
        ("ts_code", "end_date", "ann_date", "holder_name", "holder_type"),
    ),
}
TOP10 = ("top10_holders", "top10_floatholders")
ANNOUNCEMENTS = ("stk_holdernumber", "stk_holdertrade", "repurchase")
DEPENDENCIES = {"dividend": ("stocks",), **dict.fromkeys(TOP10, ("stocks",))}
INPUT_FIELDS = {
    "dividend": ("ts_code", "ann_date", "record_date", "ex_date", "imp_ann_date"),
    "stk_holdernumber": ("ts_code", "ann_date", "enddate", "start_date", "end_date"),
    "stk_holdertrade": (
        "ts_code",
        "ann_date",
        "start_date",
        "end_date",
        "trade_type",
        "holder_type",
    ),
    "repurchase": ("ann_date", "start_date", "end_date"),
    "share_float": ("ts_code", "ann_date", "float_date", "start_date", "end_date"),
    **dict.fromkeys(TOP10, ("ts_code", "period", "ann_date", "start_date", "end_date")),
}
EQUITY_EVENT_CONTRACTS = {}
for _api, (_doc, _cap, _points, _keys) in _DOCS.items():
    _required = (
        ("ts_code", "ann_date", "end_date")
        if _api == "stk_holdernumber"
        else ("ts_code",)
    )
    _start = "20000101" if _api == "dividend" else None
    _spec = _contract(
        _cap,
        _keys,
        required=_required,
        nullable=tuple(f for f in FIELDS[_api] if f not in _required),
        extra=FIELDS[_api],
        split=_api != "dividend",
        start=_start,
        rpm=50,
        cap_verified=_api not in TOP10 + ("repurchase",),
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=False,
        documented_requests_per_minute=200 if _api == "stk_holdernumber" else None,
        dependencies=list(DEPENDENCIES.get(_api, ())),
        input_fields=list(INPUT_FIELDS[_api]),
        history_bound_verified=_start is not None,
        history_gap=None if _start else "official_earliest_date_unspecified",
        split_axis="report_period"
        if _api in TOP10
        else "float_date"
        if _api == "share_float"
        else "announcement_date",
        preserve_distinct_rows=_api != "stk_holdernumber",
        row_identity_note="No unique event/holder identifier is documented. For preserve_distinct_rows datasets, the parent reader must add its generated _row_identity to deduplication keys; never request that derived field upstream. Conflicting distinct rows remain separate until source identity is verified.",
        pagination_gap="No offset/limit input is documented. Keep saturation as a gap if documented date/code subdivision is exhausted.",
        revision_note="Retain original observations and announcement/report/execution dates independently; observation time is not proof of historical availability. Recent-only overlap cannot certify older revisions.",
    )
    if _api != "repurchase" and _api not in TOP10:
        _spec.update(
            saturation_fallback="stocks",
            saturation_param="ts_code",
            saturation_dependencies=["stocks"],
        )
    EQUITY_EVENT_CONTRACTS[_api] = _spec

EQUITY_EVENT_CONTRACTS["dividend"].update(
    hidden_fields=["base_date", "base_share"],
    parameter_note="At least one of ts_code/ann_date/record_date/ex_date/imp_ann_date is mandatory. No start_date/end_date/period inputs exist.",
    history_scope_note="Each stock-only discovery requests all supplier history, even when a configured date scope is narrower. Documented source start is 20000101; future announced execution dates are retained.",
    saturation_gap="A stock-only capped response needs explicit ann_date/imp_ann_date partitions; do not invent generic date ranges or assume its last row is the earliest history.",
    refresh_gap="Old records changed without a recent announcement/implementation announcement require a separate historical revision sweep.",
    field_note="cash_div is after-tax; cash_div_tax is before-tax. base_share is in ten-thousand shares; implementation stages and their dates remain separate.",
)
EQUITY_EVENT_CONTRACTS["stk_holdernumber"]["parameter_note"] = (
    "Input enddate means observation cutoff; input start_date/end_date bound announcements. Output end_date means cutoff, not the announcement-window end."
)
EQUITY_EVENT_CONTRACTS["stk_holdertrade"].update(
    hidden_fields=["begin_date", "close_date"],
    parameter_note="Input trade_type is IN/DE while output is in_de. Leave trade_type and holder_type unfiltered to include all reported types.",
)
EQUITY_EVENT_CONTRACTS["repurchase"].update(
    cap_note="2000 is the documented no-parameter default, not a verified hard cap for filtered requests. Use it only as a conservative saturation alarm.",
    parameter_note="No ts_code input exists; announcement ranges can be bisected, but a saturated single day has no documented stock-code or offset fallback.",
)
EQUITY_EVENT_CONTRACTS["share_float"].update(
    permission_note="Detail page says 120 points, while the overview says 3000. Account capability remains unprobed.",
    parameter_note="start_date/end_date filter unlock dates; ann_date independently discovers announcements, including unlock dates after today. Never translate an ann_date request into an unlock-date range.",
    historical_request_axes=["float_date", "ann_date"],
    future_note="Announcement-date history and recent overlap retain already-announced future unlocks without inventing a future-date cutoff. Unknown announcement-history prefixes remain explicit gaps.",
)
for _api in TOP10:
    EQUITY_EVENT_CONTRACTS[_api].update(
        cap_note="Numerical supplier cap is unspecified. 1000 is an operational alarm, not a completeness guarantee; prefer per-stock calendar-year report intervals and bisect if saturated.",
        parameter_note="ts_code is required. start_date/end_date are report-period boundaries, period is an exact report period, ann_date is an exact announcement day. There is no all-market quarterly VIP alias in these reviewed docs.",
        refresh_gap="The rolling 400-day report-period refresh does not discover late changes to older reports; a separate announcement-day or full-history revision sweep is required.",
    )
EQUITY_EVENT_CONTRACTS["top10_floatholders"]["field_note"] = (
    "hold_change=0 means unchanged; null means newly entering. Do not fill null with zero. This dataset is distinct from top10_holders."
)


def _enabled(config):
    values = config.get("equity_event_apis", tuple(EQUITY_EVENT_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or v not in EQUITY_EVENT_CONTRACTS for v in values
    ):
        raise ValueError(
            "equity_event_apis must list known EQUITY_EVENT_CONTRACTS APIs"
        )
    return tuple(dict.fromkeys(values))


def _stocks(identifiers):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to records")
    values = identifiers.get("stocks", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("stocks must contain supplier codes or discovery records")
    codes = set()
    for row in values:
        code = row.get("ts_code") if isinstance(row, dict) else row
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code):
            raise ValueError("Invalid stock supplier identifier")
        codes.add(code)
    return sorted(codes)


def _starts(config, enabled):
    setting = config.get("equity_event_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "equity_event_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and set(setting) - EQUITY_EVENT_CONTRACTS.keys():
        raise ValueError("Unknown API in equity_event_history_start")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        if value is None:
            value = EQUITY_EVENT_CONTRACTS[api]["history_start"]
        result[api] = _parse(value) if value is not None else None
    return result


def equity_event_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["equity_event_apis"] = enabled_apis
    enabled = _enabled(config)
    stocks = _stocks(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = EQUITY_EVENT_CONTRACTS[api]
        if spec["dependencies"] or spec.get("saturation_fallback"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["stocks"],
                    "reason": "stored_discovery_completeness_unverified"
                    if stocks
                    else "awaiting_stored_stock_discovery",
                    "universe_complete": False,
                    "observed_codes": len(stocks),
                }
            )
        if spec["history_gap"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope_or_discovery"
                    if starts[api] is None
                    else "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        for kind in ("cap_note", "refresh_gap", "future_gap"):
            if spec.get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": spec[kind],
                    }
                )
    return gaps


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def _window(start, end):
    return {"start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")}


def iter_equity_event_jobs(config, today, identifiers=None):
    """Recent announcements first, then bounded report windows and stock history.

    Recent top10 refresh uses report periods, not announcement ranges. Initial
    dividend history is stock-only because the API cannot accept date ranges.
    Missing stock discovery never invents an all-market top10 request.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    stocks = _stocks(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    if any(s and s > today for s in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    recent = today - timedelta(days=6)
    report_recent = today - timedelta(days=399)
    for api in enabled:
        if api in ANNOUNCEMENTS or api == "share_float":
            begin = max(recent, starts[api] or recent)
            yield _job(api, _window(begin, today), epoch, 20)
    day = recent
    while day <= today:
        stamp = day.strftime("%Y%m%d")
        if "dividend" in enabled and day >= (starts["dividend"] or recent):
            for axis in ("ann_date", "imp_ann_date"):
                yield _job("dividend", {axis: stamp}, epoch, 20)
        if "share_float" in enabled:
            # No float_date/end_date restriction: future events must survive.
            yield _job("share_float", {"ann_date": stamp}, epoch, 20)
        day += timedelta(days=1)
    for code in stocks:
        for api in TOP10:
            if api in enabled:
                begin = max(report_recent, starts[api] or report_recent)
                yield _job(api, {"ts_code": code, **_window(begin, today)}, epoch, 20)
    # One unbounded stock-only discovery per dividend/unknown-bound top10 history.
    for code in stocks:
        for api in enabled:
            if api == "dividend" or (api in TOP10 and starts[api] is None):
                yield _job(api, {"ts_code": code}, "history", 40)
    cursors = {
        api: start
        for api, start in starts.items()
        if api != "dividend"
        and start
        and start < (report_recent if api in TOP10 else recent)
    }
    while cursors:
        for api, begin in tuple(cursors.items()):
            ceiling = (report_recent if api in TOP10 else recent) - timedelta(days=1)
            end = (
                min(date(begin.year, 12, 31), ceiling)
                if api in TOP10
                else min(
                    date(
                        begin.year, begin.month, monthrange(begin.year, begin.month)[1]
                    ),
                    ceiling,
                )
            )
            params = _window(begin, end)
            if api in TOP10:
                for code in stocks:
                    yield _job(api, {"ts_code": code, **params}, "history", 40)
            else:
                yield _job(api, params, "history", 40)
                if api == "share_float":
                    # Past announcements can describe future unlocks. Backfill
                    # this second axis without constraining float_date to today.
                    announced = begin
                    while announced <= end:
                        yield _job(
                            api,
                            {"ann_date": announced.strftime("%Y%m%d")},
                            "history",
                            40,
                        )
                        announced += timedelta(days=1)
            following = end + timedelta(days=1)
            if following <= ceiling:
                cursors[api] = following
            else:
                del cursors[api]
