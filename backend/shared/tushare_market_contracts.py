"""Read-only fund, industry, convertible and futures acquisition contracts.

Planning is pure. The common pipeline owns calls, cap splits and persistence.
Raw vendor identifiers are confined to this supplier request boundary.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

EXCHANGES = ("CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")

MARKET_CONTRACTS = {
    "fund_basic": _contract(15000, ("ts_code",), split=False),
    "fund_company": _contract(1000, ("name",), split=False, cap_verified=False),
    "fund_manager": _contract(
        5000,
        ("ts_code", "name", "begin_date", "ann_date"),
        required=("ts_code", "name"),
        nullable=("begin_date", "ann_date", "end_date"),
        split=False,
    ),
    "fund_nav": _contract(
        1000,
        ("ts_code", "nav_date", "ann_date"),
        required=("ts_code", "nav_date"),
        nullable=("ann_date",),
        cap_verified=False,
    ),
    "fund_share": _contract(2000, ("ts_code", "trade_date")),
    "fund_div": _contract(
        1000,
        ("ts_code", "ann_date", "ex_date", "pay_date", "div_proc"),
        required=("ts_code",),
        nullable=("ann_date", "ex_date", "pay_date", "div_proc"),
        split=False,
        cap_verified=False,
    ),
    "etf_index": _contract(5000, ("ts_code",), split=False),
    "index_weight": _contract(
        1000, ("index_code", "con_code", "trade_date"), cap_verified=False
    ),
    "index_classify": _contract(
        1000,
        ("index_code", "src"),
        required=("index_code", "level"),
        split=False,
        cap_verified=False,
    ),
    "index_member_all": _contract(
        2000,
        ("l3_code", "ts_code", "in_date", "out_date"),
        required=("l3_code", "ts_code"),
        nullable=("in_date", "out_date"),
        split=False,
    ),
    "sw_daily": _contract(4000, ("ts_code", "trade_date")),
    "cb_basic": _contract(2000, ("ts_code",), split=False),
    "cb_issue": _contract(
        2000, ("ts_code", "ann_date"), required=("ts_code",), nullable=("ann_date",)
    ),
    "cb_call": _contract(
        2000,
        ("ts_code", "ann_date", "call_type", "call_date"),
        required=("ts_code", "call_type"),
        nullable=("ann_date", "call_date"),
    ),
    "cb_rate": _contract(
        2000, ("ts_code", "rate_start_date", "rate_end_date"), split=False
    ),
    "cb_daily": _contract(2000, ("ts_code", "trade_date")),
    "cb_price_chg": _contract(
        2000,
        ("ts_code", "publish_date", "change_date"),
        required=("ts_code",),
        nullable=("publish_date", "change_date"),
        split=False,
    ),
    "cb_share": _contract(
        2000,
        ("ts_code", "publish_date", "end_date"),
        required=("ts_code", "end_date"),
        nullable=("publish_date",),
    ),
    "fut_basic": _contract(10000, ("ts_code",), split=False),
    "fut_daily": _contract(2000, ("ts_code", "trade_date")),
    "fut_mapping": _contract(2000, ("ts_code", "trade_date")),
    "fut_settle": _contract(1600, ("ts_code", "trade_date")),
    "fut_wsr": _contract(
        1000,
        (
            "trade_date",
            "symbol",
            "warehouse",
            "wh_id",
            "area",
            "year",
            "grade",
            "brand",
            "place",
            "is_ct",
            "exchange",
        ),
        required=("trade_date", "symbol", "warehouse"),
        nullable=(
            "wh_id",
            "area",
            "year",
            "grade",
            "brand",
            "place",
            "is_ct",
            "exchange",
        ),
    ),
}

# Explicit dependency and saturation metadata: callers must not silently replace
# an incomplete universe by the records present in one capped discovery response.
DEPENDENCIES = {
    "fund_nav": ("funds",),
    "fund_div": ("funds",),
    "index_weight": ("indexes",),
    "index_member_all": ("sw_l3",),
    "cb_rate": ("bonds",),
    "cb_price_chg": ("bonds",),
    "cb_share": ("bonds",),
}
for _api, _spec in MARKET_CONTRACTS.items():
    _spec["dependencies"] = list(DEPENDENCIES.get(_api, ()))
    _spec["split_axis"] = (
        "announcement_date"
        if _api in ("cb_issue", "cb_call", "cb_share")
        else "observation_date"
    )

MARKET_CONTRACTS["fund_manager"]["pagination"] = {
    "offset_param": "offset",
    "limit_param": "limit",
    "page_size": 1000,
}
MARKET_CONTRACTS["cb_price_chg"]["permission_note"] = (
    "Independent entitlement; points do not grant access. Probe once, then block this API on denial."
)
MARKET_CONTRACTS["cb_share"]["parameter_note"] = (
    "Official required-ann_date table contradicts ts_code-only example; start/end window must be live-verified."
)
for _api, _family, _param in (
    ("fund_share", "funds", "ts_code"),
    ("index_weight", "stocks", "con_code"),
    ("index_member_all", "stocks", "ts_code"),
    ("sw_daily", "sw_indexes", "ts_code"),
    ("cb_daily", "bonds", "ts_code"),
    ("cb_issue", "bonds", "ts_code"),
    ("cb_call", "bonds", "ts_code"),
    ("fut_daily", "futures", "ts_code"),
    ("fut_mapping", "futures_continuous", "ts_code"),
    ("fut_settle", "futures", "ts_code"),
    ("fut_wsr", "futures_products", "symbol"),
):
    # index_weight has no con_code input; a saturated single index/day cannot be
    # split by constituent. Preserve it as an unresolved cap instead of inventing one.
    if _api != "index_weight":
        MARKET_CONTRACTS[_api]["saturation_fallback"] = _family
        MARKET_CONTRACTS[_api]["saturation_param"] = _param


def _codes(identifiers, family):
    values = []
    for row in identifiers.get(family, []):
        if isinstance(row, dict):
            if family == "sw_l3" and row.get("level") not in (None, "L3"):
                continue
            code = row.get("ts_code") or row.get("index_code")
        else:
            code = row
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", code):
            raise ValueError(f"Invalid supplier identifier in {family}")
        values.append(code)
    return sorted(set(values))


def _months(start, end):
    day = start
    while day <= end:
        last = min(end, date(day.year, day.month, monthrange(day.year, day.month)[1]))
        yield day, last
        day = last + timedelta(days=1)


def iter_market_jobs(config, today, identifiers=None):
    """Generate every configured historical window, with all recent work first.

    identifiers accepts raw records or supplier-code strings in funds/indexes/
    bonds/sw_l3. Raw record fields: ts_code (index_code for index_classify),
    level for SW classification. Do not remove expired or unknown-status records.
    Other dependency families occur only as cap fallbacks, owned by the caller.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be date")
    start, end = _parse(config["history_start"]), today - timedelta(days=1)
    if start > end:
        raise ValueError("history_start must precede today")
    enabled = set(config.get("market_apis", MARKET_CONTRACTS))
    if enabled - MARKET_CONTRACTS.keys():
        raise ValueError("Unknown market API")
    ids = identifiers or {}
    codes = {
        family: _codes(ids, family) for family in ("funds", "indexes", "bonds", "sw_l3")
    }
    recent, epoch = max(start, today - timedelta(days=7)), today.strftime("%Y%m%d")

    def job(api, params, priority=25, version=epoch):
        return {
            "api_name": api,
            "params": params,
            "priority": priority,
            "epoch": version,
        }

    if "fund_basic" in enabled:
        for market in ("E", "O"):
            for status in ("D", "I", "L", None):
                params = {"market": market}
                if status:
                    params["status"] = status
                # Unfiltered request can reveal new/unknown statuses; caps stay gaps.
                yield job("fund_basic", params)
    for api in ("fund_company", "etf_index", "cb_basic"):
        if api in enabled:
            yield job(api, {})
    if "fund_manager" in enabled:
        yield job("fund_manager", {"offset": 0, "limit": 1000})
    if "index_classify" in enabled:
        for src in ("SW2014", "SW2021"):
            for level in ("L1", "L2", "L3"):
                yield job("index_classify", {"src": src, "level": level})
    if "fut_basic" in enabled:
        for exchange in EXCHANGES:
            for fut_type in ("1", "2"):
                # No listing cut-off: ordinary, continuous and expired contracts.
                yield job("fut_basic", {"exchange": exchange, "fut_type": fut_type})
    if "index_member_all" in enabled:
        for code in codes["sw_l3"]:
            for is_new in ("Y", "N"):
                yield job("index_member_all", {"l3_code": code, "is_new": is_new})
    for api, family in (
        ("fund_div", "funds"),
        ("cb_rate", "bonds"),
        ("cb_price_chg", "bonds"),
    ):
        if api in enabled:
            for code in codes[family]:
                yield job(api, {"ts_code": code})

    for phase in ("recent", "history"):
        left, right = (
            (recent, end) if phase == "recent" else (start, recent - timedelta(days=1))
        )
        if left > right:
            continue
        priority, version = (25, epoch) if phase == "recent" else (45, "history")
        for api, family in (("fund_nav", "funds"), ("cb_share", "bonds")):
            if api in enabled:
                for code in codes[family]:
                    # One full interval; the shared collector bisects capped windows.
                    yield job(
                        api,
                        {
                            "ts_code": code,
                            "start_date": left.strftime("%Y%m%d"),
                            "end_date": right.strftime("%Y%m%d"),
                        },
                        priority,
                        version,
                    )
        if "index_weight" in enabled:
            for code in codes["indexes"]:
                for a, b in reversed(list(_months(left, right))):
                    yield job(
                        "index_weight",
                        {
                            "index_code": code,
                            "start_date": a.strftime("%Y%m%d"),
                            "end_date": b.strftime("%Y%m%d"),
                        },
                        priority,
                        version,
                    )
        for api in ("cb_issue", "cb_call"):
            if api in enabled:
                for a, b in reversed(list(_months(left, right))):
                    yield job(
                        api,
                        {
                            "start_date": a.strftime("%Y%m%d"),
                            "end_date": b.strftime("%Y%m%d"),
                        },
                        priority,
                        version,
                    )
        for api in (
            "fund_share",
            "sw_daily",
            "cb_daily",
            "fut_daily",
            "fut_mapping",
            "fut_settle",
            "fut_wsr",
        ):
            if api not in enabled:
                continue
            variants = (
                [{"market": m} for m in ("SH", "SZ")]
                if api == "fund_share"
                else (
                    [{"exchange": e} for e in EXCHANGES]
                    if api in ("fut_daily", "fut_settle", "fut_wsr")
                    else [{}]
                )
            )
            day = right
            while day >= left:
                for params in variants:
                    yield job(
                        api,
                        {**params, "trade_date": day.strftime("%Y%m%d")},
                        priority,
                        version,
                    )
                day -= timedelta(days=1)


def market_prerequisites(identifiers=None, enabled_apis=None):
    """Return missing discovery dependencies without declaring empty coverage."""
    ids, enabled = (
        identifiers or {},
        set(MARKET_CONTRACTS if enabled_apis is None else enabled_apis),
    )
    return [
        {
            "api_name": api,
            "dependencies": [f for f in families if not ids.get(f)],
            "reason": "awaiting_complete_stored_discovery",
        }
        for api, families in DEPENDENCIES.items()
        if api in enabled and any(not ids.get(f) for f in families)
    ]
