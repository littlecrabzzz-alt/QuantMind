"""Pure TDX boards, KP events/members and THS/DC ranking acquisition contracts.

No permissions, account access, historical completeness or RRG PIT claims.
"""

from datetime import date, datetime, timedelta
from itertools import product

from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_technical_extra_contracts import _days

SOURCE_HTML_SHA256 = {
    "tdx_index": "9b9d093314fc4efa148f5b5caa4ee7d0f50f8e65605e520f7f0e77949074ee0f",
    "tdx_member": "7f144546fcec1d711af9e9059049bbaf24923d867b4d72bab62c66833af0f17a",
    "tdx_daily": "6a2f2ace60309bb06218a1d59333090f48772120306ac26bcb99c8a9ea6d468d",
    "kpl_list": "281823f615b4066515d0e56ca12369721e1f5f195ec5d114d278a7d422f23b23",
    "kpl_concept_cons": "e250e114696b3854f0256e9ae0c15b34e654dd72b8ee08429929f02c51b311e8",
    "ths_hot": "c71476d3c547a276ef489ff1bda7234619c6db4291829bbe5fa1914a78bdb4a0",
    "dc_hot": "90701ed78b217c5f21c0addc97ee632a1066a117ca6fe00062f8830a1194ffaa",
}

INPUT_METADATA = {
    "tdx_index": {
        "ts_code": {
            "type": "str",
            "required": "N",
            "description": "板块代码：xxxxxx.TDX",
        },
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期(格式：YYYYMMDD）",
        },
        "idx_type": {
            "type": "str",
            "required": "N",
            "description": "板块类型：概念板块、行业板块、风格板块、地区板块",
        },
    },
    "tdx_member": {
        "ts_code": {
            "type": "str",
            "required": "N",
            "description": "板块代码：xxxxxx.TDX",
        },
        "con_code": {"type": "str", "required": "N", "description": "成分股票代码"},
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期：（YYYYMMDD格式）",
        },
        "start_date": {
            "type": "str",
            "required": "N",
            "description": "开始日期：（YYYYMMDD格式）",
        },
        "end_date": {
            "type": "str",
            "required": "N",
            "description": "结束日期：（YYYYMMDD格式）",
        },
    },
    "tdx_daily": {
        "ts_code": {
            "type": "str",
            "required": "N",
            "description": "板块代码：xxxxxx.TDX",
        },
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期，格式YYYYMMDD,下同",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "kpl_list": {
        "ts_code": {"type": "str", "required": "N", "description": "股票代码"},
        "trade_date": {"type": "str", "required": "N", "description": "交易日期"},
        "tag": {
            "type": "str",
            "required": "N",
            "description": "板单类型（涨停/炸板/跌停/自然涨停/竞价，默认为涨停)",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "kpl_concept_cons": {
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期（YYYYMMDD格式）",
        },
        "ts_code": {
            "type": "str",
            "required": "N",
            "description": "题材代码（xxxxxx.KP格式）",
        },
        "con_code": {
            "type": "str",
            "required": "N",
            "description": "成分代码（xxxxxx.SH格式）",
        },
    },
    "ths_hot": {
        "trade_date": {"type": "str", "required": "N", "description": "交易日期"},
        "ts_code": {"type": "str", "required": "N", "description": "TS代码"},
        "market": {
            "type": "str",
            "required": "N",
            "description": "热榜类型(热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股)",
        },
        "is_new": {
            "type": "str",
            "required": "N",
            "description": "是否最新（默认Y，如果为N则为盘中和盘后阶段采集，具体时间可参考rank_time字段，状态N每2小时更新一次，状态Y更新时间为22：30）",
        },
    },
    "dc_hot": {
        "trade_date": {"type": "str", "required": "N", "description": "交易日期"},
        "ts_code": {"type": "str", "required": "N", "description": "TS代码"},
        "market": {
            "type": "str",
            "required": "N",
            "description": "类型(A股市场、ETF基金、港股市场、美股市场)",
        },
        "hot_type": {
            "type": "str",
            "required": "N",
            "description": "热点类型(人气榜、飙升榜)",
        },
        "is_new": {
            "type": "str",
            "required": "N",
            "description": "是否最新（默认Y，如果为N则为盘中和盘后阶段采集，具体时间可参考rank_time字段，状态N每2小时更新一次，状态Y更新时间为22：30）",
        },
    },
}

