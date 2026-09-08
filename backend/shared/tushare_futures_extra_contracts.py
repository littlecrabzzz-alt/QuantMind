"""Pure contracts for seven additional futures APIs; no account/network access.

Supplier trading dates, rolling period labels and regulator week identifiers are
separate axes. No equity calendar, stock normalization or invented pagination.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "fut_trade_cal": "exchange cal_date is_open pretrade_date".split(),
    "fut_daily_adj": "ts_code trade_date pre_close pre_settle open high low close settle change1 change2 vol amount oi oi_chg delv_settle exchange".split(),
    "fut_weekly_monthly": "ts_code trade_date end_date freq open high low close pre_close settle pre_settle vol amount oi oi_chg exchange change1 change2".split(),
    "fut_holding": "trade_date symbol broker vol vol_chg long_hld long_chg short_hld short_chg exchange".split(),
    "fut_index_daily": "ts_code trade_date close open high low pre_close change pct_chg vol amount".split(),
    "fut_weekly_detail": "exchange prd name vol vol_yoy amount amout_yoy cumvol cumvol_yoy cumamt cumamt_yoy open_interest interest_wow mc_close close_wow week week_date".split(),
    "ft_limit": "trade_date ts_code name up_limit down_limit m_ratio cont exchange".split(),
}
INPUT_FIELDS = {
    "fut_trade_cal": "exchange start_date end_date is_open".split(),
    "fut_daily_adj": "trade_date ts_code exchange start_date end_date".split(),
    "fut_weekly_monthly": "ts_code trade_date start_date end_date freq exchange".split(),
    "fut_holding": "trade_date symbol start_date end_date exchange".split(),
    "fut_index_daily": "ts_code trade_date start_date end_date".split(),
    "fut_weekly_detail": "week prd start_week end_week exchange fields".split(),
    "ft_limit": "ts_code trade_date start_date end_date cont exchange".split(),
}
# doc, row cap (operational alarm when undocumented), points, keys, earliest scope floor
_DOCS = {
    "fut_trade_cal": (467, 1000, 2000, ("exchange", "cal_date"), None),
    "fut_daily_adj": (492, 3000, 5000, ("ts_code", "trade_date"), None),
    "fut_weekly_monthly": (
        337,
        6000,
        None,
        ("ts_code", "trade_date", "freq", "end_date"),
        None,
    ),
    "fut_holding": (
        139,
        2000,
        2000,
        ("exchange", "trade_date", "symbol", "broker"),
        None,
    ),
    "fut_index_daily": (468, 1000, 2000, ("ts_code", "trade_date"), None),
    "fut_weekly_detail": (
        216,
        4000,
        600,
        ("exchange", "prd", "week", "week_date"),
        "20100301",
    ),
    "ft_limit": (368, 4000, 5000, ("ts_code", "trade_date"), "20050101"),
}
FUTURES_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _keys, _start) in _DOCS.items():
    _spec = _contract(
        _cap,
        _keys,
        nullable=tuple(f for f in FIELDS[_api] if f not in _keys),
        extra=FIELDS[_api],
        start=_start,
        rpm=50,
        split=_api != "fut_weekly_detail",
        cap_verified=_api not in ("fut_trade_cal", "fut_index_daily"),
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        permission_note="No independent entitlement is stated on this detail page; account access must be probed, never inferred from points.",
        input_fields=INPUT_FIELDS[_api],
        hidden_fields=[],
        dependencies=[],
        split_axis="supplier_week"
        if _api == "fut_weekly_detail"
        else "calendar_date"
        if _api == "fut_trade_cal"
        else "period_label"
        if _api == "fut_weekly_monthly"
        else "trade_date",
        history_bound_verified=_start is not None,
        history_gap=None if _start else "official_earliest_date_unspecified",
        pagination_gap="No offset/limit input is documented; saturated terminal partitions remain gaps.",
        identity_note="Preserve supplier codes, exchange, symbol and product spelling/case. Never use equity prefix rules or a stock trading calendar.",
        session_note="Dates are supplier trade-date labels. No intraday session or night-session civil-date mapping is supplied; daily bars cannot reconstruct those sessions.",
    )
    if not _spec["row_cap_verified"]:
        _spec["cap_note"] = (
            "No numerical cap is documented; 1000 is only a conservative saturation alarm, not proof of a complete response."
        )
    FUTURES_EXTRA_CONTRACTS[_api] = _spec

FUTURES_EXTRA_CONTRACTS["fut_trade_cal"].update(
    hidden_fields=["pretrade_date"],
    documented_exchanges=["SHFE", "DCE", "CFFEX", "CZCE", "INE"],
    discovery_gap="The page lists five exchanges but not GFEX. Unfiltered calendar requests discover supplied exchanges without claiming complete GFEX coverage.",
    calendar_note="Keep open and closed days (omit is_open filter), pretrade_date and each exchange separately. Not an A-share calendar or proof of night sessions. Planning covers through today; future calendar availability remains unverified.",
)
FUTURES_EXTRA_CONTRACTS["fut_daily_adj"].update(
    hidden_fields=["delv_settle"],
    documented_exchanges=["CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"],
    saturation_fallback="futures_continuous",
    saturation_param="ts_code",
    adjustment_note="Supplier continuous/main-contract series: at a roll use prior-day new/old close ratio, accumulating its reciprocal from the first segment. It is not individual-contract price or equity corporate-action adjustment; no separate factor field is exposed.",
    refresh_gap="Recent overlap alone cannot certify older supplier corrections or roll-series revisions; retain raw observations and schedule a separate historical audit.",
    unit_note="vol/oi are contracts; amount is ten-thousand CNY. Nullable delivery settlement must not be coerced to zero.",
)
FUTURES_EXTRA_CONTRACTS["fut_weekly_monthly"].update(
    saturation_fallback="futures",
    saturation_param="ts_code",
    permission_gap="The detail page gives no points threshold or independent-rights statement.",
    period_note="freq is mandatory: week/month. trade_date labels Friday or month end; end_date is calculation cutoff. Keep both axes and freq in keys, including evolving current-period rows; a future label does not make a completed bar.",
    discovery_gap="Dated and continuous contract coverage is unverified; stored fut_basic histories must retain expired contracts. An all-market period-label request also discovers codes omitted by current master data.",
    refresh_gap="Recent period-label overlap preserves in-progress periods but does not certify historical revisions.",
)
FUTURES_EXTRA_CONTRACTS["fut_holding"].update(
    hidden_fields=["exchange"],
    parameter_note="At least trade_date or symbol is mandatory. Bare start_date/end_date is invalid. SHFE includes INE contracts; do not sum a second INE copy. symbol may denote a dated contract or a product, never a ts_code suffix.",
    saturation_gap="All-market daily rankings may hit 2000. Subdivision must use observed exchange+symbol pairs, retaining product and contract rankings; generic ts_code/stock fanout is invalid and not registered here.",
    discovery_gap="Observed holding symbols/members, including retired products/contracts, are not a complete historical universe; broker is only a member short name, not a verified immutable identity.",
    preserve_distinct_rows=True,
    row_identity_note="No immutable broker/member identifier is documented. Add generated _row_identity to read dedupe keys to preserve differing source rows; do not request it upstream.",
    null_note="Missing vol/long/short ranking values are absent measures, not zero positions. Product and contract ranking rows must remain distinct.",
)
FUTURES_EXTRA_CONTRACTS["fut_index_daily"].update(
    saturation_fallback="futures_indexes",
    saturation_param="ts_code",
    discovery_gap="The document lists legacy .NH index codes but is not a verified current or historical master. Daily unfiltered requests discover symbols; retain observed retired/renamed indexes.",
    unit_note="Index point levels; vol is contracts and amount is thousand CNY, unlike the ten-thousand CNY futures-bar amount.",
)
FUTURES_EXTRA_CONTRACTS["fut_weekly_detail"].update(
    history_start_precision="month",
    week_note="Supplier year/week ordinal, not a proven ISO calendar. Query every ordinal 01..53 for a selected year, without deriving dates or skipping holidays. Preserve raw week (official examples include 20199) and week_date; no zero-padding rewrite. Year edges and formatting equivalence need source verification.",
    partition_note="Explicit exact-week requests. No generic day split for start_week/end_week; a saturated week needs observed exchange/prd subdivision, never guessed offsets.",
    discovery_gap="Only major products are in this CSRC series; no claim to all futures contracts/exchanges. Historical product universe and supplier week convention remain unverified.",
    refresh_gap="Refresh current and previous supplier years (all 01..53), since precise current week mapping is not verified. Future/holiday empty responses stay unverified; older revisions need an audit.",
    unit_note="vol/open_interest are contracts; amount/cumamt are hundred-million CNY. Retain official misspelling amout_yoy; do not alias it to amount_yoy.",
    permission_note="Detail says 600 points, and >=5000 normal calls unrestricted, but gives no numeric per-minute rate; runtime operational ceiling remains 50 and account capability unprobed.",
)
FUTURES_EXTRA_CONTRACTS["ft_limit"].update(
    history_start_precision="year",
    saturation_fallback="futures",
    saturation_param="ts_code",
    field_note="ts_code is a futures contract despite the source table's stock-code wording. m_ratio is minimum margin percent, not an equity percentage or a trade authorization.",
)


def _enabled(config):
    apis = config.get("futures_extra_apis", tuple(FUTURES_EXTRA_CONTRACTS))
    if not isinstance(apis, (list, tuple)) or any(
        not isinstance(api, str) or api not in FUTURES_EXTRA_CONTRACTS for api in apis
    ):
        raise ValueError(
            "futures_extra_apis must list known FUTURES_EXTRA_CONTRACTS APIs"
        )
    return tuple(dict.fromkeys(apis))


def _starts(config, enabled):
    value = config.get("futures_extra_history_start", config.get("history_start"))
    if value is not None and not isinstance(value, (str, dict)):
        raise ValueError(
            "futures_extra_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(value, dict) and value.keys() - FUTURES_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in futures_extra_history_start")
    starts = {}
    for api in enabled:
        supplied = (
            value.get(api, config.get("history_start"))
            if isinstance(value, dict)
            else value
        )
        floor = FUTURES_EXTRA_CONTRACTS[api]["history_start"]
        parsed = _parse(supplied) if supplied is not None else None
        starts[api] = (
            max(parsed, _parse(floor))
            if parsed and floor
            else parsed or (_parse(floor) if floor else None)
        )
    return starts


def _identifiers(identifiers, enabled):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to codes")
    families = {
        FUTURES_EXTRA_CONTRACTS[a]["saturation_fallback"]
        for a in enabled
        if FUTURES_EXTRA_CONTRACTS[a].get("saturation_fallback")
    }
    result = {}
    for family in sorted(families):
        rows = identifiers.get(family, ())
        if not isinstance(rows, (list, tuple)):
            raise ValueError(f"Invalid discovery collection for {family}")
        codes = set()
        for row in rows:
            code = row.get("ts_code") if isinstance(row, dict) else row
            pattern = (
                r"[A-Za-z][A-Za-z0-9]*\.NH"
                if family == "futures_indexes"
                else r"[A-Za-z][A-Za-z0-9]*\.(CFX|ZCE|DCE|GFE|INE|SHF)"
            )
            if not isinstance(code, str) or not re.fullmatch(pattern, code):
                raise ValueError(f"Invalid supplier futures code in {family}")
            codes.add(code)
        result[family] = sorted(codes)
    return result


def futures_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["futures_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    ids = _identifiers(identifiers if identifiers is not None else {}, enabled)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = FUTURES_EXTRA_CONTRACTS[api]
        family = spec.get("saturation_fallback")
        if family:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [family],
                    "reason": "saturation_discovery_unverified",
                    "observed_codes": len(ids[family]),
                    "universe_complete": False,
                }
            )
        if spec["history_gap"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope"
                    if starts[api] is None
                    else "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        for kind in (
            "cap_note",
            "permission_gap",
            "discovery_gap",
            "refresh_gap",
            "saturation_gap",
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
    return gaps


def _windows(api, begin, end):
    if api == "fut_weekly_detail":
        for year in range(begin.year, end.year + 1):
            for ordinal in range(1, 54):
                yield {"week": f"{year:04d}{ordinal:02d}"}
        return
    day = begin
    while day <= end:
        if api == "fut_trade_cal":
            last = min(
                end, date(day.year, day.month, monthrange(day.year, day.month)[1])
            )
            yield {
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
            day = last + timedelta(days=1)
        else:
            for extra in (
                ({"freq": "week"}, {"freq": "month"})
                if api == "fut_weekly_monthly"
                else ({},)
            ):
                yield {"trade_date": day.strftime("%Y%m%d"), **extra}
            day += timedelta(days=1)


def iter_futures_extra_jobs(config, today, identifiers=None):
    """Recent work first, then round-robin lazy history across all enabled APIs.

    Unfiltered dates discover the supplied universe without excluding expired
    contracts. Identifiers are validated only for applicable saturation families;
    these are not proof of a complete universe. Unknown lower bounds skip history
    but never suppress recent discovery or the prerequisite gap.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    _identifiers(identifiers if identifiers is not None else {}, enabled)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = config.get("planning_epoch", today.strftime("%Y%m%d"))
    histories = {}
    for api in enabled:
        start = starts[api]
        recent = max(start or date.min, today - timedelta(days=6))
        ceiling = today
        if api == "fut_weekly_monthly":
            recent = max(start or date.min, today - timedelta(days=40))
            ceiling = max(
                today + timedelta(days=(4 - today.weekday()) % 7),
                today.replace(day=monthrange(today.year, today.month)[1]),
            )
        elif api == "fut_weekly_detail":
            recent = date(max(start.year if start else 2010, today.year - 1), 1, 1)
        for params in _windows(api, recent, ceiling):
            yield {"api_name": api, "params": params, "priority": 20, "epoch": epoch}
        if start and start < recent:
            histories[api] = iter(_windows(api, start, recent - timedelta(days=1)))
    while histories:
        for api in tuple(histories):
            params = next(histories[api], None)
            if params is None:
                del histories[api]
            else:
                yield {
                    "api_name": api,
                    "params": params,
                    "priority": 40,
                    "epoch": "history",
                }
