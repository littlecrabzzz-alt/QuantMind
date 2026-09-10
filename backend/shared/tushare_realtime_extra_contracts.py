"""Pure realtime snapshots plus stk_auction's explicitly documented history.

Reuse existing rt_k/rt_etf_k contracts and request helpers without modifying their
legacy exports. No I/O, credentials, registration, live scheduling or activation.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
from itertools import zip_longest
import re

from backend.shared.tushare_discovered_contracts import (
    DISCOVERED_CONTRACTS,
    _epoch,
    _requests as discovered_requests,
)
from backend.shared.tushare_history_minutes_contracts import _codes
from backend.shared.tushare_market_contracts import _months
from backend.shared.tushare_structured_contracts import _contract, _parse

DOC_IDS = {
    "stk_auction": 369,
    "rt_etf_sz_iopv": 454,
    "rt_idx_k": 403,
    "rt_idx_min": 420,
    "rt_sw_k": 417,
    "rt_fut_min": 340,
    "rt_min": 374,
    "rt_etf_min": 416,
    "rt_k": 372,
    "rt_etf_k": 400,
}

SOURCE_HTML_SHA256 = {
    "stk_auction": "1569d43c483eeccfa03c7ed705493bccd519767273ff90088f08997eb48f2a7f",
    "rt_etf_sz_iopv": "041a3656de6dc016e72c02ae8de7cbd0dbec8391a1858722994af3c10add1790",
    "rt_idx_k": "7199e8b081500db5e789561c04192f2c31a78c71d5f7f3596e989825e772cf26",
    "rt_idx_min": "a6eb3ee102aa6a8446776137b15158b507ed7aa7d8d75badb8cff4da423ed879",
    "rt_sw_k": "4cb7963c01b5592ce0e62c40baa504f35933cc0d76957e6fb1b0255de48c0399",
    "rt_fut_min": "5f5012e5b93f067a93a2c82b38bd81e92194a18606b47a930fef63e79a882bb7",
    "rt_min": "1ab1e6dfafee4a4ed07ee15605d449da284fef97f23e3f35742279d6f7bab320",
    "rt_etf_min": "3f6791db049cc20ec38cf237cac20c508e42936b0e07f34ae29d6d3a0539e13b",
    "rt_k": "58905ec12e31c14a168bb781892ee3c89547d879252ac9ebbaad1062bb755912",
    "rt_etf_k": "4395c969142c0818405e4ce17fea6a1bbefde370a287edfa52c05253b5e5c478",
}

SOURCE_MARKDOWN_SHA256 = {
    "rt_min": "ea569c9d205870e80b04f6ef36f593be4fe0692be7e1a0c0e8d697e6e9434ac9",
    "rt_etf_min": "4e43c99f218a86820f5f03563494701ff961a517036272796531ec89f505a538",
}

_INPUT_ROWS = {
    "stk_auction": [
        ("ts_code", "str", "N", "股票代码"),
        ("trade_date", "str", "N", "交易日期（YYYYMMDD格式，下同)"),
        ("start_date", "str", "N", "开始日期"),
        ("end_date", "str", "N", "结束日期"),
        ("ts_type", "str", "N", "类型（股票STK, ETF用ETF）"),
    ],
    "rt_etf_sz_iopv": [
        (
            "ts_code",
            "str",
            "N",
            "ETF代码（默认为空，即一次全市场。支持单个和多个ETF过滤提取）",
        )
    ],
    "rt_idx_k": [
        (
            "ts_code",
            "str",
            "Y",
            "指数代码，支持通配符方式，e.g. 0*.SH、3*.SZ、000001.SH",
        )
    ],
    "rt_idx_min": [
        ("freq", "str", "Y", "1MIN,5MIN,15MIN,30MIN,60MIN （大写）"),
        ("ts_code", "str", "Y", "支持单个和多个：000001.SH 或者 000001.SH,399300.SZ"),
    ],
    "rt_sw_k": [
        (
            "ts_code",
            "str",
            "N",
            "指数代码，如: 801005.SI；可以是逗号隔开的多个，如: 801005.SI,801001.SI",
        )
    ],
    "rt_fut_min": [
        ("ts_code", "str", "Y", "股票代码，e.g.CU2310.SHF，支持多个合约（逗号分隔）"),
        ("freq", "str", "Y", "分钟频度（1MIN/5MIN/15MIN/30MIN/60MIN）"),
    ],
    "rt_min": [
        ("freq", "str", "Y", "1MIN,5MIN,15MIN,30MIN,60MIN （大写）"),
        ("ts_code", "str", "Y", "支持一个或逗号分隔的多个A股代码"),
    ],
    "rt_etf_min": [
        ("freq", "str", "Y", "1MIN,5MIN,15MIN,30MIN,60MIN （大写）"),
        ("ts_code", "str", "Y", "支持一个或逗号分隔的多个ETF代码"),
    ],
    "rt_k": [
        (
            "ts_code",
            "str",
            "Y",
            "支持通配符方式，e.g. 所有上交所股票：6*.SH、所有创业板股票3*.SZ、所有科创板股票688*.SH，或单个股票600000.SH",
        )
    ],
    "rt_etf_k": [
        ("ts_code", "str", "Y", "支持通配符方式，e.g. 5*.SH、15*.SZ、159101.SZ"),
        (
            "topic",
            "str",
            "Y",
            "分类参数，取上海ETF时，需要输入'HQ_FND_TICK'，参考下面例子",
        ),
    ],
}

_FIELD_ROWS = {
    "stk_auction": [
        ("ts_code", "str", "Y", "股票代码"),
        ("trade_date", "str", "Y", "数据日期"),
        ("vol", "int", "Y", "成交量（股）"),
        ("price", "int", "Y", "成交均价（元）"),
        ("amount", "float", "Y", "成交金额（元）"),
        ("pre_close", "float", "Y", "昨收价（元）"),
        ("turnover_rate", "float", "Y", "换手率（%）"),
        ("volume_ratio", "float", "Y", "量比"),
        ("float_share", "float", "Y", "流通股本（万股）"),
    ],
    "rt_etf_sz_iopv": [
        ("trade_time", "datetime", "Y", "交易时间"),
        ("ts_code", "str", "Y", "ETF代码"),
        ("vol", "float", "Y", "成交量（份）"),
        ("num", "int", "Y", "成交笔数"),
        ("amount", "float", "Y", "成交金额（元）"),
        ("price", "float", "Y", "最新价（元）"),
        ("iopv", "float", "Y", "最近参考净值"),
        ("pre_iopv", "float", "Y", "前一日参考净值"),
        ("buy_num", "int", "Y", "申购笔数"),
        ("buy_vol", "float", "Y", "申购买量(份)"),
        ("sell_num", "int", "Y", "赎回笔数"),
        ("sell_vol", "float", "Y", "赎回买量（份）"),
    ],
    "rt_idx_k": [
        ("ts_code", "str", "Y", "指数代码"),
        ("name", "str", "Y", "指数名称"),
        ("trade_time", "str", "Y", "交易时间"),
        ("close", "float", "Y", "现价"),
        ("pre_close", "float", "Y", "昨收"),
        ("high", "float", "Y", "最高价"),
        ("open", "float", "Y", "开盘价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "float", "Y", "成交量"),
        ("amount", "float", "Y", "成交金额（元）"),
    ],
    "rt_idx_min": [
        ("ts_code", "str", "Y", "股票代码"),
        ("time", "None", "Y", "交易时间"),
        ("open", "float", "Y", "开盘价"),
        ("close", "float", "Y", "收盘价"),
        ("high", "float", "Y", "最高价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "float", "Y", "成交量(股）"),
        ("amount", "float", "Y", "成交额（元）"),
    ],
    "rt_sw_k": [
        ("ts_code", "str", "Y", "指数代码"),
        ("name", "str", "Y", "指数名称"),
        ("trade_time", "str", "Y", "交易时间"),
        ("close", "float", "Y", "现价"),
        ("pre_close", "float", "Y", "昨收"),
        ("high", "float", "Y", "最高价"),
        ("open", "float", "Y", "开盘价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "float", "Y", "成交量（股）"),
        ("amount", "float", "Y", "成交金额（元）"),
    ],
    "rt_fut_min": [
        ("code", "str", "Y", "股票代码"),
        ("freq", "str", "Y", "频度"),
        ("time", "str", "Y", "交易时间"),
        ("open", "float", "Y", "开盘价"),
        ("close", "float", "Y", "收盘价"),
        ("high", "float", "Y", "最高价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "int", "Y", "成交量"),
        ("amount", "float", "Y", "成交金额"),
        ("oi", "float", "Y", "持仓量"),
    ],
    "rt_min": [
        ("ts_code", "str", "Y", "股票代码"),
        ("time", "str", "Y", "交易时间"),
        ("open", "float", "Y", "开盘价"),
        ("close", "float", "Y", "收盘价"),
        ("high", "float", "Y", "最高价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "float", "Y", "成交量(股）"),
        ("amount", "float", "Y", "成交额（元）"),
    ],
    "rt_etf_min": [
        ("ts_code", "str", "Y", "股票代码"),
        ("time", "None", "Y", "交易时间"),
        ("open", "float", "Y", "开盘价"),
        ("close", "float", "Y", "收盘价"),
        ("high", "float", "Y", "最高价"),
        ("low", "float", "Y", "最低价"),
        ("vol", "float", "Y", "成交量(股）"),
        ("amount", "float", "Y", "成交额（元）"),
    ],
    "rt_k": [
        ("ts_code", "str", "Y", "股票代码"),
        ("name", "None", "Y", "股票名称"),
        ("pre_close", "float", "Y", "昨收价"),
        ("high", "float", "Y", "最高价"),
        ("open", "float", "Y", "开盘价"),
        ("low", "float", "Y", "最低价"),
        ("close", "float", "Y", "收盘价（最新价）"),
        ("vol", "int", "Y", "成交量（股）"),
        ("amount", "int", "Y", "成交金额（元）"),
        ("num", "int", "Y", "开盘以来成交笔数"),
        ("ask_price1", "float", "N", "委托卖盘（元）"),
        ("ask_volume1", "int", "N", "委托卖盘（股）"),
        ("bid_price1", "float", "N", "委托买盘（元）"),
        ("bid_volume1", "int", "N", "委托买盘（股）"),
        ("trade_time", "str", "N", "交易时间"),
    ],
    "rt_etf_k": [
        ("ts_code", "str", "Y", "ETF代码"),
        ("name", "None", "Y", "ETF名称"),
        ("pre_close", "float", "Y", "昨收价（元）"),
        ("high", "float", "Y", "最高价（元）"),
        ("open", "float", "Y", "开盘价（元）"),
        ("low", "float", "Y", "最低价（元）"),
        ("close", "float", "Y", "收盘价（最新价）"),
        ("vol", "int", "Y", "成交量（股）"),
        ("amount", "int", "Y", "成交金额（元）"),
        ("num", "int", "Y", "开盘以来成交笔数"),
        ("ask_volume1", "int", "N", "委托卖盘（股）"),
        ("bid_volume1", "int", "N", "委托买盘（股）"),
        ("trade_time", "str", "N", "交易时间"),
    ],
}

INPUT_METADATA = {
    api: {
        f: {"type": t, "required": required, "description": desc}
        for f, t, required, desc in rows
    }
    for api, rows in _INPUT_ROWS.items()
}
FIELD_METADATA = {
    api: {
        f: {"type": t, "default": shown, "description": desc}
        for f, t, shown, desc in rows
    }
    for api, rows in _FIELD_ROWS.items()
}
FIELDS = {api: list(meta) for api, meta in FIELD_METADATA.items()}
INPUT_FIELDS = {api: list(meta) for api, meta in INPUT_METADATA.items()}
FREQUENCIES = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
MINUTE_APIS = ("rt_idx_min", "rt_fut_min", "rt_min", "rt_etf_min")
SOURCE_FAMILIES = {
    "rt_k": "stocks",
    "rt_etf_k": "etfs",
    "rt_etf_sz_iopv": "etfs",
    "rt_idx_k": "indexes",
    "rt_idx_min": "indexes",
    "rt_sw_k": "sw_indexes",
    "rt_fut_min": "minute_futures",
    "rt_min": "stocks",
    "rt_etf_min": "etfs",
}
CODE_PATTERNS = {
    "stocks": r"T?[0-9]{6}\.(SH|SZ|BJ)",
    "etfs": r"[0-9]{6}\.(SH|SZ|BJ)",
    "indexes": r"[0-9]{6}\.(SH|SZ)",
    "sw_indexes": r"[0-9]{6}\.SI",
    "minute_futures": r"[A-Za-z]+[0-9]{3,4}\.(SHF|DCE|ZCE|CZC|CFX|INE|GFE)",
}
REALTIME_EXTRA_CONTRACTS = {}
for _api, _guard, _cap in (
    ("stk_auction", 8000, 8000),
    ("rt_etf_sz_iopv", 5000, 5000),
    ("rt_idx_k", 1000, None),
    ("rt_idx_min", 1000, 1000),
    ("rt_sw_k", 1000, None),
    ("rt_fut_min", 1000, None),
    ("rt_min", 1000, 1000),
    ("rt_etf_min", 1000, 1000),
    ("rt_k", 6000, 6000),
    ("rt_etf_k", 1000, None),
):
    _code = "code" if _api == "rt_fut_min" else "ts_code"
    _axis = (
        "trade_date"
        if _api == "stk_auction"
        else "time"
        if _api in MINUTE_APIS
        else "trade_time"
    )
    _keys = [_code, _axis, "_observation"]
    if _api in MINUTE_APIS:
        _keys.append("_request_identity")
    if _api in ("stk_auction", "rt_etf_k"):
        _keys.append("_request_identity")
    _spec = (
        deepcopy(DISCOVERED_CONTRACTS[_api])
        if _api in DISCOVERED_CONTRACTS
        else _contract(
            _guard,
            _keys,
            split=_api == "stk_auction",
            rpm=30,
            cap_verified=False,
        )
    )
    _spec.update(
        group="realtime_extra",
        default_enabled=False,
        doc_id=DOC_IDS[_api],
        source_url=f"https://tushare.pro/document/2?doc_id={DOC_IDS[_api]}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        fields=FIELDS[_api],
        requested_fields=FIELDS[_api],
        required_fields=FIELDS[_api],
        nullable_fields=[f for f in FIELDS[_api] if f != _code],
        positive_fields=[],
        extra_fields=FIELDS[_api],
        keys=_keys,
        allowed_params=INPUT_FIELDS[_api],
        required_params=[
            f for f, m in INPUT_METADATA[_api].items() if m["required"] == "Y"
        ],
        input_metadata=INPUT_METADATA[_api],
        field_metadata=FIELD_METADATA[_api],
        hidden_fields=[
            f for f, m in FIELD_METADATA[_api].items() if m["default"] == "N"
        ],
        documented_row_cap=_cap,
        row_cap_verified=False,
        requests_per_minute=30,
        documented_requests_per_minute=500 if _api == "rt_fut_min" else None,
        documented_daily_requests=None,
        minimum_points=None,
        independent_permission=True,
        permission_status="unprobed",
        pagination=None,
        history_bound_verified=False,
        acquisition_mode="auction_daily_and_history"
        if _api == "stk_auction"
        else "realtime_snapshot",
        date_field=_axis,
        source_code_field=_code,
        preserve_distinct_rows=True,
        generated_identity_fields=[k for k in _keys if k.startswith("_")],
        request_identity_fields=["freq"]
        if _api in MINUTE_APIS
        else ["ts_type"]
        if _api == "stk_auction"
        else ["topic"]
        if _api == "rt_etf_k"
        else [],
        dependencies=[SOURCE_FAMILIES[_api]]
        if _api
        in ("rt_k", "rt_idx_k", "rt_idx_min", "rt_fut_min", "rt_min", "rt_etf_min")
        else [],
        permission_gap="Independent realtime rights remain unprobed. 10100 points and purchased news/report rights do not grant access. Local30rpm and documented limits are not measured account quota.",
        history_gap="No historical date/range input: old unobserved snapshots cannot be reconstructed or backfilled from this endpoint.",
        timing_gap="Planned UTC epoch is only idempotence identity, never observed_at or source timestamp. Runtime must refuse expired plans and capture actual request/response times. No source timezone, session boundaries, bar open/close label, final-close state, publication lag or PIT guarantee is established.",
        saturation_gap="No pagination or automatic timeframe replay. At cap/has_more use only legal source-code filtering and verified discovery; missing universe or single-code saturation remains a gap. A below-cap reply is not completeness proof, even where the page claims current-market coverage.",
        field_selection_note="Explicitly request all known columns including defaultN; retain additional supplier fields and null/zero/decimal values. Metadata types are descriptions, not coercion rules. Missing nullable columns still fail presence validation.",
        namespace_gap="Keep original code and request asset context. Never classify source identifiers solely by SH/SZ suffix or route indexes/funds/futures into the A-share stock namespace.",
        field_gaps={
            f: ["actual_presence_type_units_unprobed", "source_time_pit_unverified"]
            for f in FIELDS[_api]
        },
    )
    REALTIME_EXTRA_CONTRACTS[_api] = _spec

for _api, _sha256 in SOURCE_MARKDOWN_SHA256.items():
    REALTIME_EXTRA_CONTRACTS[_api].update(
        source_markdown_url=(
            f"https://tushare.pro/wctapi/documents/{DOC_IDS[_api]}.md"
        ),
        source_markdown_sha256=_sha256,
    )

REALTIME_EXTRA_CONTRACTS["stk_auction"].update(
    documented_history_start_month="202501",
    exact_date_param="trade_date",
    documented_availability_window="09:26-09:29; source timezone not explicitly stated",
    request_variants=[{}, {"ts_type": "STK"}, {"ts_type": "ETF"}],
    history_gap="Page369 now explicitly supports historical requests from202501 (month precision). 20250101 is a request boundary, not a verified first row. Do not substitute APIs353/354 or infer complete coverage/cessation from a sample.",
    timing_gap="Auction data becomes available during09:26-09:29 according to page369; raw trade_date is the data date, not actual observation/publication time. Historical revisions/knowledge time remain unknown. Planner does not guess exchange holidays or fabricate observation timestamps.",
    saturation_gap="Legal trade_date/start_date/end_date and ts_type allow date bisection, then separately observed STK/ETF codes. Unfiltered output includes123039.SZ in the official sample, so untyped remainder and historical asset discovery remain incomplete. A single-code/day/type cap has no finer documented dimension.",
    namespace_gap="Unfiltered sample mixes equities, ETFs and a convertible-bond-shaped123039.SZ. Preserve source and request ts_type; infer actual asset only from verified master membership. STK/ETF are input filters, not proof that unfiltered output has only two asset classes.",
    type_gap="price is documented int but official sample includes23.240 and1.211; preserve decimals. ETF turnover_rate/volume_ratio samples are NaN. Numeric volumes are shares, amount/price yuan, float_share ten-thousand shares, turnover_rate percent.",
)
REALTIME_EXTRA_CONTRACTS["rt_etf_sz_iopv"].update(
    target_namespace="FUND:",
    unit_gap="vol is shares/units(份); buy_vol/sell_vol are declared份 but fractional sample magnitudes need validation. Preserve IOPV zeros and do not treat0 as a valid arbitrage NAV; no unit or scale correction is authorized.",
    source_scope_note="Shenzhen only; all-market blank ts_code is documented. Do not extend this endpoint to Shanghai using guessed topic/venue parameters.",
)
for _api in ("rt_idx_k", "rt_idx_min", "rt_sw_k"):
    REALTIME_EXTRA_CONTRACTS[_api]["target_namespace"] = "IDX:"
REALTIME_EXTRA_CONTRACTS["rt_idx_k"]["unit_gap"] = (
    "vol units are unspecified; amount is yuan. Index OHLC units and aggregate construction are not trading-security prices or verified constituent PIT."
)
REALTIME_EXTRA_CONTRACTS["rt_idx_min"].update(
    frequencies=list(FREQUENCIES),
    frequency_gap="Uppercase1MIN/5MIN/15MIN/30MIN/60MIN are independent request identities. Output omits freq; persist freq in existing _request_identity JSON without pretending it was supplied. time type is documented None; retain actual spelling/type until verified.",
)
REALTIME_EXTRA_CONTRACTS["rt_sw_k"].update(
    schema_note="Official417 update20260908 removed pct_change. Request the current10 columns; retain it as an unknown field if provider still sends it, do not require/fabricate it.",
)
REALTIME_EXTRA_CONTRACTS["rt_fut_min"].update(
    target_namespace="FUT:",
    frequencies=list(FREQUENCIES),
    frequency_gap="All five uppercase frequencies are independent identities. Preserve source output freq/code/time and request freq/ts_code; mismatches remain validation gaps, not aliases.",
    mapping_gap="Requires actual futures contract codes. Official main-contract guidance requires dated fut_mapping; continuous/product/expired discovery cannot be rewritten into a guessed live contract. Preserve case and source code, do not impose stock sessions on night trading.",
    unit_gap="Endpoint340 gives no contract/currency units or multiplier for OHLC,vol,amount,oi. Descriptions wrongly say stock code; source output is code, not ts_code. Preserve raw numbers, no stock-share conversion.",
    catalog_gap="Saved catalog340 merges date_str from separately headed rt_fut_min_daily input table. rt_fut_min accepts only ts_code/freq; do not pass date_str. Catalog correction belongs to later integration.",
)
REALTIME_EXTRA_CONTRACTS["rt_min"].update(
    target_namespace="equity_prefix_from_verified_stock_context",
    frequencies=list(FREQUENCIES),
    frequency_gap="All five uppercase frequencies are separate request identities. The source time has no documented timezone, bar-label convention or finality; never treat a captured bar as known earlier.",
    unit_gap="vol is documented in shares and amount in CNY. Prices and volumes are retained exactly; no missing bar, zero or null may be filled or converted into suspension evidence.",
)
REALTIME_EXTRA_CONTRACTS["rt_etf_min"].update(
    target_namespace="FUND:",
    frequencies=list(FREQUENCIES),
    frequency_gap="All five uppercase frequencies are separate request identities. The source time type is documented None; preserve the actual value and do not invent timezone or bar-finality semantics.",
    unit_gap="The page labels vol as shares and amount as CNY, but ETF unit conventions are not independently verified. Preserve source values without stock-share or NAV conversion.",
)
REALTIME_EXTRA_CONTRACTS["rt_k"]["target_namespace"] = (
    "equity_prefix_from_verified_stock_context"
)
REALTIME_EXTRA_CONTRACTS["rt_etf_k"]["target_namespace"] = "FUND:"

ADJACENT_API_OBLIGATIONS = {
    "rt_idx_min_daily": {
        "doc_id": 420,
        "source_html_sha256": SOURCE_HTML_SHA256["rt_idx_min"],
        "named_api_evidence": "Page420 explicitly names rt_idx_min_daily and calls it with ts_code='399300.SZ',freq='1MIN'.",
        "allowed_params": ["ts_code", "freq"],
        "frequencies": list(FREQUENCIES),
        "scope": "One actual index at a time, current opening-to-now minutes; no date input documented.",
        "gap": "Separate API entitlement/cap/field equivalence and exact current-day timing unprobed; not an alias call to rt_idx_min and not in this eight-API planner.",
    },
    "rt_fut_min_daily": {
        "doc_id": 340,
        "source_html_sha256": SOURCE_HTML_SHA256["rt_fut_min"],
        "named_api_evidence": "Page340 separately names rt_fut_min_daily with its own three-row input table.",
        "allowed_params": ["ts_code", "freq", "date_str"],
        "required_params": ["ts_code", "freq"],
        "frequencies": list(FREQUENCIES),
        "scope": "One actual futures contract; date_str YYYY-MM-DD optional, trading day by default, at most one day lookback advertised. Night-session/date boundary undefined.",
        "gap": "Independent named API; do not invent general history or leak date_str into rt_fut_min. Rights/cap and exact prior-trading-day vs calendar-day meaning remain unprobed.",
    },
}


def _settings(config):
    active = config.get("enable_realtime_extra", False)
    if not isinstance(active, bool):
        raise ValueError("enable_realtime_extra must be boolean")
    selected = config.get("realtime_extra_apis", tuple(REALTIME_EXTRA_CONTRACTS))
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(a, str) or a not in REALTIME_EXTRA_CONTRACTS for a in selected
    ):
        raise ValueError("realtime_extra_apis must list only the reviewed eight APIs")
    frequencies = config.get("realtime_extra_frequencies", FREQUENCIES)
    if not isinstance(frequencies, (list, tuple)) or any(
        f not in FREQUENCIES for f in frequencies
    ):
        raise ValueError("Exact uppercase realtime minute frequencies required")
    return tuple(dict.fromkeys(selected)) if active else (), tuple(
        dict.fromkeys(frequencies)
    )


def _source_codes(api, identifiers):
    family = SOURCE_FAMILIES[api]
    observed = _codes(identifiers, family)
    valid = [c for c in observed if re.fullmatch(CODE_PATTERNS[family], c)]
    if api == "rt_fut_min":
        valid = [c for c in valid if not c.split(".")[0].endswith(("8888", "9999"))]
    if api == "rt_etf_sz_iopv":
        valid = [c for c in valid if c.endswith(".SZ")]
    return valid, sorted(set(observed) - set(valid))


def _auction_start(config):
    value = config.get(
        "realtime_extra_history_start", config.get("history_start", "20250101")
    )
    if isinstance(value, dict):
        if value.keys() - {"stk_auction"}:
            raise ValueError("Only stk_auction accepts historical scope")
        value = value.get("stk_auction", config.get("history_start", "20250101"))
    return _parse(value)


def _snapshot_requests(api, identifiers, frequencies):
    codes, _ = _source_codes(api, identifiers)
    if api in DISCOVERED_CONTRACTS:
        yield from discovered_requests(api, codes)
    elif api in ("rt_etf_sz_iopv", "rt_sw_k"):
        yield {}  # Explicitly documented whole-market call; no invented filters.
    elif api in MINUTE_APIS:
        for code in codes:
            for freq in frequencies:
                yield {"ts_code": code, "freq": freq}
    else:
        for code in codes:
            yield {"ts_code": code}


def realtime_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["realtime_extra_apis"] = enabled_apis
    enabled, frequencies = _settings(config)
    gaps = []
    for api in enabled:
        spec = REALTIME_EXTRA_CONTRACTS[api]
        gaps.extend(
            {"api_name": api, "reason": k, "detail": v, "dependencies": []}
            for k, v in spec.items()
            if k.endswith("_gap")
        )
        if api == "stk_auction":
            gaps.append(
                {
                    "api_name": api,
                    "reason": "configured_history_not_verified_complete",
                    "request_history_start": _auction_start(config).strftime("%Y%m%d"),
                    "dependencies": [],
                }
            )
        else:
            codes, unsupported = _source_codes(api, identifiers)
            gaps.append(
                {
                    "api_name": api,
                    "reason": "source_universe_unverified",
                    "dependencies": [SOURCE_FAMILIES[api]],
                    "observed_accepted_codes": len(codes),
                    "unsupported_source_codes": unsupported,
                }
            )
            if not config.get("realtime_extra_snapshot_epoch"):
                gaps.append(
                    {
                        "api_name": api,
                        "reason": "explicit_current_snapshot_epoch_required",
                        "dependencies": [],
                    }
                )
        if api in MINUTE_APIS and set(frequencies) != set(FREQUENCIES):
            gaps.append(
                {
                    "api_name": api,
                    "reason": "explicit_frequency_subset_scope",
                    "selected": list(frequencies),
                    "dependencies": [],
                }
            )
    return gaps


def iter_realtime_extra_jobs(config, today, identifiers=None):
    """Lazy snapshots require a same-day explicit UTC slot; only auction has history.

    No timer is installed here. Runtime must validate actual freshness at dispatch;
    never queue a year's old snapshot epochs or substitute poll time for source time.
    """
    enabled, frequencies = _settings(config)
    if not enabled:
        return
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("today must be Asia/Shanghai calendar date")
    start = _auction_start(config) if "stk_auction" in enabled else None
    if start and start > today:
        raise ValueError("Auction history cannot start in the future")
    epoch = _epoch(
        {"discovered_snapshot_epoch": config.get("realtime_extra_snapshot_epoch")},
        today,
    )
    streams = []
    for api in enabled:
        if api != "stk_auction" and epoch:
            streams.append(
                (api, iter(_snapshot_requests(api, identifiers, frequencies)))
            )
    for row in zip_longest(*(stream for _, stream in streams)):
        for (api, _), params in zip(streams, row, strict=True):
            if params is not None:
                yield {
                    "api_name": api,
                    "params": params,
                    "fields": ",".join(FIELDS[api]),
                    "priority": 20,
                    "epoch": epoch,
                }
    if "stk_auction" not in enabled:
        return
    recent = today - timedelta(days=6)
    # Separate legal dated API branch: no artificial historical epoch for realtime.
    for history in (False, True):
        begin, end = (
            (start, recent - timedelta(days=1))
            if history
            else (max(start, recent), today)
        )
        windows = (
            _months(begin, end)
            if history
            else (
                (day, day)
                for day in (
                    begin + timedelta(days=i)
                    for i in range(max(0, (end - begin).days + 1))
                )
            )
        )
        for first, last in windows:
            params = (
                {
                    "start_date": first.strftime("%Y%m%d"),
                    "end_date": last.strftime("%Y%m%d"),
                }
                if history
                else {"trade_date": first.strftime("%Y%m%d")}
            )
            for variant in REALTIME_EXTRA_CONTRACTS["stk_auction"]["request_variants"]:
                yield {
                    "api_name": "stk_auction",
                    "params": {**params, **variant},
                    "fields": ",".join(FIELDS["stk_auction"]),
                    "priority": 55 if history else 20,
                    "epoch": "history"
                    if history
                    else str(config.get("planning_epoch", today.strftime("%Y%m%d"))),
                }