FIELD_METADATA = {
    "tdx_index": {
        "ts_code": {"type": "str", "default": "Y", "description": "板块代码"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "name": {"type": "str", "default": "Y", "description": "板块名称"},
        "idx_type": {"type": "str", "default": "Y", "description": "板块类型"},
        "idx_count": {"type": "int", "default": "Y", "description": "成分个数"},
        "total_share": {"type": "float", "default": "Y", "description": "总股本(亿)"},
        "float_share": {"type": "float", "default": "Y", "description": "流通股(亿)"},
        "total_mv": {"type": "float", "default": "Y", "description": "总市值(亿)"},
        "float_mv": {"type": "float", "default": "Y", "description": "流通市值(亿)"},
    },
    "tdx_member": {
        "ts_code": {"type": "str", "default": "Y", "description": "板块代码"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "con_code": {"type": "str", "default": "Y", "description": "成分股票代码"},
        "con_name": {"type": "str", "default": "Y", "description": "成分股票名称"},
    },
    "tdx_daily": {
        "ts_code": {"type": "str", "default": "Y", "description": "板块代码"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "close": {"type": "float", "default": "Y", "description": "收盘点位"},
        "open": {"type": "float", "default": "Y", "description": "开盘点位"},
        "high": {"type": "float", "default": "Y", "description": "最高点位"},
        "low": {"type": "float", "default": "Y", "description": "最低点位"},
        "pre_close": {"type": "float", "default": "Y", "description": "昨日收盘点"},
        "change": {"type": "float", "default": "Y", "description": "涨跌点位"},
        "pct_change": {"type": "float", "default": "Y", "description": "涨跌幅%"},
        "vol": {"type": "float", "default": "Y", "description": "成交量（手）"},
        "amount": {
            "type": "float",
            "default": "Y",
            "description": "成交额（万元）, 对于期货指数，该字段存储持仓量",
        },
        "rise": {"type": "str", "default": "Y", "description": "收盘涨速%"},
        "vol_ratio": {"type": "float", "default": "Y", "description": "量比"},
        "turnover_rate": {"type": "float", "default": "Y", "description": "换手%"},
        "swing": {"type": "float", "default": "Y", "description": "振幅%"},
        "up_num": {"type": "int", "default": "Y", "description": "上涨家数"},
        "down_num": {"type": "int", "default": "Y", "description": "下跌家数"},
        "limit_up_num": {"type": "int", "default": "Y", "description": "涨停家数"},
        "limit_down_num": {"type": "int", "default": "Y", "description": "跌停家数"},
        "lu_days": {"type": "int", "default": "Y", "description": "连涨天数"},
        "3day": {"type": "float", "default": "Y", "description": "3日涨幅%"},
        "5day": {"type": "float", "default": "Y", "description": "5日涨幅%"},
        "10day": {"type": "float", "default": "Y", "description": "10日涨幅%"},
        "20day": {"type": "float", "default": "Y", "description": "20日涨幅%"},
        "60day": {"type": "float", "default": "Y", "description": "60日涨幅%"},
        "mtd": {"type": "float", "default": "Y", "description": "月初至今%"},
        "ytd": {"type": "float", "default": "Y", "description": "年初至今%"},
        "1year": {"type": "float", "default": "Y", "description": "一年涨幅%"},
        "pe": {"type": "str", "default": "Y", "description": "市盈率"},
        "pb": {"type": "str", "default": "Y", "description": "市净率"},
        "float_mv": {"type": "float", "default": "Y", "description": "流通市值(亿)"},
        "ab_total_mv": {
            "type": "float",
            "default": "Y",
            "description": "AB股总市值（亿）",
        },
        "float_share": {"type": "float", "default": "Y", "description": "流通股(亿)"},
        "total_share": {"type": "float", "default": "Y", "description": "总股本(亿)"},
        "bm_buy_net": {"type": "float", "default": "Y", "description": "主买净额(元)"},
        "bm_buy_ratio": {"type": "float", "default": "Y", "description": "主买占比%"},
        "bm_net": {"type": "float", "default": "Y", "description": "主力净额"},
        "bm_ratio": {"type": "float", "default": "Y", "description": "主力占比%"},
    },
    "kpl_list": {
        "ts_code": {"type": "str", "default": "Y", "description": "代码"},
        "name": {"type": "str", "default": "Y", "description": "名称"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易时间"},
        "lu_time": {"type": "str", "default": "Y", "description": "涨停时间"},
        "ld_time": {"type": "str", "default": "Y", "description": "跌停时间"},
        "open_time": {"type": "str", "default": "Y", "description": "开板时间"},
        "last_time": {"type": "str", "default": "Y", "description": "最后涨停时间"},
        "lu_desc": {"type": "str", "default": "Y", "description": "涨停原因"},
        "tag": {"type": "str", "default": "Y", "description": "标签"},
        "theme": {"type": "str", "default": "Y", "description": "板块"},
        "net_change": {"type": "float", "default": "Y", "description": "主力净额(元)"},
        "bid_amount": {
            "type": "float",
            "default": "Y",
            "description": "竞价成交额(元)",
        },
        "status": {"type": "str", "default": "Y", "description": "状态（N连板）"},
        "bid_change": {"type": "float", "default": "Y", "description": "竞价净额"},
        "bid_turnover": {"type": "float", "default": "Y", "description": "竞价换手%"},
        "lu_bid_vol": {"type": "float", "default": "Y", "description": "涨停委买额"},
        "pct_chg": {"type": "float", "default": "Y", "description": "涨跌幅%"},
        "bid_pct_chg": {"type": "float", "default": "Y", "description": "竞价涨幅%"},
        "rt_pct_chg": {"type": "float", "default": "Y", "description": "实时涨幅%"},
        "limit_order": {"type": "float", "default": "Y", "description": "封单"},
        "amount": {"type": "float", "default": "Y", "description": "成交额"},
        "turnover_rate": {"type": "float", "default": "Y", "description": "换手率%"},
        "free_float": {"type": "float", "default": "Y", "description": "实际流通"},
        "lu_limit_order": {"type": "float", "default": "Y", "description": "最大封单"},
    },
    "kpl_concept_cons": {
        "ts_code": {"type": "str", "default": "Y", "description": "题材ID"},
        "name": {"type": "str", "default": "Y", "description": "题材名称"},
        "con_name": {"type": "str", "default": "Y", "description": "股票名称"},
        "con_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "desc": {"type": "str", "default": "Y", "description": "描述"},
        "hot_num": {"type": "int", "default": "Y", "description": "人气值"},
    },
    "ths_hot": {
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "data_type": {"type": "str", "default": "Y", "description": "数据类型"},
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "ts_name": {"type": "str", "default": "Y", "description": "股票名称"},
        "rank": {"type": "int", "default": "Y", "description": "排行"},
        "pct_change": {"type": "float", "default": "Y", "description": "涨跌幅%"},
        "current_price": {"type": "float", "default": "Y", "description": "当前价格"},
        "concept": {"type": "str", "default": "Y", "description": "标签"},
        "rank_reason": {"type": "str", "default": "Y", "description": "上榜解读"},
        "hot": {"type": "float", "default": "Y", "description": "热度值"},
        "rank_time": {"type": "str", "default": "Y", "description": "排行榜获取时间"},
    },
    "dc_hot": {
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "data_type": {"type": "str", "default": "Y", "description": "数据类型"},
        "ts_code": {"type": "str", "default": "Y", "description": "股票代码"},
        "ts_name": {"type": "str", "default": "Y", "description": "股票名称"},
        "rank": {"type": "int", "default": "Y", "description": "排行或者热度"},
        "pct_change": {"type": "float", "default": "Y", "description": "涨跌幅%"},
        "current_price": {"type": "float", "default": "Y", "description": "当前价"},
        "rank_time": {"type": "str", "default": "Y", "description": "排行榜获取时间"},
    },
}

FIELDS = {api: list(table) for api, table in FIELD_METADATA.items()}
INPUT_FIELDS = {api: list(table) for api, table in INPUT_METADATA.items()}
TDX_TYPES = ("概念板块", "行业板块", "风格板块", "地区板块")
KPL_TAGS = ("涨停", "炸板", "跌停", "自然涨停", "竞价")
THS_MARKETS = (
    "热股",
    "ETF",
    "可转债",
    "行业板块",
    "概念板块",
    "期货",
    "港股",
    "热基",
    "美股",
)
DC_MARKETS = ("A股市场", "ETF基金", "港股市场", "美股市场")
DC_HOT_TYPES = ("人气榜", "飙升榜")
VARIANTS = {
    "tdx_index": [{"idx_type": value} for value in TDX_TYPES],
    "tdx_member": [{}],
    "tdx_daily": [{}],
    "kpl_list": [{"tag": value} for value in KPL_TAGS],
    "kpl_concept_cons": [{}],
    "ths_hot": [
        {"market": market, "is_new": fresh}
        for market, fresh in product(THS_MARKETS, ("Y", "N"))
    ],
    "dc_hot": [
        {"market": market, "hot_type": kind, "is_new": fresh}
        for market, kind, fresh in product(DC_MARKETS, DC_HOT_TYPES, ("Y", "N"))
    ],
}
_DOCS = {
    "tdx_index": (376, 1000, 6000),
    "tdx_member": (377, 3000, 6000),
    "tdx_daily": (378, 3000, 6000),
    "kpl_list": (347, 8000, 5000),
    "kpl_concept_cons": (351, 3000, 5000),
    "ths_hot": (320, 2000, 6000),
    "dc_hot": (321, 2000, 8000),
}
MARKET_SENTIMENT_CONTRACTS = {}
for _api, (_doc, _cap, _points) in _DOCS.items():
    keys = ["ts_code", "trade_date"]
    if _api == "tdx_index":
        keys.append("idx_type")
    if _api in ("tdx_member", "kpl_concept_cons"):
        keys.append("con_code")
    if _api == "kpl_list":
        keys.extend(("tag", "lu_time", "ld_time", "open_time", "last_time", "lu_desc"))
    if _api in ("ths_hot", "dc_hot"):
        keys.extend(("data_type", "rank_time", "rank"))
    protected = {"ts_code", "trade_date"}
    if _api in ("tdx_member", "kpl_concept_cons"):
        protected.add("con_code")
    if _api in ("ths_hot", "dc_hot"):
        protected.add("rank_time")
    spec = _contract(
        _cap,
        keys,
        required=FIELDS[_api],
        nullable=[field for field in FIELDS[_api] if field not in protected],
        extra=FIELDS[_api],
        rpm=30,
        split=_api in ("tdx_member", "tdx_daily", "kpl_list"),
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[
            field
            for field, meta in FIELD_METADATA[_api].items()
            if meta["default"] != "Y"
        ],
        field_metadata=FIELD_METADATA[_api],
        dependencies=[],
        required_params=list(VARIANTS[_api][0]),
        request_identity_fields=list(VARIANTS[_api][0]),
        preserve_distinct_rows=True,
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        permission_gap="Point thresholds are documented, actual account access and any separate rights are unprobed. Local30rpm is a conservative ceiling, not a measured account quota.",
        date_field="trade_date",
        split_axis="trade_date",
        history_bound_verified=False,
        history_partition="exact_day_v1",
        history_gap="No exact historical lower bound is documented. Example dates are not earliest records; explicit history_start is requested scope only. Without scope, plan recent days and retain unknown-history gap.",
        pagination_gap="No offset/limit is documented. Use only exact trade_date, legal range parameters where offered and lawful source-code filters; terminal saturation remains unresolved.",
        field_selection_note="All reviewed output columns are defaultY; explicitly request the entire list, including digit-leading field names. Do not use fields='' to prove presence; retain extra supplier columns, signed values and nullable values.",
        field_gaps={
            field: [
                "actual_field_presence_unprobed",
                "availability_revision_unverified",
            ]
            for field in FIELDS[_api]
        },
        pit_gap="trade_date/rank_time/observed_at are different clocks. Historical rows do not establish original publication time or immutable taxonomy. These commercial boards/rankings are not RRG industry membership PIT or strategy eligibility evidence.",
        identity_gap="No globally unique event/ranking ID is supplied. Preserve distinct source rows and request dimensions; equal-valued raw event multiplicity is not proven by content-hash deduplication.",
        refresh_gap="Seven recent calendar days overlap; old revisions, deletions, retired boards and earlier snapshots remain unverified. Do not drop weekends/foreign sessions via a mainland-only calendar assumption.",
        unit_note="Preserve documented per-field source descriptions and original scales. Unstated units, currencies, adjustment and formulas remain unknown; do not infer units by copying another provider/API.",
    )
    if _api.startswith("tdx_"):
        spec.update(
            saturation_fallback="tdx_indices",
            saturation_param="ts_code",
            saturation_dependencies=["tdx_indices"],
            namespace_note="TDX board ts_code is a provider-specific opaque xxxxxx.TDX identity, never an A-share/THS/DC/KP alias. Retain source_ts_code. con_code is a separate member identity, whose original suffix/T/retired spelling must remain available.",
            discovery_gap="All-date/category requests do not depend on current board lists. Saturation fanout needs stored tdx_index/tdx_daily/tdx_member source observations including historical/removed boards; observed boards are not a complete universe.",
        )
    MARKET_SENTIMENT_CONTRACTS[_api] = spec

MARKET_SENTIMENT_CONTRACTS["tdx_index"].update(
    category_gap="Explicitly request all four input literals; 地区板块 is not DC's 地域板块. Input/output category correspondence and exhaustive future categories remain unverified.",
    unit_note="total_share/float_share: hundred-million shares; total_mv/float_mv: hundred-million monetary units, currency unstated. idx_count is a source count, not a proven complete historical member universe.",
    saturation_gap="No start_date/end_date input. A full date/type partition can fan out only observed TDX boards; same-board/day/type saturation has no documented second filter.",
)
MARKET_SENTIMENT_CONTRACTS["tdx_member"].update(
    date_axis_note="trade_date and start/end describe source snapshot dates; no in_date/out_date/weight or first-publication timestamp is provided. A historical snapshot is not an effective membership interval.",
    saturation_gap="Date ranges can bisect to exact dates, then observed board codes. con_code is a legal second filter but its historical member universe is unknown; generic second-dimension fanout is not implemented and must remain a gap.",
    member_namespace_note="Examples include SH/SZ/BJ members. Preserve historical/T/source-observed members without current-stock filtering; unknown future formats require validation instead of invented A-share conversion.",
)
MARKET_SENTIMENT_CONTRACTS["tdx_daily"].update(
    unit_note="OHLC/pre_close are index points; pct_change/rise/turnover_rate/swing/horizon changes are percent; vol is lots. amount is ten-thousand monetary units BUT documentation says futures indices store open interest there. Shares and market values are hundred-million units. bm_buy_net is yuan; bm_net unit not stated. pe/pb/rise are source strings. Do not force this mixed board set into one amount/currency/asset interpretation.",
    catalog_review_note="On 2026-09-09 the catalog parser and saved catalog were corrected against the unchanged official HTML: all38 fields now include 3day/5day/10day/20day/60day/1year. See docs/tushare-catalog-numeric-fields.md. Full response and historical coverage still require runtime evidence.",
    field_name_note="Keep exact source names 3day/5day/10day/20day/60day/1year. Existing fixed-store quoted identifiers support digit-leading columns; no renaming to Python identifiers.",
    formula_gap="Index weighting, constituents effective time, adjustments, horizon-return calculation, valuation exclusions and main-buy/main-force formulas are undocumented.",
    saturation_gap="At cap use legal date bisection and observed TDX board fanout. Single-board/day has no further documented filter or pagination.",
)
MARKET_SENTIMENT_CONTRACTS["kpl_list"].update(
    documented_quota_tiers=[
        {"minimum_points": 5000, "requests_per_minute": 200, "daily_requests": 10000},
        {
            "minimum_points": 8000,
            "requests_per_minute": 500,
            "daily_requests": None,
            "daily_unlimited_documented": True,
        },
    ],
    saturation_fallback="market_sentiment_stocks",
    saturation_param="ts_code",
    saturation_dependencies=["market_sentiment_stocks"],
    category_gap="Request all five tag literals, not just default涨停. Returned tag is described merely as标签, so preserve immutable requesttag and audit correspondence; states/themes/reasons may be multi-valued strings.",
    discovery_gap="Saturated date/tag partitions need historical/delisted/T stocks plus source-observed KP securities. Current listings cannot establish that universe complete.",
    namespace_note="ts_code is a source security identity, independent of theme strings. Theme names are not KP concept IDs or historically effective industry membership.",
    unit_note="net_change/bid_amount are yuan; pct_chg/bid_pct_chg/rt_pct_chg/bid_turnover/turnover_rate percent. Other order/float/amount/net fields have unstated unit/scale; do not infer all values are yuan or shares.",
    date_axis_note="trade_date is supplier trading date; lu_time/ld_time/open_time/last_time are source time strings. Keep partial/empty times and multiple reasons; source update time/timezone and actual availability not documented.",
    saturation_gap="Legal date ranges and stock fanout preserve request tag; single-stock/day/tag saturation cannot split on output-only theme/reason/time.",
)
MARKET_SENTIMENT_CONTRACTS["kpl_concept_cons"].update(
    saturation_fallback="kpl_concepts",
    saturation_param="ts_code",
    saturation_dependencies=["kpl_concepts"],
    namespace_note="ts_code is opaque xxxxxx.KP board identity, distinct from member con_code. Do not alias a missing KP master API, DC member API or theme names as board discovery.",
    discovery_gap="Start with legal all-board date requests; official sample has3000rows exactly at cap. Stored KP board observations can drive code fanout but are not a complete historical master, especially if the source date response is truncated.",
    member_namespace_note="Input describes xxxxxx.SH but examples also contain SZ. Keep source con_code; verify BJ/T/other return spellings rather than rejecting historical members by current universe.",
    schema_gap="Output table says con_name/desc/hot_num, while example header uses ts_name and omits desc/hot_num. Request all seven documented fields; if actual response only has ts_name, retain it as extra and mark missing con_name instead of inventing an alias.",
    date_axis_note="Only exact trade_date is a legal date filter; no start/end or member-effective dates/weights. Daily snapshots/descriptions/popularity do not establish historical publication or RRG PIT membership.",
    saturation_gap="Date is already exact. Board ts_code then member con_code filters are legal, but complete board/member universes and generic second-dimension fanout are unresolved. Never mark3000-row source sample complete.",
)
for _api in ("ths_hot", "dc_hot"):
    MARKET_SENTIMENT_CONTRACTS[_api].update(
        ranking_markets=THS_MARKETS if _api == "ths_hot" else DC_MARKETS,
        date_axis_note="trade_date is requested source day; rank_time is the actual source ranking capture label, not the transaction date or when a client could know it. Preserve both and source timezone/precision uncertainty.",
        category_gap="Request every documented market and both is_new=Y/N; DC also both hot_type. Output data_type does not establish equality with market/hot_type or Y/N; dimensions omitted from outputs must remain in immutable request identity.",
        namespace_note="Use request market to keep A securities, ETFs/funds, convertibles, boards, futures, HK and US in separate namespaces. Preserve source_ts_code and market; numeric/stock-shaped symbols in board/foreign markets must not be blindly converted as mainland stocks. Runtime normalization is not implemented by this pure module.",
        intraday_gap="Intro says4intraday+4postclose captures/latest22:00; parameter table says N every2hours and Y22:30. No exact complete timetable/timezone/history availability is guaranteed. One daily pull cannot certify every intermediate ranking snapshot, even if N returns multiple rank_time rows.",
        saturation_gap="Only exact date/market/is_new (plus DC hot_type) and optional ts_code are documented. No range, rank_time, rank, offset or limit filter. Cross-market source-code fanout needs a complete universe for that exact market; generic stock-only fallback is unsafe and intentionally undeclared. Single-code saturation remains blocked.",
        discovery_gap="Market-specific historical source subjects and ranking timestamps are unknown; returned top lists or current stocks do not establish their complete universe. Do not silently skip non-A markets or is_new=N to avoid saturation.",
    )
MARKET_SENTIMENT_CONTRACTS["ths_hot"]["unit_note"] = (
    "pct_change is percent; current_price currency depends on source market. hot scoring, concept-string encoding and ranking/reason formulas are unstated; retain original strings, signed/null values and raw metadata."
)
MARKET_SENTIMENT_CONTRACTS["dc_hot"]["unit_note"] = (
    "rank is documented as ranking OR heat, not always an ordinal. pct_change percent; current_price currency/quote units depend on market. hot_type mapping and source score/price formulas are unknown."
)


def _enabled(config):
    values = config.get("market_sentiment_apis", tuple(MARKET_SENTIMENT_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(api, str) or api not in MARKET_SENTIMENT_CONTRACTS
        for api in values
    ):
        raise ValueError("market_sentiment_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("market_sentiment_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "market_sentiment_history_start must be YYYYMMDD or API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - MARKET_SENTIMENT_CONTRACTS.keys():
        raise ValueError("Unknown API history scope")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        result[api] = _parse(value) if value is not None else None
    return result


def market_sentiment_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["market_sentiment_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = MARKET_SENTIMENT_CONTRACTS[api]
        for kind, detail in spec.items():
            if kind.endswith("_gap"):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": detail,
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
        if spec.get("saturation_fallback"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "saturation_discovery_unverified",
                    "saturation_dependencies": spec["saturation_dependencies"],
                    "universe_complete": False,
                }
            )
    return gaps


def _params(api, begin, end):
    for day in _days(begin, end):
        for variant in VARIANTS[api]:
            yield {**day, **variant}


def iter_market_sentiment_jobs(config, today, identifiers=None):
    """Round-robin complete categories over recent7 then lazy explicit history."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(value and value > today for value in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            start = starts[api]
            if history:
                if start and start < recent:
                    streams[api] = iter(_params(api, start, recent - timedelta(days=1)))
            else:
                streams[api] = iter(_params(api, max(start or recent, recent), today))
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
