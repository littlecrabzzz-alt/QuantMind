"""Six research/financial contracts; pure requests, no entitlement assumptions.

All source fields are retained. Generated row identity belongs to the parent
reader, never the supplier fields parameter. Observed revisions are not PIT.
Official pages reviewed 2026-09-09; operational guards are not measured caps.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
from itertools import zip_longest
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "fina_audit": "ts_code ann_date end_date audit_result audit_fees audit_agency audit_sign".split(),
    "fina_mainbz": "ts_code end_date bz_item bz_code bz_sales bz_profit bz_cost curr_type update_flag".split(),
    "disclosure_date": "ts_code ann_date end_date pre_date actual_date modify_date".split(),
    "report_rc": "ts_code name report_date report_title report_type classify org_name author_name quarter op_rt op_pr tp np eps pe rd roe ev_ebitda rating max_price min_price imp_dg create_time".split(),
    "stk_surv": "ts_code name surv_date fund_visitors rece_place rece_mode rece_org org_type comp_rece content".split(),
    "broker_recommend": "month broker ts_code name".split(),
}
INPUT_FIELDS = {
    "fina_audit": "ts_code ann_date start_date end_date period".split(),
    "fina_mainbz": "ts_code period type start_date end_date".split(),
    "disclosure_date": "ts_code end_date pre_date ann_date actual_date".split(),
    "report_rc": "ts_code report_date start_date end_date".split(),
    "stk_surv": "ts_code trade_date start_date end_date".split(),
    "broker_recommend": ["month"],
}
# api: doc, conservative row guard, documented cap, points, required source fields,
# natural identity components (the parent must append its raw-row identity).
_DOCS = {
    "fina_audit": (
        80,
        100,
        None,
        2000,
        ("ts_code", "ann_date", "end_date"),
        ("ts_code", "ann_date", "end_date", "audit_agency", "audit_sign"),
    ),
    "fina_mainbz": (
        81,
        100,
        100,
        2000,
        ("ts_code", "end_date", "bz_item"),
        ("ts_code", "end_date", "bz_code", "bz_item", "curr_type"),
    ),
    "disclosure_date": (
        162,
        6000,
        6000,
        2000,
        ("ts_code", "end_date"),
        ("ts_code", "end_date", "ann_date"),
    ),
    "report_rc": (
        292,
        3000,
        3000,
        8000,
        ("ts_code", "report_date"),
        (
            "ts_code",
            "report_date",
            "org_name",
            "author_name",
            "report_title",
            "report_type",
            "classify",
            "quarter",
        ),
    ),
    "stk_surv": (
        275,
        400,
        400,
        5000,
        ("ts_code", "surv_date"),
        (
            "ts_code",
            "surv_date",
            "rece_org",
            "fund_visitors",
            "rece_place",
            "rece_mode",
            "comp_rece",
            "org_type",
        ),
    ),
    "broker_recommend": (
        267,
        1000,
        1000,
        6000,
        ("month", "broker", "ts_code"),
        ("month", "broker", "ts_code"),
    ),
}
RESEARCH_EXTRA_CONTRACTS = {}
for _api, (_doc, _guard, _cap, _points, _required, _keys) in _DOCS.items():
    _spec = _contract(
        _guard,
        _keys,
        required=_required,
        nullable=tuple(f for f in FIELDS[_api] if f not in _required),
        extra=FIELDS[_api],
        start="20100101" if _api == "report_rc" else None,
        split=_api not in ("disclosure_date", "broker_recommend"),
        rpm=50,
        cap_verified=False,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        documented_row_cap=_cap,
        minimum_points=_points,
        permission_status="unprobed",
        independent_permission=False,
        documented_requests_per_minute=None,
        dependencies=["stocks"] if _api in ("fina_audit", "fina_mainbz") else [],
        history_bound_verified=_api == "report_rc",
        history_gap=None
        if _api == "report_rc"
        else "official_earliest_date_unspecified",
        preserve_distinct_rows=True,
        row_identity_note="Append generated _row_identity to reader keys; preserve all raw columns and observations. No globally unique source row ID is documented. Exact duplicate payloads may coalesce, conflicting source rows must not.",
        revision_note="Natural identity groups possible revisions; different institutions, authors, forecast quarters, business segments and currencies remain distinct. No automatic latest-version collapse. _fetched_at is system observation time, not historical publication availability.",
        pagination_gap="No offset/limit parameter appears in the reviewed input table. Do not invent pagination; keep a gap when documented date/code subdivision is exhausted.",
        refresh_gap="Recent overlap is an operational refresh, not proof that older source revisions are absent; an explicit old-history revision sweep remains necessary.",
    )
    if _api in ("disclosure_date", "report_rc", "stk_surv"):
        _spec.update(
            saturation_fallback="stocks",
            saturation_param="ts_code",
            saturation_dependencies=["stocks"],
        )
    RESEARCH_EXTRA_CONTRACTS[_api] = _spec

RESEARCH_EXTRA_CONTRACTS["fina_audit"].update(
    split_axis="announcement_date",
    date_field="ann_date",
    parameter_note="ts_code is required. start_date/end_date bound announcements; output end_date and input period mean report period.",
    cap_note="The page publishes no maximum rows. 100 is an operational alarm, not evidence of a supplier cap or of completeness below it.",
    history_scope_note="One stock-only initial request preserves all available supplier history, including records earlier than a configured scope. A capped response without a documented lower bound remains a gap.",
    units={"audit_fees": "CNY"},
)
RESEARCH_EXTRA_CONTRACTS["fina_mainbz"].update(
    split_axis="report_period",
    date_field="end_date",
    types=["P", "D", "I"],
    parameter_note="Required ts_code; type=P product, D region, I industry. start_date/end_date bound report periods, not announcements. Separate fina_mainbz_vip is documented at 5000 points but is outside this six-API implementation.",
    request_identity_fields=["type"],
    row_identity_note="Keep bz_code, bz_item and curr_type in identity plus raw-row identity. Parent must retain request type in provenance/identity when bz_code is missing; do not merge indistinguishable P/D/I payloads across requests.",
    refresh_cadence="weekly",
    refresh_gap="No announcement timestamp is supplied. Refresh prior/current-year report periods once per completed week; late restatements of older periods require an explicit revision sweep. The open week waits until the next completed-week anchor.",
    history_scope_note="Known scope uses fixed calendar-year windows per stock/type; unknown scope uses an unfiltered stock/type discovery request, whose 100-row saturation cannot prove complete history.",
    units={"bz_sales": "CNY", "bz_profit": "CNY", "bz_cost": "CNY"},
)

# The VIP endpoint is intentionally runtime-only.  It is planned by the exact
# quarterly batch tool, not by the stock/window research-extra planner above.
FINA_MAINBZ_VIP_CONTRACT = {
    **RESEARCH_EXTRA_CONTRACTS["fina_mainbz"],
    "input_fields": ["period", "type"],
    "minimum_points": 5000,
    "dependencies": [],
    "split": False,
    "row_cap_verified": True,
    "catalog_api": "fina_mainbz_vip",
    "dataset_identity": "fina_mainbz",
    "parameter_note": "Exact period=quarter end and type=P product, D region, I industry. The VIP endpoint returns all companies for that request; do not add ts_code, start_date, end_date, offset, page or limit.",
    "pagination_gap": "The reviewed input table documents no offset/page/limit. A 100-row response for one period/type is a terminal saturated request and remains an explicit completeness gap.",
    "history_scope_note": "Official earliest history is unspecified. Exact quarterly requests do not prove earlier periods complete.",
    "revision_note": "Output end_date is report period. No announcement timestamp is supplied, so known_at and PIT availability remain unverified.",
}


def _fina_mainbz_vip_start(config):
    value = config.get("fina_mainbz_vip_history_start", config.get("history_start"))
    if value is None:
        raise ValueError("fina_mainbz_vip_history_start must be configured")
    return _parse(value)


def fina_mainbz_vip_prerequisites(identifiers=None, config=None):
    del identifiers
    _fina_mainbz_vip_start(config or {})
    return [
        {
            "api_name": "fina_mainbz_vip",
            "dependencies": [],
            "reason": "configured_scope_does_not_prove_earlier_history_absent",
        },
        {
            "api_name": "fina_mainbz_vip",
            "dependencies": [],
            "reason": "pagination_gap",
            "detail": FINA_MAINBZ_VIP_CONTRACT["pagination_gap"],
        },
        {
            "api_name": "fina_mainbz_vip",
            "dependencies": [],
            "reason": "pit_unverified",
            "detail": FINA_MAINBZ_VIP_CONTRACT["revision_note"],
        },
    ]


def iter_fina_mainbz_vip_jobs(config, today, identifiers=None):
    """Plan exact quarter/type requests without inventing paging dimensions."""
    del identifiers
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    start = _fina_mainbz_vip_start(config)
    if start > today:
        raise ValueError("History start cannot be after today")
    for year in range(today.year, start.year - 1, -1):
        for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            period = date(year, month, day)
            if not start <= period <= today:
                continue
            for kind in ("P", "D", "I"):
                yield _job(
                    "fina_mainbz_vip",
                    {"period": period.strftime("%Y%m%d"), "type": kind},
                    "history",
                    40,
                )


RESEARCH_EXTRA_CONTRACTS["disclosure_date"].update(
    split_axis="exact_report_period_or_announcement_date",
    date_field="end_date",
    hidden_fields=["modify_date"],
    parameter_note="No start_date/end_date range: end_date alone is an exact quarter-end report period; ann_date is latest announcement, pre_date planned disclosure, actual_date actual disclosure. modify_date is a revision record, not a scalar date filter.",
    future_gap="An unfiltered current snapshot plus recent announcement dates retains future plans; saturation must fan out through the complete stock universe. Do not reject future pre_date/end_date as invalid observations.",
)
RESEARCH_EXTRA_CONTRACTS["report_rc"].update(
    split_axis="report_date",
    date_field="report_date",
    hidden_fields=["imp_dg", "create_time"],
    permission_note="2000 points: trial 10/day; 8000: formal 100000/day; above 10000: no daily total limit stated. Account access and per-minute limits remain unprobed. This structured forecast API is not the independently purchased research_report original-document API.",
    documented_update_window="19:00-22:00 daily; source timezone not specified on page",
    history_scope_note="Page says data starts in 2010; 20100101 is the enclosing year boundary, not a verified first trading/report date.",
    parameter_note="report_date/ranges select report publication dates; quarter is forecast horizon. create_time is Tushare update time, not proof of when the report first became public.",
    units={
        "op_rt": "10000 CNY",
        "op_pr": "10000 CNY",
        "tp": "10000 CNY",
        "np": "10000 CNY",
        "eps": "CNY",
    },
)
RESEARCH_EXTRA_CONTRACTS["stk_surv"].update(
    split_axis="survey_date",
    date_field="surv_date",
    hidden_fields=["content"],
    parameter_note="Input trade_date and date ranges select survey dates; output surv_date is the survey date, not market trading date or publication time. One visit may produce many institution/participant rows.",
    content_type_gap="Official output type for hidden content is None; preserve the raw returned value, do not assume string/PDF URL or invent an attachment.",
)
RESEARCH_EXTRA_CONTRACTS["broker_recommend"].update(
    split_axis="month",
    date_field="month",
    parameter_note="Only month=YYYYMM is documented and required. No broker or stock filter exists; 1000-row saturation for a single month remains unresolved.",
    documented_update_window="Normally days 1-3 of current month",
)


def _enabled(config):
    values = config.get("research_extra_apis", tuple(RESEARCH_EXTRA_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or v not in RESEARCH_EXTRA_CONTRACTS for v in values
    ):
        raise ValueError("research_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _stocks(identifiers):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to records")
    values = identifiers.get("stocks", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("stocks must contain supplier codes or records")
    codes = set()
    for row in values:
        code = row.get("ts_code") if isinstance(row, dict) else row
        # Same opaque supplier-code boundary as the structured planner. A stored
        # T600018.SH remains distinct from 600018.SH; no suffix meaning inferred.
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]+\.[A-Z]+", code):
            raise ValueError("Invalid stock supplier identifier")
        codes.add(code)
    return sorted(codes)


def _starts(config, enabled):
    setting = config.get("research_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("research_extra_history_start must be YYYYMMDD or API mapping")
    if isinstance(setting, dict) and set(setting) - RESEARCH_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in research_extra_history_start")
    output = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        if value is None:
            value = RESEARCH_EXTRA_CONTRACTS[api]["history_start"]
        output[api] = _parse(value) if value is not None else None
    return output


def research_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["research_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    stocks = _stocks(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = RESEARCH_EXTRA_CONTRACTS[api]
        if spec["dependencies"] or spec.get("saturation_fallback"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["stocks"],
                    "reason": "stored_discovery_completeness_unverified"
                    if stocks
                    else "awaiting_stored_stock_discovery",
                    "observed_codes": len(stocks),
                    "universe_complete": False,
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
        for field in (
            "cap_note",
            "pagination_gap",
            "refresh_gap",
            "future_gap",
            "content_type_gap",
        ):
            if spec.get(field):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": field,
                        "detail": spec[field],
                    }
                )
    return gaps


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def _dates(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def _months(start, end):
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def _recent(api, start, today, stocks, epoch):
    recent = max(start or date.min, today - timedelta(days=6))
    if api == "fina_audit":
        for code in stocks:
            yield _job(
                api,
                {
                    "ts_code": code,
                    "start_date": recent.strftime("%Y%m%d"),
                    "end_date": today.strftime("%Y%m%d"),
                },
                epoch,
                20,
            )
    elif api == "fina_mainbz":
        anchor = today - timedelta(days=today.weekday() + 1)
        left = max(start or date.min, date(anchor.year - 1, 1, 1))
        if left <= anchor:
            for code in stocks:
                for kind in ("P", "D", "I"):
                    yield _job(
                        api,
                        {
                            "ts_code": code,
                            "type": kind,
                            "start_date": left.strftime("%Y%m%d"),
                            "end_date": anchor.strftime("%Y%m%d"),
                        },
                        "week-" + anchor.strftime("%Y%m%d"),
                        20,
                    )
    elif api == "broker_recommend":
        previous = today.replace(day=1) - timedelta(days=1)
        for month in (today.replace(day=1), previous.replace(day=1)):
            if start is None or month >= start.replace(day=1):
                yield _job(api, {"month": month.strftime("%Y%m")}, epoch, 20)
    else:
        if api == "disclosure_date":
            yield _job(api, {}, epoch, 20)  # Include already announced future plans.
        for day in _dates(recent, today):
            day = day.strftime("%Y%m%d")
            param = {
                "report_rc": "report_date",
                "stk_surv": "trade_date",
                "disclosure_date": "ann_date",
            }[api]
            yield _job(api, {param: day}, epoch, 20)


def _history(api, start, today, stocks):
    if api == "fina_audit" or (api == "fina_mainbz" and start is None):
        for code in stocks:
            for kind in ("P", "D", "I") if api == "fina_mainbz" else (None,):
                yield _job(
                    api,
                    {"ts_code": code, **({"type": kind} if kind else {})},
                    "history",
                    40,
                )
        return
    if start is None:
        return
    if api == "fina_mainbz":
        anchor = today - timedelta(days=today.weekday() + 1)
        for year in range(start.year, anchor.year - 1):
            left = max(start, date(year, 1, 1))
            for code in stocks:
                for kind in ("P", "D", "I"):
                    yield _job(
                        api,
                        {
                            "ts_code": code,
                            "type": kind,
                            "start_date": left.strftime("%Y%m%d"),
                            "end_date": f"{year:04d}1231",
                        },
                        "history",
                        40,
                    )
    elif api == "disclosure_date":
        for month in _months(start, today):
            if month.month in (3, 6, 9, 12):
                period = month.replace(day=monthrange(month.year, month.month)[1])
                if start <= period <= today:
                    yield _job(
                        api, {"end_date": period.strftime("%Y%m%d")}, "history", 40
                    )
    elif api == "broker_recommend":
        previous = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for month in _months(start, previous - timedelta(days=1)):
            yield _job(api, {"month": month.strftime("%Y%m")}, "history", 40)
    else:
        param = "report_date" if api == "report_rc" else "trade_date"
        for day in _dates(start, today - timedelta(days=7)):
            yield _job(api, {param: day.strftime("%Y%m%d")}, "history", 40)


def iter_research_extra_jobs(config, today, identifiers=None):
    """All recent streams precede lazy complete scoped history; never call I/O.

    Required stock discovery includes retired and renamed supplier codes without
    filtering. History anchors/cursors and cap-triggered date/code splitting are
    owned by the parent. Empty results never establish prehistory completeness.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    stocks = _stocks(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for maker in (_recent, _history):
        streams = [
            maker(api, starts[api], today, stocks, epoch)
            if maker is _recent
            else maker(api, starts[api], today, stocks)
            for api in enabled
        ]
        for batch in zip_longest(*streams):
            yield from (job for job in batch if job is not None)
