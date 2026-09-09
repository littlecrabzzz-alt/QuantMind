"""Pure cross-asset factors, global indexes and market statistics; no I/O.
Official pages reviewed 2026-09-09. This module does not register acquisition.
"""

from datetime import date, datetime, timedelta
import re
from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_market_contracts import _codes, _months
from backend.shared.tushare_global_contracts import _interleave

# Exact official names/types/default flags/formula parameters, including hidden N.
_OUTPUT_TABLES = {
    "idx_factor_pro": """
ts_code|str|Y|指数代码
trade_date|str|Y|交易日期
open|float|Y|开盘价
high|float|Y|最高价
low|float|Y|最低价
close|float|Y|收盘价
pre_close|float|Y|昨收价
change|float|Y|涨跌额
pct_change|float|Y|涨跌幅 （未复权，如果是复权请用 通用行情接口 ）
vol|float|Y|成交量 （手）
amount|float|Y|成交额 （千元）
asi_bfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
asit_bfq|float|Y|振动升降指标-OPEN, CLOSE, HIGH, LOW, M1=26, M2=10
atr_bfq|float|Y|真实波动N日平均值-CLOSE, HIGH, LOW, N=20
bbi_bfq|float|Y|BBI多空指标-CLOSE, M1=3, M2=6, M3=12, M4=20
bias1_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias2_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
bias3_bfq|float|Y|BIAS乖离率-CLOSE, L1=6, L2=12, L3=24
boll_lower_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_mid_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
boll_upper_bfq|float|Y|BOLL指标，布林带-CLOSE, N=20, P=2
brar_ar_bfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
brar_br_bfq|float|Y|BRAR情绪指标-OPEN, CLOSE, HIGH, LOW, M1=26
cci_bfq|float|Y|顺势指标又叫CCI指标-CLOSE, HIGH, LOW, N=14
cr_bfq|float|Y|CR价格动量指标-CLOSE, HIGH, LOW, N=20
dfma_dif_bfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dfma_difma_bfq|float|Y|平行线差指标-CLOSE, N1=10, N2=50, M=10
dmi_adx_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_adxr_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_mdi_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
dmi_pdi_bfq|float|Y|动向指标-CLOSE, HIGH, LOW, M1=14, M2=6
downdays|float|Y|连跌天数
updays|float|Y|连涨天数
dpo_bfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
madpo_bfq|float|Y|区间震荡线-CLOSE, M1=20, M2=10, M3=6
ema_bfq_10|float|Y|指数移动平均-N=10
ema_bfq_20|float|Y|指数移动平均-N=20
ema_bfq_250|float|Y|指数移动平均-N=250
ema_bfq_30|float|Y|指数移动平均-N=30
ema_bfq_5|float|Y|指数移动平均-N=5
ema_bfq_60|float|Y|指数移动平均-N=60
ema_bfq_90|float|Y|指数移动平均-N=90
emv_bfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
maemv_bfq|float|Y|简易波动指标-HIGH, LOW, VOL, N=14, M=9
expma_12_bfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
expma_50_bfq|float|Y|EMA指数平均数指标-CLOSE, N1=12, N2=50
kdj_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_d_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
kdj_k_bfq|float|Y|KDJ指标-CLOSE, HIGH, LOW, N=9, M1=3, M2=3
ktn_down_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_mid_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
ktn_upper_bfq|float|Y|肯特纳交易通道, N选20日，ATR选10日-CLOSE, HIGH, LOW, N=20, M=10
lowdays|float|Y|LOWRANGE(LOW)表示当前最低价是近多少周期内最低价的最小值
topdays|float|Y|TOPRANGE(HIGH)表示当前最高价是近多少周期内最高价的最大值
ma_bfq_10|float|Y|简单移动平均-N=10
ma_bfq_20|float|Y|简单移动平均-N=20
ma_bfq_250|float|Y|简单移动平均-N=250
ma_bfq_30|float|Y|简单移动平均-N=30
ma_bfq_5|float|Y|简单移动平均-N=5
ma_bfq_60|float|Y|简单移动平均-N=60
ma_bfq_90|float|Y|简单移动平均-N=90
macd_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dea_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
macd_dif_bfq|float|Y|MACD指标-CLOSE, SHORT=12, LONG=26, M=9
mass_bfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
ma_mass_bfq|float|Y|梅斯线-HIGH, LOW, N1=9, N2=25, M=6
mfi_bfq|float|Y|MFI指标是成交量的RSI指标-CLOSE, HIGH, LOW, VOL, N=14
mtm_bfq|float|Y|动量指标-CLOSE, N=12, M=6
mtmma_bfq|float|Y|动量指标-CLOSE, N=12, M=6
obv_bfq|float|Y|能量潮指标-CLOSE, VOL
psy_bfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
psyma_bfq|float|Y|投资者对股市涨跌产生心理波动的情绪指标-CLOSE, N=12, M=6
roc_bfq|float|Y|变动率指标-CLOSE, N=12, M=6
maroc_bfq|float|Y|变动率指标-CLOSE, N=12, M=6
rsi_bfq_12|float|Y|RSI指标-CLOSE, N=12
rsi_bfq_24|float|Y|RSI指标-CLOSE, N=24
rsi_bfq_6|float|Y|RSI指标-CLOSE, N=6
taq_down_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_mid_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
taq_up_bfq|float|Y|唐安奇通道(海龟)交易指标-HIGH, LOW, 20
trix_bfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
trma_bfq|float|Y|三重指数平滑平均线-CLOSE, M1=12, M2=20
vr_bfq|float|Y|VR容量比率-CLOSE, VOL, M1=26
wr_bfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
wr1_bfq|float|Y|W&R 威廉指标-CLOSE, HIGH, LOW, N=10, N1=6
xsii_td1_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td2_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td3_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
xsii_td4_bfq|float|Y|薛斯通道II-CLOSE, HIGH, LOW, N=102, M=7
""",
    "index_global": """
ts_code|str|Y|TS指数代码
trade_date|str|Y|交易日
open|float|Y|开盘点位
close|float|Y|收盘点位
high|float|Y|最高点位
low|float|Y|最低点位
pre_close|float|Y|昨日收盘点
change|float|Y|涨跌点位
pct_chg|float|Y|涨跌幅
swing|float|Y|振幅
vol|float|Y|成交量 （大部分无此项数据）
amount|float|N|成交额 （大部分无此项数据）
""",
    "sz_daily_info": """
trade_date|str|Y|
ts_code|str|Y|市场类型
count|int|Y|股票个数
amount|float|Y|成交金额
vol|int|Y|成交量
total_share|float|Y|总股本
total_mv|float|Y|总市值
float_share|float|Y|流通股票
float_mv|float|Y|流通市值
""",
    "etf_limit": """
trade_date|str|Y|交易日期
ts_code|str|Y|合约代码
pre_close|float|N|昨日收盘价
up_limit|float|Y|涨停价
down_limit|float|Y|跌停价
asset_type|str|N|类型 ETF
exchange|str|N|交易所：SSE/SZSE
""",
}
# Official tables differ in only these entries; preserve order and all source types.
_OUTPUT_TABLES["fund_factor_pro"] = (
    _OUTPUT_TABLES["idx_factor_pro"]
    .replace("ts_code|str|Y|指数代码", "ts_code|str|Y|基金代码")
    .replace(
        "trade_date|str|Y|交易日期",
        "trade_date|str|Y|交易日期\ntrade_date_doris|None|Y|日期",
    )
)
_OUTPUT_TABLES["cb_factor_pro"] = (
    _OUTPUT_TABLES["idx_factor_pro"]
    .replace("ts_code|str|Y|指数代码", "ts_code|str|Y|转债代码")
    .replace("amount|float|Y|成交额 （千元）", "amount|float|Y|成交金额(万元)")
)
FIELD_METADATA = {
    api: {
        parts[0]: dict(zip(("type", "default", "description"), parts[1:], strict=True))
        for line in table.strip().splitlines()
        if (parts := line.split("|", 3))
    }
    for api, table in _OUTPUT_TABLES.items()
}
FIELDS = {api: list(fields) for api, fields in FIELD_METADATA.items()}
INPUT_FIELDS = {api: "ts_code trade_date start_date end_date".split() for api in FIELDS}
SOURCE_HTML_SHA256 = {
    "idx_factor_pro": "ec9e96b24e5ebf464e1a7a06d9e2c1db2cfd341102d733d05a1092928f542451",
    "fund_factor_pro": "394c4e91872ea44fba0aff983a4b9c5a5e39a66def0c220b1fc181e7ac6d17b2",
    "cb_factor_pro": "e8e1aaa652767517f85f1ed733f3ad0c0e5d4c685e7b6e5b6a68f06316fb18b8",
    "index_global": "d609b225c655a55bde5a0d6cdbfe3dc12fd0b36eab07003adaff4d375145387c",
    "sz_daily_info": "801db76a7d3a0f8331ddd57492771c9e18670d3f8d0649876d702aaf14e74604",
    "etf_limit": "534dd19bb5899733f3e368890836cecf82e86cefc550b7e39a65f2c816338601",
}
GLOBAL_INDEX_CODES = {
    "XIN9": "富时中国A50指数  (富时A50)",
    "HSI": "恒生指数",
    "HKTECH": "恒生科技指数",
    "HKAH": "恒生AH股H指数",
    "DJI": "道琼斯工业指数",
    "SPX": "标普500指数",
    "IXIC": "纳斯达克指数",
    "FTSE": "富时100指数",
    "FCHI": "法国CAC40指数",
    "GDAXI": "德国DAX指数",
    "N225": "日经225指数",
    "KS11": "韩国综合指数",
    "AS51": "澳大利亚标普200指数",
    "SENSEX": "印度孟买SENSEX指数",
    "IBOVESPA": "巴西IBOVESPA指数",
    "RTS": "俄罗斯RTS指数",
    "TWII": "台湾加权指数",
    "CKLSE": "马来西亚指数",
    "SPTSX": "加拿大S&P/TSX指数",
    "CSX5P": "STOXX欧洲50指数",
    "RUT": "罗素2000指数",
}
SZ_BOARD_STARTS = {
    "股票": "20080102",
    "主板A股": "20080102",
    "主板B股": "20080102",
    "创业板A股": "20080102",
    "基金": "20080102",
    "ETF": "20080102",
    "LOF": "20080102",
    "封闭式基金": "20080102",
    "基础设施基金": "20210621",
    "债券": "20080102",
    "债券现券": "20080102",
    "债券回购": "20080102",
    "ABS": "20080102",
    "期权": "20080102",
}
# Historical example contains a retired board absent from the current table.
SZ_HISTORICAL_EXAMPLE_CODES = ("中小板",)
_DOCS = {
    "idx_factor_pro": (358, 8000, 5000, "cross_asset_indexes"),
    "fund_factor_pro": (359, 8000, 5000, "cross_asset_funds"),
    "cb_factor_pro": (392, 10000, 8000, "bonds"),
    "index_global": (211, 4000, 6000, "global_indexes"),
    "sz_daily_info": (268, 2000, 2000, "sz_boards"),
    "etf_limit": (491, 3000, 2000, "etfs"),
}
CROSS_ASSET_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _family) in _DOCS.items():
    _fields = FIELDS[_api]
    _spec = _contract(
        _cap,
        ("ts_code", "trade_date"),
        required=("ts_code", "trade_date"),
        nullable=[f for f in _fields if f not in ("ts_code", "trade_date")],
        extra=_fields,
        rpm=30,
        start="20080102" if _api == "sz_daily_info" else None,
    )
    _spec.update(
        doc_id=_doc,
        official_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_reviewed_at="2026-09-09",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        dataset_identity=_api,
        requested_fields=_fields,
        hidden_fields=[f for f in _fields if FIELD_METADATA[_api][f]["default"] == "N"],
        field_metadata=FIELD_METADATA[_api],
        date_field="trade_date",
        history_bound_verified=False,
        saturation_fallback=_family,
        saturation_param="ts_code",
        discovery_dependencies=[_family],
        universe_complete=False,
        preserve_distinct_rows=True,
        permission_note=f"Official page requires {_points} points; account permission has not been probed. Operational 30/min is not an entitlement assertion; share the account/API gates.",
        documented_minimum_points=_points,
        documented_requests_per_minute=None,
        history_gap="No exact first observation documented. Explicit configured history is a requested envelope, not a completeness proof.",
        discovery_gap="Bulk date requests do not depend on current listings. Saturation fanout must union all stored historical/retired and parent-observed identifiers. Observed subsets do not prove the universe complete.",
        pagination_gap="No offset/limit input documented. Bisect date ranges; terminal date/code saturation remains a gap, not guessed pagination.",
        pit_gap="trade_date is a source market date, not a release timestamp. Preserve observations/revisions; no historical availability or historical membership proof.",
        refresh_gap="Recent overlap does not prove old corrections/deletions have been recaptured.",
        field_selection_note="Request all documented fields including hidden N; retain unknown returned columns and nulls. Missing live fields remain a schema gap.",
        unit_note="No scale conversion; retain supplier values and metadata.",
        namespace_note="Source identifiers are dataset-scoped; never infer an A-share identity from ts_code alone.",
    )
    CROSS_ASSET_EXTRA_CONTRACTS[_api] = _spec
