"""Historical minute contracts only: no credentials, provider requests or activation."""

from datetime import date, datetime, time, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

SOURCE_HTML_SHA256 = {
    "stk_mins": "0552c43bbf60d4995afc1f07cf9bd1b196ffc444c47815c8e8b92d8710e3ffe9",
    "etf_mins": "aa3c45c1df0d884d11e3e4494baafc433a328095a0746caa168cb200ce853cb5",
    "idx_mins": "f5f848d97011ec53ee021a477de662b48d5797653fecc39f672cd5f53aba7eab",
    "sw_mins": "93cbf76f1f305947746d264410ec052486a3245e83bdc8f8d2e707900fc31720",
    "ft_mins": "7aaf14dd81b7b7306b37a7052e4628107d07154c9d0a4675314caf5caca04a17",
    "opt_mins": "b61e7d96f703194886f0400a61e0ae422d762bd3e6bc53db2b33769ea6be2d58",
    "hk_mins": "0b636568c837e073149a0459ffb26ac4c891b70ad5d7d5162a1e7bf8248fc822",
}

PERMISSION_HTML_SHA256 = (
    "765453b00496cdf9749a7d733c189766e3a2411d3ada03f3d96bb98c3c3ecb27"
)

INPUT_METADATA = {
    "stk_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "股票代码，e.g. 600000.SH",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2023-08-25 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2023-08-25 19:00:00",
        },
    },
    "etf_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "ETF代码，e.g. 159001.SZ",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2025-06-01 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2025-06-20 19:00:00",
        },
    },
    "idx_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "指数代码，e.g. 000001.SH",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2023-08-25 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2023-08-25 19:00:00",
        },
    },
    "sw_mins": {
        "ts_code": {"type": "str", "required": "Y", "description": "指数代码"},
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2023-08-25 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2023-08-25 19:00:00",
        },
    },
    "ft_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "股票代码，e.g.CU2310.SHF",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2023-08-25 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2023-08-25 19:00:00",
        },
    },
    "opt_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "股票代码，e.g：10007976.SH",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2024-08-25 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2024-08-25 19:00:00",
        },
    },
    "hk_mins": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "股票代码，e.g.00001.HK",
        },
        "freq": {
            "type": "str",
            "required": "Y",
            "description": "分钟频度（1min/5min/15min/30min/60min）",
        },
        "start_date": {
            "type": "datetime",
            "required": "N",
            "description": "开始日期 格式：2023-03-13 09:00:00",
        },
        "end_date": {
            "type": "datetime",
            "required": "N",
            "description": "结束时间 格式：2023-03-13 19:00:00",
        },
    },
}

FIELD_METADATA = {
    "stk_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价"},
        "close": {"type": "float", "default": "Y", "description": "收盘价"},
        "high": {"type": "float", "default": "Y", "description": "最高价"},
        "low": {"type": "float", "default": "Y", "description": "最低价"},
        "vol": {"type": "int", "default": "Y", "description": "成交量(股)"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额（元）"},
    },
    "etf_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "ETF代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价"},
        "close": {"type": "float", "default": "Y", "description": "收盘价"},
        "high": {"type": "float", "default": "Y", "description": "最高价"},
        "low": {"type": "float", "default": "Y", "description": "最低价"},
        "vol": {"type": "int", "default": "Y", "description": "成交量（股）"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额（元）"},
    },
    "idx_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "指数代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价"},
        "close": {"type": "float", "default": "Y", "description": "收盘价"},
        "high": {"type": "float", "default": "Y", "description": "最高价"},
        "low": {"type": "float", "default": "Y", "description": "最低价"},
        "vol": {"type": "int", "default": "Y", "description": "成交量(股)"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额（元）"},
    },
    "sw_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "指数代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘点数"},
        "close": {"type": "float", "default": "Y", "description": "收盘点数"},
        "high": {"type": "float", "default": "Y", "description": "最高点数"},
        "low": {"type": "float", "default": "Y", "description": "最低点数"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额（元）"},
        "vol": {"type": "float", "default": "Y", "description": "成交量（股）"},
    },
    "ft_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价（元）"},
        "close": {"type": "float", "default": "Y", "description": "收盘价（元）"},
        "high": {"type": "float", "default": "Y", "description": "最高价（元）"},
        "low": {"type": "float", "default": "Y", "description": "最低价（元）"},
        "vol": {"type": "int", "default": "Y", "description": "成交量（手）"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额（元）"},
        "oi": {"type": "float", "default": "Y", "description": "持仓量（手）"},
    },
    "opt_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价"},
        "close": {"type": "float", "default": "Y", "description": "收盘价"},
        "high": {"type": "float", "default": "Y", "description": "最高价"},
        "low": {"type": "float", "default": "Y", "description": "最低价"},
        "vol": {"type": "int", "default": "Y", "description": "成交量"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额"},
        "oi": {"type": "float", "default": "Y", "description": "持仓量"},
    },
    "hk_mins": {
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "trade_time": {"type": "str", "default": "Y", "description": "交易时间"},
        "open": {"type": "float", "default": "Y", "description": "开盘价"},
        "close": {"type": "float", "default": "Y", "description": "收盘价"},
        "high": {"type": "float", "default": "Y", "description": "最高价"},
        "low": {"type": "float", "default": "Y", "description": "最低价"},
        "vol": {"type": "int", "default": "Y", "description": "成交量"},
        "amount": {"type": "float", "default": "Y", "description": "成交金额"},
    },
}

