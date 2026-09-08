"""Pure credit, securities-lending, block-trade and pledge acquisition contracts.

All reads are supplier-boundary plans. No account access, persistence, fabricated
pagination or claim that sampled discovery is a complete historical universe.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "margin": "trade_date exchange_id rzye rzmre rzche rqye rqmcl rzrqye rqyl".split(),
    "margin_detail": "trade_date ts_code name rzye rqye rzmre rqyl rzche rqchl rqmcl rzrqye".split(),
    "margin_secs": "trade_date ts_code name exchange".split(),
    "slb_len": "trade_date ob auc_amount repo_amount repay_amount cb".split(),
    "block_trade": "ts_code trade_date price vol amount buyer seller".split(),
    "pledge_detail": "ts_code ann_date holder_name pledge_amount start_date end_date is_release release_date pledgor holding_amount pledged_amount p_total_ratio h_total_ratio is_buyback".split(),
    "pledge_stat": "ts_code end_date pledge_count unrest_pledge rest_pledge total_share pledge_ratio".split(),
}
INPUT_FIELDS = {
    "margin": "trade_date start_date end_date exchange_id".split(),
    "margin_detail": "trade_date ts_code start_date end_date".split(),
    "margin_secs": "ts_code trade_date exchange start_date end_date".split(),
    "slb_len": "trade_date start_date end_date".split(),
    "block_trade": "ts_code trade_date start_date end_date".split(),
    "pledge_detail": "ts_code ann_date start_date end_date".split(),
    "pledge_stat": "ts_code end_date".split(),
}
# doc, documented cap, natural-key candidates; source row identity supplements events.
_DOCS = {
    "margin": (58, 4000, ("trade_date", "exchange_id")),
    "margin_detail": (59, 6000, ("trade_date", "ts_code")),
    "margin_secs": (326, 6000, ("trade_date", "ts_code", "exchange")),
    "slb_len": (331, 5000, ("trade_date",)),
    "block_trade": (
        161,
        1000,
        ("ts_code", "trade_date", "buyer", "seller", "price", "vol", "amount"),
    ),
    "pledge_detail": (
        111,
        1000,
        ("ts_code", "ann_date", "holder_name", "pledgor", "start_date", "end_date"),
    ),
    "pledge_stat": (110, 1000, ("ts_code", "end_date")),
}
SECURITIES_APIS = ("margin_detail", "margin_secs", "block_trade")
STOCK_APIS = ("pledge_detail", "pledge_stat")
CREDIT_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _keys) in _DOCS.items():
    _required = (
        ("ts_code", "trade_date")
        if _api == "block_trade"
        else ("ts_code",)
        if _api == "pledge_detail"
        else _keys
    )
    _spec = _contract(
        _cap,
        _keys,
        required=_required,
        nullable=tuple(f for f in FIELDS[_api] if f not in _required),
        extra=FIELDS[_api],
        split=_api != "pledge_stat",
        rpm=50,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=2000,
        independent_permission=None,
        permission_note="The page states a points threshold, not verified account entitlement; no independent-rights grant is established by this contract.",
        input_fields=INPUT_FIELDS[_api],
        hidden_fields=[],
        history_bound_verified=False,
        history_gap="official_earliest_date_unspecified",
        stop_date=None,
        update_status="not_marked_stopped_in_reviewed_catalog",
        stop_note="No stop date is documented here; this does not verify current supplier freshness or authorize another API's rights.",
        dependencies=["stocks"] if _api == "pledge_stat" else [],
        split_axis="announcement_date"
        if _api == "pledge_detail"
        else "cutoff_date"
        if _api == "pledge_stat"
        else "trade_date",
        pagination_gap="No offset/limit input is documented. Exhausted legal date/code partitions remain explicit gaps.",
        identity_note="Keep raw source codes and all discovered historical/retired listings, including T-prefixed stock identities. Distinguish exchange_id from exchange and retain source fields on normalization.",
        refresh_gap="Recent overlap is not proof that older historical revisions were captured; retain observations and audit older windows separately.",
    )
    if _api in SECURITIES_APIS:
        _spec.update(
            saturation_fallback="credit_securities",
            saturation_param="ts_code",
            saturation_dependencies=["stocks", "funds", "credit_securities"],
        )
    elif _api in STOCK_APIS:
        _spec.update(
            saturation_fallback="stocks",
            saturation_param="ts_code",
            saturation_dependencies=["stocks"],
        )
    CREDIT_EXTRA_CONTRACTS[_api] = _spec

CREDIT_EXTRA_CONTRACTS["margin"].update(
    documented_exchanges=["SSE", "SZSE", "BSE"],
    update_note="Previous trading day's figures arrive next morning around 08:30, by 09:05 for this summary; SZSE/BSE Friday figures update Monday morning. Refresh seven calendar days, preserving holidays and delayed empties as unverified.",
    unit_note="Balances/buy/repay amounts are CNY; rqmcl/rqyl may be shares, fund units or lots, not a uniform money measure.",
)
CREDIT_EXTRA_CONTRACTS["margin_detail"].update(
    update_note="Previous-day publication is next morning; SZSE/BSE Friday data updates Monday. The description says Shanghai/Shenzhen yet also mentions Beijing: actual historical exchange coverage remains unverified.",
    field_note="name starts only after 20190910; missing older names are valid. Amount fields are CNY, rqyl/rqchl shares, and rqmcl may be shares/fund units/lots. Do not conflate repayment quantity with lending sold quantity.",
)
CREDIT_EXTRA_CONTRACTS["margin_secs"].update(
    documented_exchanges=["SSE", "SZSE", "BSE"],
    discovery_note="Daily pre-open eligible securities include ETFs. Stock-only discovery omits funds; use the union of stocks, listed fund codes and observed margin securities. Daily membership is not proof of earlier eligibility or complete PIT availability.",
    permission_note="2000-point threshold; 5000 points removes the documented total-count restriction, but account access and rate remain unprobed.",
)
CREDIT_EXTRA_CONTRACTS["slb_len"].update(
    documented_requests_per_minute={"2000_points": 200, "5000_points": 500},
    unit_note="ob/auc_amount/repo_amount/repay_amount/cb are hundred-million CNY; one aggregate row per trading date.",
    alias_note="This financing aggregate is distinct from catalog slb_sec, slb_sec_detail and slb_len_mm, which are marked stopped. Do not treat their historical coverage or termination status as aliases of slb_len.",
)
CREDIT_EXTRA_CONTRACTS["block_trade"].update(
    parameter_note="At least a stock code or date is required; planner uses exact trade_date for all-market discovery, never an empty request.",
    preserve_distinct_rows=True,
    row_identity_note="No unique trade ID is exposed. Keep differing source rows with generated _row_identity in read keys; never request that derived field upstream.",
    multiplicity_gap="Two truly separate trades may have identical code/date/buyer/seller/price/vol/amount. Raw capture preserves their multiplicity, but a content-hash view cannot certify trade counts; an occurrence-aware contract needs supplier evidence.",
    unit_note="vol is ten-thousand shares; the page does not state an amount unit. Preserve price/vol/amount and broker strings without filling nulls or guessing units.",
)
CREDIT_EXTRA_CONTRACTS["pledge_detail"].update(
    parameter_note="Input start_date/end_date bound announcements; output start_date/end_date are pledge initiation/expiry, not the query window. Retain ann_date, both lifecycle dates and release_date separately; do not substitute them.",
    preserve_distinct_rows=True,
    row_identity_note="No stable pledge event ID is documented; add generated _row_identity to natural-key candidates in read views, preserving changed is_release/is_buyback and distinct source rows.",
    unit_note="pledge_amount/holding_amount/pledged_amount are ten-thousand shares. is_buyback is the supplier 0/1 flag, not a missing-field default.",
    refresh_gap="A release or correction may modify an old announcement without a recent ann_date; recent announcement overlap cannot certify all changed lifecycle states.",
)
CREDIT_EXTRA_CONTRACTS["pledge_stat"].update(
    history_strategy="One stock-only discovery per observed stock requests all supplier history even when configured date scope is narrower. Unknown earliest history remains a gap; no start_date input exists.",
    parameter_note="end_date is a cutoff date. Do not assume a weekly cadence or map it to a trading/announcement date based on examples. Recent discovery requests each calendar cutoff date.",
    saturation_gap="A capped stock-only history request cannot be split by a generic start/end range. Explicit end_date partitions need verified cutoff coverage; a missing terminal partition remains blocked, never inferred complete from the last row.",
    unit_note="unrest_pledge/rest_pledge quantities are in ten-thousands. total_share units and ratio scaling are not fully specified on this page; preserve supplier values.",
)


def _enabled(config):
    enabled = config.get("credit_extra_apis", tuple(CREDIT_EXTRA_CONTRACTS))
    if not isinstance(enabled, (list, tuple)) or any(
        not isinstance(api, str) or api not in CREDIT_EXTRA_CONTRACTS for api in enabled
    ):
        raise ValueError(
            "credit_extra_apis must list known CREDIT_EXTRA_CONTRACTS APIs"
        )
    return tuple(dict.fromkeys(enabled))


def _starts(config, enabled):
    setting = config.get("credit_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "credit_extra_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - CREDIT_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in credit_extra_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        starts[api] = _parse(value) if value is not None else None
    return starts


def credit_identifiers(identifiers=None, enabled_apis=None):
    """Union source stock/eligible listed-fund codes, retaining retired/T identities.

    Fund master may contain off-exchange .OF codes: these are valid input records
    but are not margin-market codes. Preserve their raw master elsewhere, omit
    them from this outbound union. No exchange/prefix conversion is performed.
    """
    ids = identifiers if identifiers is not None else {}
    if not isinstance(ids, dict):
        raise ValueError("identifiers must map discovery families to records")
    enabled = _enabled(
        {
            "credit_extra_apis": list(CREDIT_EXTRA_CONTRACTS)
            if enabled_apis is None
            else enabled_apis
        }
    )
    if not set(enabled).intersection(SECURITIES_APIS + STOCK_APIS):
        return {}
    stocks = _stocks(ids)
    result = {"stocks": stocks}
    if set(enabled).intersection(SECURITIES_APIS):
        funds = ids.get("funds", ())
        if not isinstance(funds, (list, tuple)):
            raise ValueError("funds must contain supplier codes or discovery records")
        listed = []
        for row in funds:
            code = row.get("ts_code") if isinstance(row, dict) else row
            if not isinstance(code, str) or not re.fullmatch(
                r"[0-9]{6}\.(SH|SZ|BJ|OF)", code
            ):
                raise ValueError("Invalid supplier fund code")
            if not code.endswith(".OF"):
                listed.append(code)
        observed = _stocks({"stocks": ids.get("credit_securities", ())})
        result["credit_securities"] = sorted(set(stocks) | set(listed) | set(observed))
    return result


def credit_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["credit_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    ids = credit_identifiers(identifiers, enabled)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = CREDIT_EXTRA_CONTRACTS[api]
        family = spec.get("saturation_fallback")
        if family:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": spec["saturation_dependencies"],
                    "reason": "stored_discovery_completeness_unverified"
                    if ids[family]
                    else "awaiting_stored_security_discovery",
                    "observed_codes": len(ids[family]),
                    "universe_complete": False,
                }
            )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "unknown_history_start_requires_scope_or_discovery"
                if starts[api] is None
                else "configured_scope_does_not_prove_earlier_history_absent",
            }
        )
        for kind in ("refresh_gap", "multiplicity_gap", "saturation_gap"):
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
    day = begin
    while day <= end:
        if api in ("margin", "slb_len", "pledge_detail"):
            last = min(
                end, date(day.year, day.month, monthrange(day.year, day.month)[1])
            )
            yield {
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
            day = last + timedelta(days=1)
        else:
            yield {
                "end_date" if api == "pledge_stat" else "trade_date": day.strftime(
                    "%Y%m%d"
                )
            }
            day += timedelta(days=1)


def iter_credit_extra_jobs(config, today, identifiers=None):
    """All recent jobs first, then fair lazy history without guessed lower bounds.

    Pledge-stat stock-only discovery intentionally requests all supplier history;
    other unknown histories wait for an explicit configured scope. No current-
    status filtering, weekday shortcut, account probe or derived source fields.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    ids = credit_identifiers(identifiers, enabled)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api in enabled:
        start = starts[api]
        for params in _windows(api, max(start or recent, recent), today):
            yield {"api_name": api, "params": params, "priority": 20, "epoch": epoch}
        if api == "pledge_stat":
            histories[api] = iter({"ts_code": code} for code in ids["stocks"])
        elif start and start < recent:
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