for _api in ("idx_factor_pro", "fund_factor_pro", "cb_factor_pro"):
    CROSS_ASSET_EXTRA_CONTRACTS[_api].update(
        documented_rate_tiers=[
            {"minimum_points": 5000, "rpm": 30},
            {"minimum_points": 8000, "rpm": 500},
        ]
        if _api != "cb_factor_pro"
        else [{"minimum_points": 8000, "rpm": 500}],
        history_gap="Page claims full history but gives no calendar lower bound; no example date may replace configured historical scope.",
        adjustment_note="All listed technical fields are bfq. Keep supplier factors; do not recompute or silently substitute qfq/hfq.",
        formula_gap="Literal defaults retained per field; seeds, warm-up, rounding, revision vintages and full calculation methods remain unspecified.",
        unit_note="vol lots; amount ten-thousand currency units (currency not explicitly labelled)."
        if _api == "cb_factor_pro"
        else "vol lots; amount thousand currency units (currency not explicitly labelled). Signed indicators and null warm-up values are valid.",
    )
CROSS_ASSET_EXTRA_CONTRACTS["cb_factor_pro"]["adjustment_note"] += (
    " Prose mentions qfq/hfq but no such output columns are listed: support beyond the official table is unverified."
)
CROSS_ASSET_EXTRA_CONTRACTS["fund_factor_pro"]["field_type_gap"] = (
    "trade_date_doris is documented with literal type None. Preserve its raw value; do not use it as the trading-date axis or drop it."
)
CROSS_ASSET_EXTRA_CONTRACTS["fund_factor_pro"]["namespace_note"] = (
    "Listed fund source codes, including opaque seven-digit historical codes, stay distinct. Exclude .OF from outbound listed-market scope without deleting raw discovery; a code is not proof of tradability."
)
CROSS_ASSET_EXTRA_CONTRACTS["index_global"].update(
    unit_note="OHLC are index points; vol/amount are often absent and their cross-market scales/currencies are unspecified. Hidden amount must be explicitly requested.",
    namespace_note="International index labels such as HSI/SPX/XIN9 are opaque dataset-scoped source names, not US equities or domestic suffix indexes.",
    calendar_gap="No shared exchange timezone/calendar is specified; do not apply mainland holidays or convert trade_date to UTC. Official current 21-code list does not prove retired/historical coverage.",
)
CROSS_ASSET_EXTRA_CONTRACTS["sz_daily_info"].update(
    history_gap="Table gives 20080102 for most boards and 20210621 for infrastructure funds; old example also contains 中小板. Bulk history starts at the earliest documented market envelope, retaining configured earlier requests.",
    unit_note="count is a count; exact amount/vol/share/mv scales are not specified. Do not copy daily lots/thousand-CNY units.",
    namespace_note="ts_code is a Chinese/ASCII board label, including historical 中小板, not a stock symbol. Current board table is not an exhaustive historical allowlist.",
    history_bound_verified=False,
)
CROSS_ASSET_EXTRA_CONTRACTS["etf_limit"].update(
    documented_update_time="08:40 approximately",
    update_timezone_verified=False,
    unit_note="Price currency/scale is not explicitly stated. Keep pre_close/up_limit/down_limit without assuming a universal limit percentage.",
    namespace_note="ETF identifiers only; copied stock/contract wording in the page is not proof of A-share/futures coverage.",
    field_type_gap="asset_type and exchange are hidden source fields, not request filters. Preserve explicit ETF and SSE/SZSE values without inferring missing ones.",
)