FIELDS = {api: list(metadata) for api, metadata in FIELD_METADATA.items()}
INPUT_FIELDS = {api: list(metadata) for api, metadata in INPUT_METADATA.items()}
FREQUENCIES = ("1min", "5min", "15min", "30min", "60min")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

HISTORY_MINUTES_CONTRACTS = {}
for _api, _doc, _family, _namespace, _year in (
    ("stk_mins", 370, "minute_stocks", "CN", 2009),
    ("etf_mins", 387, "minute_etfs", "FUND", None),
    ("idx_mins", 419, "minute_indexes", "IDX", None),
    ("sw_mins", 469, "minute_sw_indexes", "SW", 2015),
    ("ft_mins", 313, "minute_futures", "FUT", 2010),
    ("opt_mins", 341, "minute_options", "OPT", 2010),
    ("hk_mins", 304, "minute_hk_stocks", "HK", None),
):
    spec = _contract(
        5000 if _api == "sw_mins" else 8000,
        ("ts_code", "trade_time"),
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in ("ts_code", "trade_time")],
        extra=FIELDS[_api],
        rpm=30,
    )
    spec.update(
        doc_id=_doc,
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        permission_source_url="https://tushare.pro/document/1?doc_id=290",
        permission_source_html_sha256=PERMISSION_HTML_SHA256,
        fields=FIELDS[_api],
        requested_fields=FIELDS[_api],
        hidden_fields=[],
        field_metadata=FIELD_METADATA[_api],
        input_metadata=INPUT_METADATA[_api],
        allowed_params=INPUT_FIELDS[_api],
        required_params=["ts_code", "freq"],
        request_identity_fields=["freq"],
        preserve_distinct_rows=True,
        identity_note="Business identity includes API/asset, original ts_code, full trade_time and immutable requested freq. freq is not a documented output column: store request identity without overwriting future source freq. Preserve distinct revisions, original timestamps and source codes; do not dedupe bars by date or infer freq from timestamp spacing.",
        frequencies=list(FREQUENCIES),
        dependencies=[_family],
        source_namespace=_namespace,
        date_field="trade_time",
        split_axis="trade_time",
        split={
            "start_param": "start_date",
            "end_param": "end_date",
            "precision": "second",
        },
        permission_status="unprobed",
        minimum_points=120 if _api == "hk_mins" else None,
        independent_permission="Each historical-minute entitlement must be independently verified; points and purchased text permissions do not authorize minutes.",
        documented_trial_requests=2 if _api == "hk_mins" else None,
        documented_requests_per_minute=500
        if _api in ("stk_mins", "ft_mins", "opt_mins", "sw_mins")
        else None,
        documented_daily_requests=None,
        advertised_price_cny_per_year=2000
        if _api in ("stk_mins", "ft_mins", "opt_mins", "sw_mins")
        else None,
        advertised_total_limit="not_limited"
        if _api in ("ft_mins", "opt_mins", "sw_mins")
        else None,
        advertised_history_year=_year,
        history_bound_verified=False,
        permission_gap="Linked permission table explicitly excludes minutes from point-based tiers and separates permissions. Quoted500rpm is a product description, not measured current rights or an account-wide budget. Local30rpm is conservative; exact asset/frequency/trial/daily entitlements remain unprobed.",
        history_gap="Pages and linked table only advertise years or more-than10years, not an exact earliest timestamp per code/frequency. Examples are not bounds. Explicit history_start is requested scope only; expired instruments, delisted listings and discontinued classifications must remain discoverable.",
        discovery_gap="Only actual source records in the declared asset family may seed requests. Current masters are not complete historical universes. Keep historical/T/HK reuse markers, expired contracts and source-observed identifiers; do not generate demo codes or reuse a stock list for every market.",
        time_gap="Source timestamps have no declared timezone/UTC offset, exchange trading-date assignment or inclusive/exclusive range semantics. Preserve wall-clock spelling and full cross-midnight time; never infer session start/end, midnight trading-day rollover, holiday closure, or whether bars label their open/close.",
        frequency_gap="All five documented frequencies are planned independently by default; no auto-resampling can establish supplier equivalence. Unknown returned frequencies/fields must be retained and audited, not aliased to a known frequency or silently dropped. Configured frequency subsets are explicit scope gaps.",
        pagination_gap="Only code/freq/start_date/end_date are documented. No limit/offset/page/trade_date/adj/exchange input; reject invented pagination. Datetime strings follow YYYY-MM-DD HH:MM:SS, not daily YYYYMMDD query parameters.",
        saturation_gap="At row cap or has_more, bisect only the exact timestamp range while retaining ts_code/freq. Endpoint semantics require actual overlap/filter verification. A one-code/freq/second saturated result has no documented finer filter and remains blocked; fewer-than-cap alone does not certify coverage.",
        refresh_gap="Recent7 completed wall-clock dates are a finite overlap, not proof of settled bars or old-revision completeness. No current-day real-time polling is introduced. Late data, retractions and bars dated at a boundary require later audited reconciliation.",
        pit_gap="Observed_at is collection evidence only. Minute-bar adjustment, revisions, lookahead, roll methodology, corporate actions and first availability are unverified; this is not research or live-trading readiness.",
        field_selection_note="Request every known column explicitly (all defaultY), require column presence, retain optional scalar nulls and unexpected columns without rescaling. Sample float-looking volumes must not be truncated because metadata says int.",
        field_gaps={
            f: ["actual_presence_and_type_unprobed", "revision_availability_unverified"]
            for f in FIELDS[_api]
        },
    )
    HISTORY_MINUTES_CONTRACTS[_api] = spec

