"""ETF daily creation/redemption baskets, not quarterly fund holdings or PIT.

Pure supplier request planning. Keep cash rows, overseas identifiers, raw cash
substitution flags and '-' values; no credentials, network or storage access.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
from itertools import zip_longest
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "etf_sh_cons": "trade_date ts_code con_code con_name qty sub_flag cpr rdr sca exchange".split(),
    "etf_sz_cons": "trade_date ts_code con_code con_name qty sub_flag cpr rdr sub_cc red_cc exchange".split(),
}
INPUT_FIELDS = {
    api: "ts_code trade_date con_code start_date end_date".split() for api in FIELDS
}
ETF_BASKET_CONTRACTS = {}
for _api, _doc, _market in (("etf_sh_cons", 471, "SH"), ("etf_sz_cons", 472, "SZ")):
    _spec = _contract(
        3000,
        ("ts_code", "trade_date", "con_code", "exchange"),
        required=("ts_code", "trade_date", "con_code"),
        nullable=tuple(
            f for f in FIELDS[_api] if f not in ("ts_code", "trade_date", "con_code")
        ),
        extra=FIELDS[_api],
        rpm=50,
        cap_verified=False,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        reviewed_on="20260909",
        input_fields=INPUT_FIELDS[_api],
        hidden_fields=[],
        documented_row_cap=3000,
        minimum_points=8000,
        independent_permission=None,
        permission_status="unprobed",
        permission_note="Detail page states 8000 points and no separate entitlement requirement; actual account access is unprobed. Do not infer or purchase an independent permission.",
        dependencies=["etfs"],
        supplier_etf_market=_market,
        date_field="trade_date",
        split_axis="basket_trade_date",
        preserve_distinct_rows=True,
        history_bound_verified=False,
        history_gap="official_earliest_date_unspecified",
        publication_gap="Page says daily pre-market disclosure but provides no announcement timestamp, timezone, exact release clock or revision log. trade_date is basket applicability, not known_at; _fetched_at is only our observation time.",
        revision_gap="Keep raw _row_identity and immutable observations for conflicting basket revisions. Recent7d refresh does not prove older rows cannot be revised; old-history revision sweeps remain a separate requirement.",
        pagination_gap="No offset/limit is documented. Split a bounded range by calendar date; a single ETF/day at3000 rows stays unresolved unless a complete component universe independently proves con_code subdivision coverage.",
        unknown_history_gap="Unfiltered per-ETF history discovery may hit3000; with no verified lower bound a capped response cannot prove whole history or safely invent a start date.",
        component_gap="exchange identifies the component market HK/SH/SZ/OTH, not ETF listing venue. Preserve cash/overseas/other rows and opaque con_code, never derive a stock or ETF discovery universe from these components.",
        raw_numeric_fields=["qty", "cpr", "rdr", "sca"]
        if _market == "SH"
        else ["qty", "cpr", "rdr", "sub_cc", "red_cc"],
        raw_numeric_note="Official examples include qty=0 and '-' in nominal float columns. Preserve source scalars; do not force float/positive/finite constraints on these raw columns.",
        units={
            "qty": "shares",
            "cpr": "percent",
            "rdr": "percent",
            **(
                {"sca": "CNY"}
                if _market == "SH"
                else {"sub_cc": "CNY", "red_cc": "CNY"}
            ),
        },
        basket_scope_gap="Creation/redemption basket quantities are not portfolio weights or total fund holdings. No minimum creation unit, full PCF header or NAV/exposure denominator is documented here.",
    )
    ETF_BASKET_CONTRACTS[_api] = _spec

ETF_BASKET_CONTRACTS["etf_sh_cons"]["cash_semantics"] = {
    "sub_flag": "source cash substitution flag; examples allow/require; do not close the enum",
    "cpr": "subscription cash substitution premium percentage",
    "rdr": "redemption cash substitution discount percentage",
    "sca": "cash substitution amount in CNY",
}
ETF_BASKET_CONTRACTS["etf_sz_cons"]["cash_semantics"] = {
    "sub_flag": "source cash substitution flag; preserve raw values",
    "cpr": "subscription cash substitution margin percentage",
    "rdr": "redemption cash substitution margin percentage",
    "sub_cc": "subscription substitution amount in CNY",
    "red_cc": "redemption substitution amount in CNY",
}


def _enabled(config):
    values = config.get("etf_basket_apis", tuple(ETF_BASKET_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(v, str) or v not in ETF_BASKET_CONTRACTS for v in values
    ):
        raise ValueError("etf_basket_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _etfs(identifiers):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map families to records")
    values = identifiers.get("etfs", ())
    if not isinstance(values, (tuple, list)):
        raise ValueError("etfs must contain source codes or records")
    codes = set()
    for item in values:
        code = item.get("ts_code") if isinstance(item, dict) else item
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]+\.[A-Z]+", code):
            raise ValueError("Invalid supplier ETF identifier")
        codes.add(code)
    return sorted(codes)


def _starts(config, enabled):
    setting = config.get("etf_basket_history_start", config.get("history_start"))
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("etf_basket_history_start must be YYYYMMDD or API mapping")
    if isinstance(setting, dict) and set(setting) - ETF_BASKET_CONTRACTS.keys():
        raise ValueError("Unknown ETF basket history API")
    return {
        api: _parse(value) if value is not None else None
        for api in enabled
        for value in [setting.get(api) if isinstance(setting, dict) else setting]
    }


def etf_basket_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["etf_basket_apis"] = enabled_apis
    enabled = _enabled(config)
    codes = _etfs(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = ETF_BASKET_CONTRACTS[api]
        selected = [c for c in codes if c.endswith("." + spec["supplier_etf_market"])]
        gaps.append(
            {
                "api_name": api,
                "reason": "stored_discovery_completeness_unverified"
                if selected
                else "awaiting_stored_etf_discovery",
                "dependencies": ["etfs"],
                "observed_codes": len(selected),
                "universe_complete": False,
            }
        )
        gaps.append(
            {
                "api_name": api,
                "reason": "unknown_history_start_requires_discovery"
                if starts[api] is None
                else "configured_scope_does_not_prove_earlier_history_absent",
            }
        )
        for key in (
            "publication_gap",
            "revision_gap",
            "pagination_gap",
            "unknown_history_gap",
            "component_gap",
            "basket_scope_gap",
        ):
            gaps.append({"api_name": api, "reason": key, "detail": spec[key]})
        gaps.append({"api_name": api, "reason": "account_permission_unprobed"})
    unsupported = [c for c in codes if not c.endswith((".SH", ".SZ"))]
    if unsupported:
        gaps.append(
            {
                "api_name": None,
                "reason": "no_documented_basket_endpoint_for_etf_market",
                "codes": unsupported,
            }
        )
    return gaps


def _history_windows(start, end):
    """Stable completed years, completed months, then individual tail dates."""
    cursor = start
    while cursor <= end:
        if cursor.year < end.year:
            right = date(cursor.year, 12, 31)
        elif cursor.month < end.month:
            right = date(
                cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]
            )
        else:
            right = cursor
        yield cursor, right
        cursor = right + timedelta(days=1)


def _recent(api, codes, start, today, epoch):
    left = max(start or date.min, today - timedelta(days=6))
    for code in codes:
        yield {
            "api_name": api,
            "params": {
                "ts_code": code,
                "start_date": left.strftime("%Y%m%d"),
                "end_date": today.strftime("%Y%m%d"),
            },
            "priority": 20,
            "epoch": epoch,
        }


def _history(api, codes, start, today):
    if start is None:
        for code in codes:
            yield {
                "api_name": api,
                "params": {"ts_code": code},
                "priority": 40,
                "epoch": "history",
            }
        return
    for left, right in _history_windows(start, today - timedelta(days=7)):
        for code in codes:
            yield {
                "api_name": api,
                "params": {
                    "ts_code": code,
                    "start_date": left.strftime("%Y%m%d"),
                    "end_date": right.strftime("%Y%m%d"),
                },
                "priority": 40,
                "epoch": "history",
            }


def iter_etf_basket_jobs(config, today, identifiers=None):
    """Recent first, then lazy scoped history; retired source ETF codes retained.

    Calendar days are deliberate: no stock calendar can silently exclude basket
    publications. Parent owns date splitting, retries and persistent cursor state.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    codes = _etfs(identifiers if identifiers is not None else {})
    starts = _starts(config, enabled)
    if any(start is not None and start > today for start in starts.values()):
        raise ValueError("history scope starts after today")
    epoch = config.get("planning_epoch", today.strftime("%Y%m%d"))
    if not isinstance(epoch, str) or not epoch:
        raise ValueError("planning_epoch must be a nonempty string")
    groups = {
        api: [
            c
            for c in codes
            if c.endswith("." + ETF_BASKET_CONTRACTS[api]["supplier_etf_market"])
        ]
        for api in enabled
    }
    for recent in (True, False):
        streams = [
            (
                _recent(api, groups[api], starts[api], today, epoch)
                if recent
                else _history(api, groups[api], starts[api], today)
            )
            for api in enabled
        ]
        for row in zip_longest(*streams):
            for job in row:
                if job is not None:
                    yield job
