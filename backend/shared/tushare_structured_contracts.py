"""Reviewed read-only Tushare contracts and deterministic acquisition requests.

Pure planning only: no credentials, network, storage or production side effects.
Supplier suffix codes are accepted ONLY at this outbound request boundary.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re


def _contract(
    cap,
    keys,
    *,
    required=None,
    nullable=(),
    positive=(),
    split=True,
    start=None,
    rpm=120,
    extra=(),
    base=None,
    cap_verified=True,
):
    result = {
        "row_cap": cap,
        "required_fields": list(required or keys),
        "nullable_fields": list(nullable),
        "positive_fields": list(positive),
        "keys": list(keys),
        # Operational ceilings, not assertions of measured account permissions.
        "requests_per_minute": rpm,
        "split": {
            "start_param": "start_date",
            "end_param": "end_date",
            "precision": "day",
        }
        if split
        else None,
        "history_start": start,
        "attachment_fields": [],
        "extra_fields": list(extra),
        "row_cap_verified": cap_verified,
    }
    if base:
        result["catalog_api"] = base
        result["dataset_identity"] = base
        result["saturation_fallback"] = "stocks"
    return result


STRUCTURED_CONTRACTS = {
    "stock_basic": _contract(
        6000, ("ts_code",), required=("ts_code", "name"), split=False, rpm=50
    ),
    "stock_company": _contract(4500, ("ts_code",), split=False),
    "namechange": _contract(
        1000,
        ("ts_code", "name", "start_date"),
        nullable=("end_date", "ann_date"),
        cap_verified=False,
    ),
    "daily": _contract(
        6000,
        ("ts_code", "trade_date"),
        required=("ts_code", "trade_date", "close"),
        positive=("close",),
    ),
    "adj_factor": _contract(
        6000,
        ("ts_code", "trade_date"),
        required=("ts_code", "trade_date", "adj_factor"),
        positive=("adj_factor",),
        cap_verified=False,
    ),
    "daily_basic": _contract(6000, ("ts_code", "trade_date")),
    "stk_limit": _contract(5800, ("ts_code", "trade_date")),
    "suspend_d": _contract(
        1000,
        ("ts_code", "trade_date", "suspend_type", "suspend_timing"),
        required=("ts_code", "trade_date", "suspend_type"),
        nullable=("suspend_timing",),
        cap_verified=False,
    ),
    "moneyflow": _contract(6000, ("ts_code", "trade_date"), start="20100101"),
    "index_basic": _contract(8000, ("ts_code",), split=False, start="19900101"),
    "index_daily": _contract(1000, ("ts_code", "trade_date"), cap_verified=False),
    "shibor": _contract(
        2000, ("date",), extra=("1w", "2w", "1m", "3m", "6m", "9m", "1y")
    ),
    "shibor_quote": _contract(
        4000,
        ("date", "bank"),
        extra=tuple(
            f"{term}_{side}"
            for term in ("1w", "2w", "1m", "3m", "6m", "9m", "1y")
            for side in ("b", "a")
        ),
    ),
    "shibor_lpr": _contract(4000, ("date",), extra=("1y", "5y")),
    "cn_gdp": _contract(10000, ("quarter",), split=False),
    "cn_cpi": _contract(5000, ("month",), split=False),
    "cn_ppi": _contract(5000, ("month",), split=False),
    "cn_m": _contract(5000, ("month",), split=False),
    "cn_pmi": _contract(2000, ("month",), split=False),
    "sf_month": _contract(2000, ("month",), split=False),
}
# Demonstrated lower bounds from the 2026-09-09 authority capability probe,
# period 20260630. These are saturation alarms, NOT verified provider maxima.
# Using the ordinary 100-row alarm caused avoidable per-stock fanout even when
# the VIP endpoint returned thousands of rows in a single retained response.
VIP_OBSERVED_ROWS = {
    "income": 9000,
    "balancesheet": 7000,
    "cashflow": 6400,
    "fina_indicator": 10736,
    "forecast": 1913,
    "express": 66,
}

for _base in (
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "forecast",
    "express",
):
    _keys = ("ts_code", "end_date", "ann_date")
    if _base in ("income", "balancesheet", "cashflow"):
        _keys += ("report_type", "comp_type", "f_ann_date")
    elif _base == "forecast":
        _keys += ("type",)
    # A response below the alarm is a usable sample, not a completeness proof.
    STRUCTURED_CONTRACTS[_base + "_vip"] = _contract(
        max(100, VIP_OBSERVED_ROWS[_base]),
        _keys,
        required=("ts_code", "end_date"),
        nullable=("ann_date", "f_ann_date"),
        split=_base != "fina_indicator",
        base=_base,
        cap_verified=False,
    )
    STRUCTURED_CONTRACTS[_base + "_vip"].update(
        row_cap_basis="observed_response_lower_bound_not_verified_maximum",
        row_cap_observed_rows=VIP_OBSERVED_ROWS[_base],
        row_cap_observed_period="20260630",
        row_cap_observed_at="2026-09-09",
        row_cap_evidence="validation/global-vip-probe.json",
    )
    STRUCTURED_CONTRACTS[_base + "_vip"]["split_axis"] = (
        "report_period" if _base == "fina_indicator" else "announcement_date"
    )
    STRUCTURED_CONTRACTS[_base + "_vip"]["report_types"] = (
        [str(n) for n in range(1, 13)]
        if _base in ("income", "balancesheet", "cashflow")
        else []
    )


INDEX_MARKETS = ("MSCI", "CSI", "SSE", "SZSE", "CICC", "SW", "OTH")
DAY_APIS = ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d", "moneyflow")
MONTH_APIS = ("cn_cpi", "cn_ppi", "cn_m", "cn_pmi", "sf_month")


def _parse(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise ValueError("Expected YYYYMMDD")
    return datetime.strptime(value, "%Y%m%d").date()


def _years(start, end):
    for year in range(start.year, end.year + 1):
        yield max(start, date(year, 1, 1)), min(end, date(year, 12, 31))


def _quarters(start, end):
    for year in range(start.year, end.year + 1):
        for month in (3, 6, 9, 12):
            period = date(year, month, monthrange(year, month)[1])
            if start <= period <= end:
                yield period


def iter_structured_jobs(config, today, identifiers=None):
    """Yield api_name/params/priority/epoch; default full history, recent first.

    config: history_start YYYYMMDD, optional structured_apis explicit subset.
    identifiers: stocks and indexes are exhaustive *stored* vendor code lists.
    Missing identifiers postpone namechange/index_daily only; see prerequisites().
    Saturated requests require the parent pipeline's split/fallback handling.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be date")
    start, end = _parse(config["history_start"]), today - timedelta(days=1)
    if start > end:
        raise ValueError("history_start must precede today")
    enabled = set(config.get("structured_apis", STRUCTURED_CONTRACTS))
    if enabled - STRUCTURED_CONTRACTS.keys():
        raise ValueError("Unknown structured API")
    ids = identifiers or {}
    stocks, indexes = (
        sorted(set(ids.get("stocks", []))),
        sorted(set(ids.get("indexes", []))),
    )
    for code in stocks + indexes:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]+\.[A-Z]+", code):
            raise ValueError(
                "Identifiers must be supplier codes at the request boundary"
            )
    epoch = today.strftime("%Y%m%d")
    recent = max(start, today - timedelta(days=7))

    def job(api, params, priority=25, version=epoch):
        return {
            "api_name": api,
            "params": params,
            "priority": priority,
            "epoch": version,
        }

    if "stock_basic" in enabled:
        for status in ("L", "D", "P", "G", "UN"):
            for exchange in ("SSE", "SZSE", "BSE"):
                yield job("stock_basic", {"list_status": status, "exchange": exchange})
    if "stock_company" in enabled:
        for exchange in ("SSE", "SZSE", "BSE"):
            yield job("stock_company", {"exchange": exchange})
    if "index_basic" in enabled:
        for market in INDEX_MARKETS:
            yield job("index_basic", {"market": market})
    if "namechange" in enabled:
        for code in stocks:
            # Per-security full snapshot includes rows with unknown announcement date.
            yield job("namechange", {"ts_code": code})
    for api in MONTH_APIS:
        if api in enabled:
            yield job(
                api, {"start_m": start.strftime("%Y%m"), "end_m": end.strftime("%Y%m")}
            )
    if "cn_gdp" in enabled:
        yield job(
            "cn_gdp",
            {
                "start_q": f"{start.year}Q{(start.month - 1) // 3 + 1}",
                "end_q": f"{end.year}Q{(end.month - 1) // 3 + 1}",
            },
        )
    # Recent windows for EVERY API precede history. The caller can persist a
    # bounded iterator cursor without starving the later datasets behind daily.
    for phase in ("recent", "history"):
        left_bound, right_bound = (
            (recent, end) if phase == "recent" else (start, recent - timedelta(days=1))
        )
        if left_bound > right_bound:
            continue
        priority, version = (25, epoch) if phase == "recent" else (45, "history")
        for api in DAY_APIS:
            if api not in enabled:
                continue
            floor = max(
                left_bound,
                _parse(
                    STRUCTURED_CONTRACTS[api]["history_start"]
                    or config["history_start"]
                ),
            )
            day = right_bound
            while day >= floor:
                # Do not let an incomplete calendar silently remove dates.
                yield job(
                    api, {"trade_date": day.strftime("%Y%m%d")}, priority, version
                )
                day -= timedelta(days=1)
        for api in ("shibor", "shibor_quote", "shibor_lpr", "index_daily"):
            if api not in enabled:
                continue
            # index_daily explicitly excludes SW; its history remains a ledger gap.
            codes = (
                [c for c in indexes if not c.endswith((".SI", ".SW"))]
                if api == "index_daily"
                else [None]
            )
            for code in codes:
                for left, right in reversed(list(_years(left_bound, right_bound))):
                    params = {
                        "start_date": left.strftime("%Y%m%d"),
                        "end_date": right.strftime("%Y%m%d"),
                    }
                    if code:
                        params["ts_code"] = code
                    yield job(api, params, priority, version)
        for api in sorted(enabled):
            if not api.endswith("_vip"):
                continue
            base = STRUCTURED_CONTRACTS[api]["catalog_api"]
            for period in reversed(list(_quarters(start, end))):
                recent_report = (end - period).days <= 730
                if recent_report != (phase == "recent"):
                    continue
                types = (
                    range(1, 13)
                    if base in ("income", "balancesheet", "cashflow")
                    else [None]
                )
                for report_type in types:
                    params = {"period": period.strftime("%Y%m%d")}
                    if report_type:
                        params["report_type"] = str(report_type)
                    # Preserve unknown ann_date. Saturation first fans out by stock.
                    yield job(api, params, priority, version)


def structured_prerequisites(identifiers=None):
    """Visible dependency gaps; an empty discovery list is not zero coverage."""
    ids = identifiers or {}
    gaps = []
    if not ids.get("stocks"):
        gaps.append(
            {"apis": ["namechange"], "reason": "awaiting_stock_basic_all_statuses"}
        )
    if not ids.get("indexes"):
        gaps.append(
            {"apis": ["index_daily"], "reason": "awaiting_index_basic_all_markets"}
        )
    return gaps