HISTORY_MINUTES_CONTRACTS["stk_mins"]["unit_note"] = (
    "vol is shares and amount yuan. OHLC adjustment is unspecified and there is no adj input; do not assume compatibility with adjusted daily prices."
)
HISTORY_MINUTES_CONTRACTS["etf_mins"].update(
    unit_note="ETF vol is documented 股, amount yuan; do not silently convert to lots or fund units. OHLC adjustment and split/dividend treatment are unspecified.",
    product_mapping_gap="ETF endpoint advertises more-than10years, but permission table has no explicit ETF row. Do not assume the generic2009 history/price/500rpm bundle grants ETFs.",
)
HISTORY_MINUTES_CONTRACTS["idx_mins"].update(
    unit_note="Exchange index endpoint labels vol shares and amount yuan but does not explain aggregate constituents or index-price scaling. Keep source numbers; do not infer a tradeable security.",
    product_mapping_gap="Exchange indices are a separate endpoint; mapping to generic historical-minute subscription/year/price is not explicit. Do not add SW/CSI/global indices from unrelated masters without verified source scope.",
)
HISTORY_MINUTES_CONTRACTS["sw_mins"].update(
    unit_note="OHLC are index points, amount yuan and vol float shares. Output field order has amount before vol, unlike the other six APIs.",
    cap_conflict_gap="Endpoint469 says5000 rows; general permission table290 says8000 forSW minutes. Use the conservative5000 cap until an actual probe resolves this discrepancy.2015 is only advertised year, not a proven timestamp.",
)
HISTORY_MINUTES_CONTRACTS["ft_mins"].update(
    unit_note="OHLC/amount documented yuan; vol and oi contracts/lots(手). Preserve code-specific multiplier, quotation units and settlement conventions as unknown; no adjustment or currency conversion.",
    mapping_gap="Endpoint requires a real futures contract. To request a main contract, official page requires dated fut_mapping first (at least2000points for mapping, separately from minutes). Do not manufacture a continuous symbol or use current main mapping for past dates. Product night sessions and weekend rollover do not follow stock calendars.",
    documentation_gap="Input/output descriptions incorrectly say stock code, while endpoint and CU2310.SHF sample are futures; preserve futures namespace. Permission table advertises2010 and500rpm without proving current entitlement.",
)
HISTORY_MINUTES_CONTRACTS["opt_mins"].update(
    unit_note="Option OHLC/vol/amount/oi units are not specified on this endpoint. Do not inherit futures multipliers or stock-share/yuan units; option venue/product contract metadata needs audit.",
    documentation_gap="Input/output text says stock code but endpoint covers options; sample10007976.SH is an option. Sample trade_time uses ISO T, unlike spaced request format; preserve source spelling. Permission table includes stock-index and commodity options but does not prove every option venue/expired contract exists.",
)
HISTORY_MINUTES_CONTRACTS["hk_mins"].update(
    unit_note="HK OHLC currency and vol/amount units are unspecified here; no implicit HKD or lot conversion. Sample includes16:10, so stock-session assumptions would lose bars.",
    product_mapping_gap="Page offers120-point two-call trial but no dedicatedHK-minute row in permission table establishes full price/start/frequency. Actual remaining trial and formal rights are unknown; never spend a presumed trial automatically.",
)