def _enabled(config):
    values = config.get("cross_asset_extra_apis", tuple(CROSS_ASSET_EXTRA_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(a, str) or a not in CROSS_ASSET_EXTRA_CONTRACTS for a in values
    ):
        raise ValueError("Unknown cross_asset_extra_apis")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    value = config.get("cross_asset_extra_history_start")
    if value is not None and not isinstance(value, (str, dict)):
        raise ValueError("Invalid historical scope")
    if isinstance(value, dict) and value.keys() - CROSS_ASSET_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown historical scope API")
    starts = {}
    for api in enabled:
        requested = value.get(api) if isinstance(value, dict) else value
        requested = requested if requested is not None else config.get("history_start")
        floor = CROSS_ASSET_EXTRA_CONTRACTS[api]["history_start"]
        starts[api] = (
            _parse(requested)
            if requested is not None
            else _parse(floor)
            if floor
            else None
        )
    return starts


def _code(api, code):
    if (
        not isinstance(code, str)
        or not code
        or len(code) > 64
        or any(c.isspace() or c in ",\\\"'" or ord(c) < 32 for c in code)
    ):
        raise ValueError("Invalid source identifier")
    if api == "sz_daily_info":
        if not re.fullmatch(r"[A-Za-z0-9\u3400-\u9fff]+", code):
            raise ValueError("Invalid board label")
    elif api == "index_global":
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", code):
            raise ValueError("Invalid global index label")
    elif api in ("fund_factor_pro", "etf_limit"):
        if not re.fullmatch(r"[0-9]{6,7}\.(SH|SZ|BJ)", code):
            raise ValueError("Invalid listed fund identifier")
    elif api == "cb_factor_pro":
        if not re.fullmatch(r"T?[0-9]{6}\.(SH|SZ)", code):
            raise ValueError("Invalid convertible identifier")
    elif not re.fullmatch(r"[A-Za-z0-9]+\.[A-Z]+", code):
        raise ValueError("Invalid index identifier")
    return code


def cross_asset_identifiers(identifiers=None, enabled_apis=None):
    ids = {} if identifiers is None else identifiers
    if not isinstance(ids, dict):
        raise ValueError("Identifier mapping required")
    result = {}
    enabled = _enabled(
        {} if enabled_apis is None else {"cross_asset_extra_apis": enabled_apis}
    )
    for api in enabled:
        spec = CROSS_ASSET_EXTRA_CONTRACTS[api]
        family = spec["saturation_fallback"]
        families = {
            "cross_asset_indexes": ("indexes", "sw_indexes", "ci_indexes", family),
            "cross_asset_funds": ("funds", "etfs", family),
        }.get(family, (family,))
        values = set(
            GLOBAL_INDEX_CODES
            if api == "index_global"
            else (*SZ_BOARD_STARTS, *SZ_HISTORICAL_EXAMPLE_CODES)
            if api == "sz_daily_info"
            else ()
        )
        for source in families:
            rows = ids.get(source, ())
            if not isinstance(rows, (list, tuple)):
                raise ValueError("Discovery must be a list")
            # Existing suffix discovery helper preserves codes/statuses unchanged.
            if api not in ("index_global", "sz_daily_info"):
                codes = _codes({source: rows}, source)
            else:
                codes = [r.get("ts_code") if isinstance(r, dict) else r for r in rows]
            for code in codes:
                if (
                    api in ("fund_factor_pro", "etf_limit")
                    and isinstance(code, str)
                    and code.endswith(".OF")
                ):
                    continue
                values.add(_code(api, code))
        result[family] = sorted(values)
    return result


def validate_cross_asset_request(api, params):
    if (
        api not in CROSS_ASSET_EXTRA_CONTRACTS
        or not isinstance(params, dict)
        or params.keys() - set(INPUT_FIELDS[api])
    ):
        raise ValueError("Undocumented request")
    if "ts_code" in params:
        _code(api, params["ts_code"])
    for k in ("trade_date", "start_date", "end_date"):
        if k in params:
            _parse(params[k])
    if "trade_date" in params and ("start_date" in params or "end_date" in params):
        raise ValueError("Mixed date axes not reviewed")
    if (
        "start_date" in params
        and "end_date" in params
        and _parse(params["start_date"]) > _parse(params["end_date"])
    ):
        raise ValueError("Reversed date window")


def split_cross_asset_request(api, params):
    validate_cross_asset_request(api, params)
    if not {"start_date", "end_date"} <= params.keys():
        return []
    left, right = _parse(params["start_date"]), _parse(params["end_date"])
    if left == right:
        return []
    mid = left + (right - left) // 2
    return [
        {**params, "end_date": mid.strftime("%Y%m%d")},
        {**params, "start_date": (mid + timedelta(days=1)).strftime("%Y%m%d")},
    ]


def cross_asset_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["cross_asset_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    ids = cross_asset_identifiers(identifiers, enabled)
    gaps = []
    for api in enabled:
        spec = CROSS_ASSET_EXTRA_CONTRACTS[api]
        for key in (
            "history_gap",
            "discovery_gap",
            "pagination_gap",
            "pit_gap",
            "refresh_gap",
            "calendar_gap",
            "formula_gap",
            "field_type_gap",
        ):
            if spec.get(key):
                gaps.append(
                    {
                        "api_name": api,
                        "reason": key,
                        "detail": spec[key],
                        "dependencies": [],
                    }
                )
        gaps.append(
            {
                "api_name": api,
                "reason": "configured_scope_not_verified_complete"
                if starts[api]
                else "unknown_history_start_requires_scope",
                "dependencies": spec["discovery_dependencies"],
                "observed_or_documented_codes": len(ids[spec["saturation_fallback"]]),
                "universe_complete": False,
            }
        )
    return gaps


def iter_cross_asset_extra_jobs(config, today, identifiers=None):
    """Bulk recent days first, then lazy fair monthly history. No guessed paging."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("Future history start")
    end = today - timedelta(days=1)
    recent = end - timedelta(days=6)

    def windows(begin, stop, daily):
        if daily:
            while begin <= stop:
                yield {"trade_date": begin.strftime("%Y%m%d")}
                begin += timedelta(days=1)
        else:
            for left, right in _months(begin, stop):
                yield {
                    "start_date": left.strftime("%Y%m%d"),
                    "end_date": right.strftime("%Y%m%d"),
                }

    for history in (False, True):

        def jobs(api, history=history):
            start = starts[api]
            if history and (start is None or start >= recent):
                return
            begin = start if history else max(start or recent, recent)
            stop = recent - timedelta(days=1) if history else end
            for params in windows(begin, stop, not history):
                yield {
                    "api_name": api,
                    "params": params,
                    "fields": ",".join(FIELDS[api]),
                    "priority": 55 if history else 20,
                    "epoch": "history"
                    if history
                    else str(config.get("planning_epoch", today.strftime("%Y%m%d"))),
                }

        yield from _interleave([jobs(api) for api in enabled])
