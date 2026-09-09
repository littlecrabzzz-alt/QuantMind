"""Pure stopped account-statistics contracts; no runtime registration or calls.

Only explicit configured history is planned. The two source series have different
units and definitions and must remain separate. A parsed old period is an output
projection, never proof of which period endpoint a range request filters.
"""

from datetime import date, datetime
import re

from backend.shared.tushare_market_contracts import _months
from backend.shared.tushare_structured_contracts import _contract, _parse

SOURCE_HTML_SHA256 = {
    "stk_account": "158c2a71d6eba4df9aff9abaccf9defc74355bf15976811fe11b0049be444e56",
    "stk_account_old": "edb40049e18b303b3dcb6bee3c4c0248fcd5e97bd8f105ce56ec0c6ce0fcf617",
}
INPUT_METADATA = {
    "stk_account": {
        "date": {"type": "str", "required": "N", "description": "日期"},
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "stk_account_old": {
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
}
FIELD_METADATA = {
    "stk_account": {
        "date": {"type": "str", "default": "Y", "description": "统计周期"},
        "weekly_new": {
            "type": "float",
            "default": "Y",
            "description": "本周新增（万）",
        },
        "total": {"type": "float", "default": "Y", "description": "期末总账户数（万）"},
        "weekly_hold": {
            "type": "float",
            "default": "Y",
            "description": "本周持仓账户数（万）",
        },
        "weekly_trade": {
            "type": "float",
            "default": "Y",
            "description": "本周参与交易账户数（万）",
        },
    },
    "stk_account_old": {
        "date": {"type": "str", "default": "Y", "description": "统计周期"},
        "new_sh": {
            "type": "int",
            "default": "Y",
            "description": "本周新增（上海，户）",
        },
        "new_sz": {
            "type": "int",
            "default": "Y",
            "description": "本周新增（深圳，户）",
        },
        "active_sh": {
            "type": "float",
            "default": "Y",
            "description": "期末有效账户（上海，万户）",
        },
        "active_sz": {
            "type": "float",
            "default": "Y",
            "description": "期末有效账户（深圳，万户）",
        },
        "total_sh": {
            "type": "float",
            "default": "Y",
            "description": "期末账户数（上海，万户）",
        },
        "total_sz": {
            "type": "float",
            "default": "Y",
            "description": "期末账户数（深圳，万户）",
        },
        "trade_sh": {
            "type": "float",
            "default": "Y",
            "description": "参与交易账户数（上海，万户）",
        },
        "trade_sz": {
            "type": "float",
            "default": "Y",
            "description": "参与交易账户数（深圳，万户）",
        },
    },
}
FIELDS = {api: list(meta) for api, meta in FIELD_METADATA.items()}
INPUT_FIELDS = {api: list(meta) for api, meta in INPUT_METADATA.items()}

ACCOUNT_HISTORY_CONTRACTS = {}
for _api, _doc in (("stk_account", 164), ("stk_account_old", 165)):
    _spec = _contract(
        1000,
        ("date",),
        required=FIELDS[_api],
        nullable=FIELDS[_api][1:],
        extra=FIELDS[_api],
        rpm=30,
        cap_verified=False,
    )
    _spec.update(
        group="account_history",
        default_enabled=False,
        doc_id=_doc,
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        fields=list(FIELDS[_api]),
        requested_fields=list(FIELDS[_api]),
        input_metadata=INPUT_METADATA[_api],
        field_metadata=FIELD_METADATA[_api],
        allowed_params=list(INPUT_FIELDS[_api]),
        required_params=[],
        hidden_fields=[],
        dependencies=[],
        request_identity_fields=[],
        preserve_distinct_rows=True,
        date_field="date" if _api == "stk_account" else None,
        split_axis="date" if _api == "stk_account" else None,
        permission_status="unprobed",
        minimum_points=600,
        independent_permission=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        documented_row_cap=None,
        pagination=None,
        history_bound_verified=False,
        stopped_updates=True,
        permission_gap="600 points is documented eligibility, not measured entitlement. RPM/daily quota are unpublished; local30rpm is only a conservative operational ceiling.",
        saturation_gap="1000 is an unverified local guard, not the provider cap. Legal ranges may bisect but completeness below guard is unproved; single-period saturation has no documented further dimension, limit or offset.",
        boundary_gap="New-series documentation points to old structure before20150508; old-series documentation ends20150529. Do not join, deduplicate across APIs or invent a seamless cutoff.",
        pit_gap="Weekly statistical period is not a publication/as-of timestamp. Revision history and publication lag are unknown; fetched_at only records this observation.",
        unknown_field_gap="Explicitly request all known fields; preserve additional returned columns and null values. Unknown output fields or date patterns require a retained source observation and an explicit validation gap.",
    )
    ACCOUNT_HISTORY_CONTRACTS[_api] = _spec

ACCOUNT_HISTORY_CONTRACTS["stk_account"].update(
    exact_date_param="date",
    history_gap="Provider stopped updates but publishes no verified first/last available date. Explicit configured scope is not all history; sample2018 is not a bound.",
    date_gap="Output date is a weekly statistics label, not a daily trading observation. Do not infer week start, Friday, exchange calendar or request-filter boundary semantics.",
    unit_note="All four numerical columns are in ten-thousands; preserve null rather than zero. weekly_hold/weekly_trade publication stopped from20170210; nulls are expected thereafter.",
)
ACCOUNT_HISTORY_CONTRACTS["stk_account_old"].update(
    exact_date_param=None,
    source_period_field="date",
    documented_history_start_month="200801",
    documented_history_end="20150529",
    history_gap="Official coverage is month-granularity200801 through20150529; first actual row and missing weeks are unverified. Planner requires explicit scope and only clips its upper bound to20150529.",
    date_gap="Raw date is YYYYMMDD~MMDD. Official2014 range ending20141231 returns20141229~0102: output period may end outside request. Filter start/end/intersection semantics remain unknown; never replace source date with projected end.",
    projection_gap="Only valid YYYYMMDD~MMDD periods within seven calendar days are projected; Dec-to-Jan may roll one year. This deliberately narrow recognized shape is not the complete source grammar. Unknown/null/impossible/longer patterns must retain raw data and record period_projection_unverified.",
    unit_note="new_sh/new_sz are accounts (户); remaining six numerical columns are ten-thousand accounts (万户). Do not coerce to the new series or sum exchange counts as unique persons.",
)


def project_account_period(value):
    """Return derived start/end YYYYMMDD; leave the caller's raw value untouched.

    ValueError means unverified projection, not permission to discard the row.
    No trading-calendar or fixed weekday assumption is made.
    """
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}~[0-9]{4}", value):
        raise ValueError("period_projection_unverified: expected YYYYMMDD~MMDD")
    try:
        start = _parse(value[:8])
    except ValueError as exc:
        raise ValueError("period_projection_unverified: invalid start date") from exc
    month, day = int(value[9:11]), int(value[11:13])
    year = start.year + (start.month == 12 and month == 1)
    try:
        end = date(year, month, day)
    except ValueError as exc:
        raise ValueError("period_projection_unverified: invalid end date") from exc
    if not 0 <= (end - start).days <= 6:
        raise ValueError("period_projection_unverified: outside recognized weekly span")
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _scope(config):
    enabled = config.get("account_history_apis", tuple(ACCOUNT_HISTORY_CONTRACTS))
    if not isinstance(enabled, (list, tuple)) or any(
        not isinstance(api, str) or api not in ACCOUNT_HISTORY_CONTRACTS
        for api in enabled
    ):
        raise ValueError("account_history_apis must list known APIs")
    setting = config.get("account_history_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "account_history_history_start must be YYYYMMDD or API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - ACCOUNT_HISTORY_CONTRACTS.keys():
        raise ValueError("Unknown account history API")
    starts = {}
    for api in dict.fromkeys(enabled):
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        starts[api] = _parse(value) if value is not None else None
    return starts


def account_history_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["account_history_apis"] = enabled_apis
    gaps = []
    for api, start in _scope(config).items():
        gaps.extend(
            {"api_name": api, "dependencies": [], "reason": key, "detail": value}
            for key, value in ACCOUNT_HISTORY_CONTRACTS[api].items()
            if key.endswith("_gap")
        )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "configured_scope_not_verified_complete"
                if start
                else "unknown_history_start_requires_scope",
            }
        )
    return gaps


def iter_account_history_jobs(config, today, identifiers=None):
    """Lazy, round-robin monthly history; stopped series have no recent polling.

    Runtime integration must remain disabled until separately authorized. Missing
    scope produces gaps, not an invented first date. Anchored caller today is the
    request bound for the new series whose last available date is unpublished.
    """
    if not config.get("enable_account_history", False):
        return
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    starts = _scope(config)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    streams = {
        api: iter(
            _months(
                start,
                min(today, date(2015, 5, 29)) if api == "stk_account_old" else today,
            )
        )
        for api, start in starts.items()
        if start is not None
    }
    while streams:
        for api in tuple(streams):
            window = next(streams[api], None)
            if window is None:
                del streams[api]
                continue
            yield {
                "api_name": api,
                "params": {
                    "start_date": window[0].strftime("%Y%m%d"),
                    "end_date": window[1].strftime("%Y%m%d"),
                },
                "fields": ",".join(FIELDS[api]),
                "epoch": "history",
                "priority": 55,
            }
