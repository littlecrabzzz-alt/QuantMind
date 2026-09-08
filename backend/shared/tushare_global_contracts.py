"""Pure supplier-boundary plans for HK/US and stock/index period data.

Contracts describe documented behavior, not verified account permissions.
No credentials, network, database, date truncation, or symbol normalization.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
from itertools import zip_longest
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

# All documented output fields, including default-hidden fields. Caller sends
# these as the API request's top-level fields selector and retains unknown raw fields.
FIELDS = {
    "hk_basic": [
        "ts_code",
        "name",
        "fullname",
        "enname",
        "cn_spell",
        "market",
        "list_status",
        "list_date",
        "delist_date",
        "trade_unit",
        "isin",
        "curr_type",
    ],
    "us_basic": ["ts_code", "name", "enname", "classify", "list_date", "delist_date"],
    "hk_tradecal": ["cal_date", "is_open", "pretrade_date"],
    "us_tradecal": ["cal_date", "is_open", "pretrade_date"],
    "weekly": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "monthly": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "stk_weekly_monthly": [
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "change",
        "pct_chg",
    ],
    "stk_week_month_adj": [
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "open_qfq",
        "high_qfq",
        "low_qfq",
        "close_qfq",
        "open_hfq",
        "high_hfq",
        "low_hfq",
        "close_hfq",
        "vol",
        "amount",
        "change",
        "pct_chg",
    ],
    "index_weekly": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "index_monthly": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "index_dailybasic": [
        "ts_code",
        "trade_date",
        "total_mv",
        "float_mv",
        "total_share",
        "float_share",
        "free_share",
        "turnover_rate",
        "turnover_rate_f",
        "pe",
        "pe_ttm",
        "pb",
    ],
    "hk_daily": [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "hk_daily_adj": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_change",
        "vol",
        "amount",
        "vwap",
        "adj_factor",
        "turnover_ratio",
        "free_share",
        "total_share",
        "free_mv",
        "total_mv",
    ],
    "hk_adjfactor": ["ts_code", "trade_date", "cum_adjfactor", "close_price"],
    "us_daily": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_change",
        "vol",
        "amount",
        "vwap",
        "turnover_ratio",
        "total_mv",
        "pe",
        "pb",
    ],
    "us_daily_adj": [
        "ts_code",
        "trade_date",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_change",
        "vol",
        "amount",
        "vwap",
        "adj_factor",
        "turnover_ratio",
        "free_share",
        "total_share",
        "free_mv",
        "total_mv",
        "exchange",
    ],
    "us_adjfactor": [
        "ts_code",
        "trade_date",
        "exchange",
        "cum_adjfactor",
        "close_price",
    ],
}

# API: (official doc id, cap, permission points; None means independent entitlement)
_DOCS = {
    "hk_basic": (191, 6000, 2000),
    "us_basic": (252, 6000, 5000),
    "hk_tradecal": (250, 2000, 2000),
    "us_tradecal": (253, 6000, 5000),
    "weekly": (144, 6000, 2000),
    "monthly": (145, 4500, 2000),
    "stk_weekly_monthly": (336, 6000, 2000),
    "stk_week_month_adj": (365, 6000, 2000),
    "index_weekly": (171, 1000, 600),
    "index_monthly": (172, 1000, 600),
    "index_dailybasic": (128, 3000, 2000),
    "hk_daily": (192, 5000, None),
    "hk_daily_adj": (339, 6000, None),
    "hk_adjfactor": (401, 6000, None),
    "us_daily": (254, 6000, None),
    "us_daily_adj": (338, 8000, None),
    "us_adjfactor": (402, 15000, None),
}
BASICS = ("hk_basic", "us_basic")
CALENDARS = ("hk_tradecal", "us_tradecal")
PERIOD_DAILY = ("stk_weekly_monthly", "stk_week_month_adj")
SYMBOL_PERIODS = {
    "weekly": "stocks",
    "monthly": "stocks",
    "index_weekly": "indexes",
    "index_monthly": "indexes",
}
GLOBAL_CONTRACTS = {}
for _api, (_doc, _cap, _points) in _DOCS.items():
    _keys = ("ts_code", "trade_date")
    if _api in BASICS:
        _keys = ("ts_code",)
    elif _api in CALENDARS:
        _keys = ("cal_date",)
    elif _api in PERIOD_DAILY:
        _keys += ("freq", "end_date")
    elif _api in ("us_daily_adj", "us_adjfactor"):
        _keys += ("exchange",)
    _required = tuple(k for k in _keys if k not in ("end_date", "exchange"))
    _spec = _contract(
        _cap,
        _keys,
        required=_required,
        nullable=tuple(f for f in FIELDS[_api] if f not in _required),
        split=_api not in BASICS,
        rpm=50,
        extra=FIELDS[_api],
        start="20040101" if _api == "index_dailybasic" else None,
        cap_verified=_api != "hk_basic",
    )
    _spec.update(
        {
            "source_url": f"https://tushare.pro/document/2?doc_id={_doc}",
            "permission_status": "unprobed",
            "minimum_points": _points,
            "independent_permission": _points is None,
            "documented_requests_per_minute": None,
            "history_bound_verified": _api == "index_dailybasic",
            "history_gap": None
            if _api in BASICS or _api == "index_dailybasic"
            else "official_earliest_date_unspecified",
            "dependencies": [],
            "split_axis": "cal_date" if _api in CALENDARS else "trade_date",
        }
    )
    if _api not in BASICS + CALENDARS:
        _family = (
            "hk_stocks"
            if _api.startswith("hk_")
            else "us_stocks"
            if _api.startswith("us_")
            else "indexes"
            if _api.startswith("index_")
            else "stocks"
        )
        _spec.update(
            saturation_fallback=_family,
            saturation_param="ts_code",
            saturation_dependencies=[_family],
        )
    GLOBAL_CONTRACTS[_api] = _spec

# A production observation disproved the old documentation's 4500 limit.
# 5629 is a measured lower bound ONLY: reaching it must still trigger cap handling.
GLOBAL_CONTRACTS["monthly"].update(
    row_cap=5629,
    row_cap_verified=False,
    documented_row_cap=4500,
    observed_row_cap_lower_bound=5629,
    cap_note="Observed 5629 rows in validation/global-vip-probe.json; actual cap unknown. Reaching 5629 remains a saturation alarm.",
)
for _api, _family in SYMBOL_PERIODS.items():
    GLOBAL_CONTRACTS[_api].update(
        dependencies=[_family],
        planning_version="stable_decade_partitions_v4",
        planning_note="Fixed closed ten-year buckets, then one prior-year tail, one prior-month tail and at most one older completed-week tail; only tails change at their calendar boundary. Recent two completed periods share a period-end epoch. Daily planning_epoch does not force period refresh. Discovery and earliest history remain unverified.",
        period_wait_note="Open calendar weeks/months wait for their full boundary; daily-updated stk_* contracts remain independent. Late corrections outside the recent two periods require an explicit revision sweep.",
    )
GLOBAL_CONTRACTS["hk_basic"]["identifier_note"] = (
    "Supplier codes may contain opaque ! or !AE suffixes; preserve each identity without inferring suffix meaning."
)

for _api in ("us_daily", "us_daily_adj"):
    GLOBAL_CONTRACTS[_api]["documented_requests_per_minute"] = 500

GLOBAL_CONTRACTS["hk_basic"]["cap_note"] = (
    "Docs promise all actively traded securities, without a numerical cap; "
    "6000 is a conservative saturation alarm, not verified completeness."
)
for _api in ("us_basic", "us_daily_adj"):
    GLOBAL_CONTRACTS[_api]["pagination"] = {
        "offset_param": "offset",
        "limit_param": "limit",
        "page_size": _DOCS[_api][1],
    }
GLOBAL_CONTRACTS["us_basic"]["parameter_note"] = (
    "Input table spells list_stauts; preserve this supplier spelling pending live verification. "
    "Table classification EQ conflicts with sample EQT; unfiltered pagination is mandatory. "
    "Offset example says 1 is first row; first request omits offset, cursor origin needs verification."
)
for _api in ("hk_daily_adj", "us_daily"):
    GLOBAL_CONTRACTS[_api]["pagination_gap"] = (
        "Description advertises pagination but input table omits cursor parameters; "
        "use documented date/code splitting until validated."
    )
for _api in (
    "hk_daily_adj",
    "us_daily_adj",
    "hk_adjfactor",
    "us_adjfactor",
    "stk_week_month_adj",
):
    GLOBAL_CONTRACTS[_api]["revision_note"] = (
        "Historic adjustment values can change. Preserve observations; recent-only refresh "
        "does not validate older factors. Requires separate periodic full-history revision sweep."
    )
GLOBAL_CONTRACTS["hk_daily"]["quality_note"] = (
    "Vendor permits high below open/close or low above open/close; do not reject on OHLC ordering."
)
GLOBAL_CONTRACTS["us_adjfactor"]["scope_note"] = (
    "Official example is exactly 15000 rows and includes ARC. Never infer completeness "
    "from one day or restrict to NAS/NYS/OTC; split by complete stored us_stocks discovery."
)
GLOBAL_CONTRACTS["us_daily_adj"]["parameter_note"] = (
    "Use exchange from input table; example exhange is a typo. Plan unfiltered all exchanges."
)
GLOBAL_CONTRACTS["index_dailybasic"]["scope_note"] = (
    "Description lists six indices but example has additional codes; request all by trade_date. "
    "This API is not a promise of indicators for every index."
)
for _api in PERIOD_DAILY:
    GLOBAL_CONTRACTS[_api]["period_note"] = (
        "trade_date is a week/month label and may be later than current date; end_date "
        "is calculation cutoff. Keep both, both frequencies, and observation revisions."
    )


def _enabled(config):
    values = config.get("global_apis", tuple(GLOBAL_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        v not in GLOBAL_CONTRACTS for v in values
    ):
        raise ValueError("global_apis must list known GLOBAL_CONTRACTS APIs")
    return tuple(dict.fromkeys(values))


def _identifiers(identifiers):
    """Validate raw supplier codes without stripping statuses or inventing suffixes.

    US tickers have no required market suffix and may contain vendor punctuation.
    These values are only outbound supplier identifiers, never internal stock codes.
    """
    result = {}
    for family in ("stocks", "indexes", "hk_stocks", "us_stocks"):
        values = identifiers.get(family, ())
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"{family} must be a list of codes or discovery records")
        codes = set()
        for row in values:
            code = (
                row.get("ts_code") or row.get("index_code")
                if isinstance(row, dict)
                else row
            )
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 64
                or any(
                    char.isspace() or char in ",\\\"'" or ord(char) < 32
                    for char in code
                )
            ):
                raise ValueError(f"Invalid supplier identifier in {family}")
            if family == "hk_stocks" and not re.fullmatch(
                r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", code
            ):
                raise ValueError(
                    "HK supplier identifiers require five digits, optional ! plus up to eight uppercase letters, and .HK"
                )
            if family in ("stocks", "indexes") and not re.fullmatch(
                r"[A-Za-z0-9]+\.[A-Z]+", code
            ):
                raise ValueError(f"Invalid supplier identifier in {family}")
            codes.add(code)
        result[family] = sorted(codes)
    return result


def _starts(config, enabled):
    setting = config.get("global_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("global_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and set(setting) - GLOBAL_CONTRACTS.keys():
        raise ValueError("Unknown API in global_history_start")
    result = {}
    for api in enabled:
        explicit = setting.get(api) if isinstance(setting, dict) else setting
        if explicit is None:
            explicit = config.get("history_start")
        known = GLOBAL_CONTRACTS[api]["history_start"]
        # An explicitly chosen range is a scope, not evidence of supplier completeness.
        result[api] = _parse(explicit or known) if explicit or known else None
    return result


def global_prerequisites(identifiers=None, enabled_apis=None, config=None):
    """Report discovery/history gaps; symbol-period requests need stored codes.

    Complete discovery must be verified by the caller, not inferred from nonempty lists.
    """
    config = dict(config or {})
    if enabled_apis is not None:
        config["global_apis"] = enabled_apis
    enabled = _enabled(config)
    ids = _identifiers(identifiers or {})
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        family = GLOBAL_CONTRACTS[api].get("saturation_fallback")
        if family and not ids[family]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [family],
                    "reason": "awaiting_stored_discovery_for_symbol_ranges"
                    if api in SYMBOL_PERIODS
                    else "awaiting_complete_stored_discovery_for_saturation",
                }
            )
        if api not in BASICS and starts[api] is None:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_explicit_scope_or_evidence",
                }
            )
    return gaps


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def _day_jobs(api, day, epoch, priority):
    if api in CALENDARS:
        params = {
            "start_date": day.strftime("%Y%m%d"),
            "end_date": day.strftime("%Y%m%d"),
        }
        yield _job(api, params, epoch, priority)
    else:
        for freq in ("week", "month") if api in PERIOD_DAILY else (None,):
            params = {"trade_date": day.strftime("%Y%m%d")}
            if freq:
                params["freq"] = freq
            if api == "us_daily_adj":
                params["limit"] = 8000
            yield _job(api, params, epoch, priority)


def _interleave(streams):
    for batch in zip_longest(*streams):
        for job in batch:
            if job is not None:
                yield job


def _completed_period_bounds(api, today):
    """Two fully ended calendar periods; no assumptions about their trading days."""
    if api.endswith("weekly"):
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=13), end
    end = today.replace(day=1) - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)
    return start, end


def _period_jobs(api, start, end, ids, epoch, priority):
    if start > end:
        return
    for code in ids[SYMBOL_PERIODS[api]]:
        yield _job(
            api,
            {
                "ts_code": code,
                "start_date": start.strftime("%Y%m%d"),
                "end_date": end.strftime("%Y%m%d"),
            },
            epoch,
            priority,
        )


def _period_history_jobs(api, start, today, ids):
    recent_start, closed = _completed_period_bounds(api, today)
    left = start
    # At most ten calendar years per code: <= 523 weekly / 120 monthly
    # period rows, below the conservative index guard of 1000. Unexpected
    # supplier saturation still goes through the parent's normal split path.
    decade_end = date((left.year // 10 + 1) * 10 - 1, 12, 31)
    while decade_end <= closed:
        yield from _period_jobs(api, left, decade_end, ids, "history", 40)
        left = decade_end + timedelta(days=1)
        decade_end = date(decade_end.year + 10, 12, 31)
    # Only the unclosed decade's tail changes yearly; complete decades keep
    # identical request keys. The remaining current-year tail changes monthly.
    year_end = date(closed.year - (closed.month != 12 or closed.day != 31), 12, 31)
    month_end = (
        closed
        if closed.day == monthrange(closed.year, closed.month)[1]
        else closed.replace(day=1) - timedelta(days=1)
    )
    for right in (year_end, month_end, recent_start - timedelta(days=1)):
        if left <= right:
            yield from _period_jobs(api, left, right, ids, "history", 40)
            left = right + timedelta(days=1)


def _date_jobs(api, start, end, epoch, priority):
    day = start
    while day <= end:
        yield from _day_jobs(api, day, epoch, priority)
        day += timedelta(days=1)
    if epoch != "history" and api in PERIOD_DAILY:
        friday = end + timedelta(days=4 - end.weekday())
        month_end = end.replace(day=monthrange(end.year, end.month)[1])
        for freq, label in (("week", friday), ("month", month_end)):
            if label > end:
                yield _job(
                    api,
                    {"trade_date": label.strftime("%Y%m%d"), "freq": freq},
                    epoch,
                    priority,
                )


def iter_global_jobs(config, today, identifiers=None):
    """Generate recent-first jobs without I/O or hidden history/universe cutoffs.

    Four completed-period APIs require stored stocks/indexes. Recent work covers
    the last two closed calendar periods, with a stable period-end epoch. History
    uses fixed closed decades followed by bounded year/month/week tails. Tails
    change only at their matching calendar boundary and may overlap recent work;
    no observations are discarded.
    Open periods wait for completion. Other APIs retain their daily plans.
    Missing discovery/history is explicit in global_prerequisites/metadata.
    Parent owns persistence, pagination, shared limits and old-plan deferral.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    ids = _identifiers(identifiers or {})
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    recent = today - timedelta(days=6)
    for api in enabled:
        if api == "hk_basic":
            for status in ("L", "D", "P"):
                yield _job(api, {"list_status": status}, epoch, 20)
        elif api == "us_basic":
            # Unfiltered classify retains EQT and categories absent from the table.
            for status in (None, "L", "D", "P"):
                params = {"limit": 6000}
                if status:
                    params["list_stauts"] = status
                yield _job(api, params, epoch, 20)
    streams = []
    for api in enabled:
        if api in BASICS:
            continue
        if api in SYMBOL_PERIODS:
            period_start, closed = _completed_period_bounds(api, today)
            start = max(period_start, starts[api] or period_start)
            streams.append(
                _period_jobs(
                    api, start, closed, ids, "period-" + closed.strftime("%Y%m%d"), 20
                )
            )
        else:
            start = max(recent, starts[api] or recent)
            streams.append(_date_jobs(api, start, today, epoch, 20))
    yield from _interleave(streams)
    end = recent - timedelta(days=1)
    streams = []
    for api in enabled:
        start = starts[api]
        if api in BASICS or start is None or start > end:
            continue
        streams.append(
            _period_history_jobs(api, start, today, ids)
            if api in SYMBOL_PERIODS
            else _date_jobs(api, start, end, "history", 40)
        )
    yield from _interleave(streams)
