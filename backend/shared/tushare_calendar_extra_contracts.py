"""Pure reviewed calendar/announcement or factor-library acquisition contracts."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_market_contracts import _months
from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_technical_extra_contracts import _days

SOURCE_HTML_SHA256 = {
    "eco_cal": "67e141e4439009435769a8f2c783967b36b896c860806b557923b56b35d73fab",
    "cn_schedule": "a3f72721345c07aa72480ea6beaab247b9a772ebe34697702f8020035090fc62",
    "idx_anns": "cb22ad7a7531c5eb65a4773d28f018d726337ac29e76cbb4ff26c42acf857bee",
}

INPUT_METADATA = {
    "eco_cal": {
        "date": {"type": "str", "required": "N", "description": "日期（YYYYMMDD格式）"},
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
        "currency": {"type": "str", "required": "N", "description": "货币代码"},
        "country": {
            "type": "str",
            "required": "N",
            "description": "国家（比如：中国、美国）",
        },
        "event": {
            "type": "str",
            "required": "N",
            "description": "事件 （支持模糊匹配： *非农*）",
        },
    },
    "cn_schedule": {
        "m": {"type": "str", "required": "N", "description": "月份（YYYYMM）"},
        "title": {"type": "str", "required": "N", "description": "发布数据"},
    },
    "idx_anns": {
        "ann_date": {
            "type": "str",
            "required": "N",
            "description": "公告日期（YYYYMMDD格式，下同）",
        },
        "start_date": {"type": "str", "required": "N", "description": "公告开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "公告结束日期"},
        "src": {
            "type": "str",
            "required": "N",
            "description": "信息来源（中证指数、国证指数、恒生指数、华证指数）",
        },
    },
}

FIELD_METADATA = {
    "eco_cal": {
        "date": {"type": "str", "default": "Y", "description": "日期"},
        "time": {"type": "str", "default": "Y", "description": "时间"},
        "currency": {"type": "str", "default": "Y", "description": "货币代码"},
        "country": {"type": "str", "default": "Y", "description": "国家"},
        "event": {"type": "str", "default": "Y", "description": "经济事件"},
        "value": {"type": "str", "default": "Y", "description": "今值"},
        "pre_value": {"type": "str", "default": "Y", "description": "前值"},
        "fore_value": {"type": "str", "default": "Y", "description": "预测值"},
    },
    "cn_schedule": {
        "month": {"type": "str", "default": "Y", "description": "月份YYYYMM"},
        "publish_date": {"type": "str", "default": "Y", "description": "发布日期"},
        "title": {"type": "str", "default": "Y", "description": "发布数据"},
        "issuing_org": {"type": "str", "default": "Y", "description": "发布单位"},
        "data_api": {"type": "str", "default": "Y", "description": "tushare对应接口"},
    },
    "idx_anns": {
        "ann_date": {"type": "str", "default": "Y", "description": "公告日期"},
        "title": {"type": "str", "default": "Y", "description": "标题"},
        "url": {"type": "str", "default": "Y", "description": "链接"},
        "source": {"type": "str", "default": "Y", "description": "来源"},
        "type": {
            "type": "str",
            "default": "Y",
            "description": "类型(指数发布、指数修订、指数更名、其他）",
        },
    },
}

INPUT_FIELDS = {api: list(metadata) for api, metadata in INPUT_METADATA.items()}

FIELDS = {api: list(metadata) for api, metadata in FIELD_METADATA.items()}

CALENDAR_EXTRA_CONTRACTS = {}
for _api, _doc, _cap, _points, _axis, _keys in (
    (
        "eco_cal",
        233,
        100,
        2000,
        "date",
        ("date", "time", "currency", "country", "event"),
    ),
    (
        "cn_schedule",
        461,
        3000,
        2000,
        "publish_date",
        ("month", "publish_date", "title", "issuing_org", "data_api"),
    ),
    (
        "idx_anns",
        460,
        1000,
        6000,
        "ann_date",
        ("ann_date", "source", "title", "url", "type"),
    ),
):
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[
            f
            for f in FIELDS[_api]
            if f != ("month" if _api == "cn_schedule" else _axis)
        ],
        extra=FIELDS[_api],
        split=_api != "cn_schedule",
        rpm=30,
    )
    spec.update(
        doc_id=_doc,
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        fields=list(FIELDS[_api]),
        requested_fields=list(FIELDS[_api]),
        input_metadata=INPUT_METADATA[_api],
        field_metadata=FIELD_METADATA[_api],
        hidden_fields=[],
        allowed_params=list(INPUT_METADATA[_api]),
        required_params=[],
        request_identity_fields=[],
        preserve_distinct_rows=True,
        date_field=_axis,
        split_axis=_axis,
        dependencies=[],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        history_bound_verified=False,
        permission_gap="Points describe eligibility only; account entitlement, frequency and daily quota remain unprobed. Local30rpm is an operational ceiling.",
        history_gap="No earliest date is documented. Explicit configured dates are requested scope, not a verified beginning; example dates are not lower bounds.",
        pagination_gap="No limit/offset/page parameter is documented. Never fabricate pagination or treat an at-cap result as complete.",
        identity_gap="No immutable source row ID. Preserve distinct full rows and original nulls; exact duplicate multiplicity, deletions and revisions remain unverified.",
        pit_gap="Calendar schedule, economic actual release, index announcement and collection time are different axes. Backfilled/revised records do not establish historical availability.",
        refresh_gap="Recent overlaps and future lookahead are finite. Older revisions, removed announcements and farther future schedules need follow-up coverage audit.",
        field_selection_note="Request all known fields explicitly; retain unexpected returned fields and nulls. All currently documented columns defaultY.",
        field_gaps={
            f: ["actual_presence_unprobed", "revision_availability_unverified"]
            for f in FIELDS[_api]
        },
    )
    CALENDAR_EXTRA_CONTRACTS[_api] = spec
CALENDAR_EXTRA_CONTRACTS["eco_cal"].update(
    exact_date_param="date",
    date_note="date YYYYMMDD and time are separate; timezone is unspecified. Request includes weekends and a bounded7-day future window, not a stock trading calendar.",
    unit_note="value/pre_value/fore_value are source strings, possibly percent, K/B/T, blanks or revised previous values; do not coerce to a common numeric unit.",
    saturation_gap="Date ranges can bisect to one day, but100 global events may still saturate. country/currency/event are legal filters; their full historical universe and second-dimension fanout are unknown. time is output-only.",
)
CALENDAR_EXTRA_CONTRACTS["cn_schedule"].update(
    exact_date_param=None,
    date_note="Only m YYYYMM and title are legal inputs. month is scheduled month; publish_date is planned publication, not a verified actual timestamp. Full containing month may precede a mid-month configured scope.",
    input_scope_gap="No daily/range/stock filters. Recent requests cover previous/current/next month; farther future and historical schedule revisions remain unknown.",
    data_api_gap="data_api is an opaque returned label and can be 待上线. It must not trigger dynamic API calls, code execution or automatic permission promotion.",
    saturation_gap="A month reaching3000 has only optional title filtering; full historical title universe is unknown. No date bisection or invented page cursor is legal.",
)
CALENDAR_EXTRA_CONTRACTS["idx_anns"].update(
    exact_date_param="ann_date",
    documented_sources=["中证指数", "国证指数", "恒生指数", "华证指数"],
    date_note="ann_date filters announcement date, not constituent effective date. source corresponds to optional input src; type is output-only and examples exceed the descriptive enum, so retain unknown labels.",
    attachment_fields=["url"],
    attachment_gap="This pure candidate only requests metadata links. Linked announcement bodies, SPA URLs and nested attachments require safe verified archival integration; their original contents are not yet acquired.",
    saturation_gap="Initial unfiltered all-source dates preserve newly appearing sources. Legal src can narrow a saturated date, but source-universe completeness is unverified; source/day cap has no title/type/page filter.",
)

# Runtime-only saturation discovery is intentionally outside the planner contract.
# Adding observed countries must not change/reset the parent calendar cursor.
ECO_CAL_OBSERVED_FANOUT = {
    "family": "eco_cal_countries",
    "param": "country",
    "jobs_per_run": 100,
}


def _enabled(config):
    selected = config.get("calendar_extra_apis", tuple(CALENDAR_EXTRA_CONTRACTS))
    if not isinstance(selected, (tuple, list)) or any(
        not isinstance(a, str) or a not in CALENDAR_EXTRA_CONTRACTS for a in selected
    ):
        raise ValueError("calendar_extra_apis must list known APIs")
    return tuple(dict.fromkeys(selected))


def _starts(config, enabled):
    setting = config.get("calendar_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("calendar_extra_history_start must be YYYYMMDD or API mapping")
    if isinstance(setting, dict) and setting.keys() - CALENDAR_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown calendar history API")
    values = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        values[api] = _parse(value) if value is not None else None
    return values


def calendar_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["calendar_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        gaps.extend(
            {"api_name": api, "dependencies": [], "reason": k, "detail": v}
            for k, v in CALENDAR_EXTRA_CONTRACTS[api].items()
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
    return gaps


def _partitions(api, begin, end):
    if api == "cn_schedule":
        for first, _ in _months(begin, end):
            yield {"m": first.strftime("%Y%m")}
    else:
        axis = CALENDAR_EXTRA_CONTRACTS[api]["exact_date_param"]
        for params in _days(begin, end):
            yield {axis: params["trade_date"]}


def iter_calendar_extra_jobs(config, today, identifiers=None):
    """Lazy all-source exact dates and legal months, recent before explicit history."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(v and v > today for v in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    previous_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            boundary = previous_month if api == "cn_schedule" else recent
            end = (
                next_month
                if api == "cn_schedule"
                else today + timedelta(days=7)
                if api == "eco_cal"
                else today
            )
            start = starts[api]
            if history:
                if start and start < boundary:
                    streams[api] = iter(
                        _partitions(api, start, boundary - timedelta(days=1))
                    )
            else:
                streams[api] = iter(
                    _partitions(api, max(start or boundary, boundary), end)
                )
        while streams:
            for api in tuple(streams):
                params = next(streams[api], None)
                if params is None:
                    del streams[api]
                else:
                    yield {
                        "api_name": api,
                        "params": params,
                        "fields": ",".join(FIELDS[api]),
                        "epoch": "history" if history else epoch,
                        "priority": 55 if history else 20,
                    }