def _settings(config):
    selected = config.get("history_minutes_apis", tuple(HISTORY_MINUTES_CONTRACTS))
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(a, str) or a not in HISTORY_MINUTES_CONTRACTS for a in selected
    ):
        raise ValueError("history_minutes_apis must list known APIs")
    selected = tuple(dict.fromkeys(selected))
    frequencies = config.get("history_minutes_frequencies", FREQUENCIES)
    if not isinstance(frequencies, (list, tuple)) or any(
        not isinstance(f, str) or f not in FREQUENCIES for f in frequencies
    ):
        raise ValueError("history_minutes_frequencies must use exact documented values")
    return selected, tuple(dict.fromkeys(frequencies))


def _starts(config, enabled):
    setting = config.get("history_minutes_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "history_minutes_history_start must be a date/time or API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - HISTORY_MINUTES_CONTRACTS.keys():
        raise ValueError("Unknown minute history API")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        if value is None:
            starts[api] = None
        elif isinstance(value, str) and re.fullmatch(r"\d{8}", value):
            starts[api] = datetime.combine(_parse(value), time())
        elif isinstance(value, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value
        ):
            starts[api] = datetime.strptime(value, TIME_FORMAT)
        else:
            raise ValueError(
                "Minute history scope requires YYYYMMDD or YYYY-MM-DD HH:MM:SS without inferred timezone"
            )
    return starts


def _codes(identifiers, family):
    """Opaque supplier identities retain hyphens/! and case; no active-only filter."""
    rows = (identifiers or {}).get(family, ())
    if not isinstance(rows, (list, tuple)):
        raise ValueError("Minute discovery must be source records or code strings")
    codes = []
    for row in rows:
        code = (
            row.get("ts_code") or row.get("index_code")
            if isinstance(row, dict)
            else row
        )
        # Unlike the legacy daily helper, options may contain hyphens and HK
        # delisted/reused symbols include ! suffix markers. No prefix conversion.
        if not isinstance(code, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_!\-]*\.[A-Z]+", code
        ):
            raise ValueError("Invalid minute supplier identifier in " + family)
        codes.append(code)
    return sorted(set(codes))


def history_minutes_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["history_minutes_apis"] = enabled_apis
    enabled, frequencies = _settings(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = HISTORY_MINUTES_CONTRACTS[api]
        family = spec["dependencies"][0]
        codes = _codes(identifiers, family)
        gaps.extend(
            {"api_name": api, "dependencies": [], "reason": k, "detail": v}
            for k, v in spec.items()
            if k.endswith("_gap")
        )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [family],
                "reason": "historical_minute_universe_unverified"
                if codes
                else "missing_source_identifiers",
                "observed_codes": len(codes),
                "universe_complete": False,
            }
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
        if set(frequencies) != set(FREQUENCIES):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "frequency_subset_scope",
                    "included": list(frequencies),
                    "excluded": [f for f in FREQUENCIES if f not in frequencies],
                }
            )
    return gaps


def _windows(begin, end):
    """At most one wall-clock date per request, with shared midnight endpoints."""
    while begin < end:
        right = min(end, datetime.combine(begin.date() + timedelta(days=1), time()))
        yield begin.strftime(TIME_FORMAT), right.strftime(TIME_FORMAT)
        begin = right


def _partitions(begin, end, codes, frequencies):
    for left, right in _windows(begin, end):
        for code in codes:
            for freq in frequencies:
                yield {
                    "ts_code": code,
                    "freq": freq,
                    "start_date": left,
                    "end_date": right,
                }


def iter_history_minutes_jobs(config, today, identifiers=None):
    """Lazy recent7 completed wall dates followed by explicit scoped history.

    today is a caller-provided wall-date anchor, NOT a timezone conversion.
    Shared boundary timestamps require immutable freq identity and later actual
    source endpoint verification; no current-day intraday request is generated.
    """
    if isinstance(today, datetime):
        if today.tzinfo is not None:
            raise ValueError("Do not infer source timezone from aware today")
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a wall-date anchor")
    enabled, frequencies = _settings(config)
    starts = _starts(config, enabled)
    end = datetime.combine(today, time())
    if any(value and value > end for value in starts.values()):
        raise ValueError("Minute history cannot begin after completed-date boundary")
    recent = end - timedelta(days=7)
    codes = {
        api: _codes(identifiers, HISTORY_MINUTES_CONTRACTS[api]["dependencies"][0])
        for api in enabled
    }
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            start = starts[api]
            if not codes[api] or not frequencies:
                continue
            if history:
                if not start or start >= recent:
                    continue
                begin, right = start, recent
            else:
                begin, right = max(start or recent, recent), end
            streams[api] = iter(_partitions(begin, right, codes[api], frequencies))
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
