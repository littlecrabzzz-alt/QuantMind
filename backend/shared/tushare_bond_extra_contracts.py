"""Pure convertible holders/ratings, bond transactions, curves and historical quotes.

No provider access, current-account entitlement or historical completeness claim.
"""

from datetime import date, datetime, timedelta

from backend.shared.tushare_market_contracts import _codes
from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_technical_extra_contracts import _days

SOURCE_HTML_SHA256 = {
    "top10_cb_holders": "473e1add1765855490560a2521f2e794e5c2d468ac98df822e28e48af25d396d",
    "cb_rating": "3c4eb3a8dcad0e5c3f64c25f06256d3461d0d91dc70d5f73d3d63cd83c12b7cb",
    "repo_daily": "e3882534637261d360475d5707339d0732f3b54af3f6615233dbb11a77e890ba",
    "bond_blk": "5b158da91011539b84cf8e6850331215112b87122a0ffd55d4ee8ad494ec542e",
    "bond_blk_detail": "03c488a5340ced35881e0da9753e827d42becd40d88de987a3aa8d1a0482ccd1",
    "yc_cb": "f29399ca0402aa95aadb718590a291d5b27687e55dbbf126118d384eb5a8e3fe",
    "bc_otcqt": "5a53292cdce3aecb3aa4b18be9b1c7103693557043b5e897b777b98de6aef222",
    "bc_bestotcqt": "d26cda769f97faf24860950c396fe3d79b378f73e6aa1166bfebb142221496f6",
}

INPUT_METADATA = {
    "top10_cb_holders": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "TS代码，支持多值输入，如110059.SH,110060.SH",
        },
        "period": {
            "type": "str",
            "required": "N",
            "description": "报告期（YYYYMMDD格式，年中和年报日期，如20240630,20251231）",
        },
        "start_date": {"type": "str", "required": "N", "description": "报告期开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "报告期结束日期"},
    },
    "cb_rating": {
        "ts_code": {
            "type": "str",
            "required": "Y",
            "description": "转债代码，支持多值输入",
        }
    },
    "repo_daily": {
        "ts_code": {"type": "str", "required": "N", "description": "TS代码"},
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期(YYYYMMDD格式，下同)",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "bond_blk": {
        "ts_code": {"type": "str", "required": "N", "description": "债券代码"},
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期（YYYYMMDD格式，下同）",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "bond_blk_detail": {
        "ts_code": {"type": "str", "required": "N", "description": "债券代码"},
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期（YYYYMMDD格式，下同）",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
    },
    "yc_cb": {
        "ts_code": {
            "type": "str",
            "required": "N",
            "description": "收益率曲线编码：1001.CB-国债收益率曲线",
        },
        "curve_type": {
            "type": "str",
            "required": "N",
            "description": "曲线类型：0-到期，1-即期",
        },
        "trade_date": {"type": "str", "required": "N", "description": "交易日期"},
        "start_date": {"type": "str", "required": "N", "description": "查询起始日期"},
        "end_date": {"type": "str", "required": "N", "description": "查询结束日期"},
        "curve_term": {"type": "float", "required": "N", "description": "期限"},
    },
    "bc_otcqt": {
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "交易日期(YYYYMMDD格式，下同)",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
        "ts_code": {"type": "str", "required": "N", "description": "TS代码"},
        "bank": {"type": "str", "required": "N", "description": "报价机构"},
    },
    "bc_bestotcqt": {
        "trade_date": {
            "type": "str",
            "required": "N",
            "description": "报价日期(YYYYMMDD格式，下同)",
        },
        "start_date": {"type": "str", "required": "N", "description": "开始日期"},
        "end_date": {"type": "str", "required": "N", "description": "结束日期"},
        "ts_code": {"type": "str", "required": "N", "description": "TS代码"},
    },
}

FIELD_METADATA = {
    "top10_cb_holders": {
        "ts_code": {"type": "str", "default": "Y", "description": "转债代码"},
        "end_date": {"type": "str", "default": "Y", "description": "报告期"},
        "holder_rank": {"type": "int", "default": "Y", "description": "持有排名"},
        "holder_name": {"type": "str", "default": "Y", "description": "持有人名称"},
        "hold_amount": {
            "type": "float",
            "default": "Y",
            "description": "持有数量(万张)",
        },
        "hold_ratio": {"type": "float", "default": "Y", "description": "持有比例(%)"},
    },
    "cb_rating": {
        "ts_code": {"type": "str", "default": "Y", "description": "转债代码"},
        "ann_date": {"type": "str", "default": "Y", "description": "评级发布日期"},
        "rating_date": {"type": "str", "default": "Y", "description": "评级日期"},
        "rating_com_name": {"type": "str", "default": "Y", "description": "评级机构"},
        "rating_way": {"type": "str", "default": "Y", "description": "评级方式"},
        "rating_type": {"type": "str", "default": "Y", "description": "评级类别"},
        "rating": {"type": "str", "default": "Y", "description": "信用等级"},
        "rating_outlook": {"type": "str", "default": "Y", "description": "评级展望"},
    },
    "repo_daily": {
        "ts_code": {"type": "str", "default": "Y", "description": "TS代码"},
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "repo_maturity": {"type": "str", "default": "Y", "description": "期限品种"},
        "pre_close": {"type": "float", "default": "Y", "description": "前收盘(%)"},
        "open": {"type": "float", "default": "Y", "description": "开盘价(%)"},
        "high": {"type": "float", "default": "Y", "description": "最高价(%)"},
        "low": {"type": "float", "default": "Y", "description": "最低价(%)"},
        "close": {"type": "float", "default": "Y", "description": "收盘价(%)"},
        "weight": {"type": "float", "default": "Y", "description": "加权价(%)"},
        "weight_r": {
            "type": "float",
            "default": "Y",
            "description": "加权价(利率债)(%)",
        },
        "amount": {"type": "float", "default": "Y", "description": "成交金额(万元)"},
        "num": {"type": "int", "default": "Y", "description": "成交笔数(笔)"},
    },
    "bond_blk": {
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "ts_code": {"type": "str", "default": "Y", "description": "债券代码"},
        "name": {"type": "str", "default": "Y", "description": "债券名称"},
        "price": {"type": "float", "default": "Y", "description": "成交价（元）"},
        "vol": {
            "type": "float",
            "default": "Y",
            "description": "累计成交数量（万股/万份/万张/万手）",
        },
        "amount": {
            "type": "float",
            "default": "Y",
            "description": "累计成交金额（万元）",
        },
    },
    "bond_blk_detail": {
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "ts_code": {"type": "str", "default": "Y", "description": "债券代码"},
        "name": {"type": "str", "default": "Y", "description": "债券名称"},
        "price": {"type": "float", "default": "Y", "description": "成交价（元）"},
        "vol": {
            "type": "float",
            "default": "Y",
            "description": "成交数量（万股/万份/万张/万手）",
        },
        "amount": {"type": "float", "default": "Y", "description": "成交金额（万元）"},
        "buy_dp": {"type": "str", "default": "Y", "description": "买方营业部"},
        "sell_dp": {"type": "str", "default": "Y", "description": "卖方营业部"},
    },
    "yc_cb": {
        "trade_date": {"type": "str", "default": "Y", "description": "交易日期"},
        "ts_code": {"type": "str", "default": "Y", "description": "曲线编码"},
        "curve_name": {"type": "str", "default": "Y", "description": "曲线名称"},
        "curve_type": {
            "type": "str",
            "default": "Y",
            "description": "曲线类型：0-到期，1-即期",
        },
        "curve_term": {"type": "float", "default": "Y", "description": "期限(年)"},
        "yield": {"type": "float", "default": "Y", "description": "收益率(%)"},
    },
    "bc_otcqt": {
        "trade_date": {"type": "str", "default": "N", "description": "报价日期"},
        "qt_time": {"type": "str", "default": "N", "description": "报价时间"},
        "bank": {"type": "str", "default": "N", "description": "报价机构"},
        "ts_code": {"type": "str", "default": "N", "description": "债券编码"},
        "name": {"type": "str", "default": "N", "description": "债券简称"},
        "maturity": {"type": "str", "default": "N", "description": "期限"},
        "remain_maturity": {"type": "str", "default": "N", "description": "剩余期限"},
        "bond_type": {"type": "str", "default": "N", "description": "债券类型"},
        "coupon_rate": {
            "type": "float",
            "default": "N",
            "description": "票面利率（%）",
        },
        "buy_price": {"type": "float", "default": "N", "description": "投资者买入全价"},
        "sell_price": {
            "type": "float",
            "default": "N",
            "description": "投资者卖出全价",
        },
        "buy_yield": {
            "type": "float",
            "default": "N",
            "description": "投资者买入到期收益率（%）",
        },
        "sell_yield": {
            "type": "float",
            "default": "N",
            "description": "投资者卖出到期收益率（%）",
        },
    },
    "bc_bestotcqt": {
        "trade_date": {"type": "str", "default": "N", "description": "报价日期"},
        "ts_code": {"type": "str", "default": "N", "description": "债券编码"},
        "name": {"type": "str", "default": "N", "description": "债券简称"},
        "remain_maturity": {"type": "str", "default": "N", "description": "剩余期限"},
        "bond_type": {"type": "str", "default": "N", "description": "债券类型"},
        "best_buy_bank": {"type": "str", "default": "N", "description": "最优报买价方"},
        "best_buy_yield": {
            "type": "float",
            "default": "N",
            "description": "投资者最优买入价到期收益率（%）",
        },
        "best_buy_price": {
            "type": "float",
            "default": "Y",
            "description": "投资者最优买入全价",
        },
        "best_sell_bank": {
            "type": "str",
            "default": "N",
            "description": "最优卖报价方",
        },
        "best_sell_yield": {
            "type": "float",
            "default": "N",
            "description": "投资者最优卖出价到期收益率（%）",
        },
        "best_sell_price": {
            "type": "float",
            "default": "Y",
            "description": "投资者最优卖出全价",
        },
    },
}

FIELDS = {api: list(table) for api, table in FIELD_METADATA.items()}
INPUT_FIELDS = {api: list(table) for api, table in INPUT_METADATA.items()}
CONVERTIBLE_APIS = ("top10_cb_holders", "cb_rating")
_DOCS = {
    "top10_cb_holders": (
        459,
        3000,
        5000,
        "end_date",
        ("ts_code", "end_date", "holder_rank", "holder_name"),
    ),
    "cb_rating": (
        458,
        3000,
        2000,
        "ann_date",
        (
            "ts_code",
            "ann_date",
            "rating_date",
            "rating_com_name",
            "rating_way",
            "rating_type",
        ),
    ),
    "repo_daily": (
        256,
        2000,
        2000,
        "trade_date",
        ("ts_code", "trade_date", "repo_maturity"),
    ),
    "bond_blk": (
        271,
        1000,
        5000,
        "trade_date",
        ("ts_code", "trade_date", "price", "vol", "amount"),
    ),
    "bond_blk_detail": (
        272,
        1000,
        5000,
        "trade_date",
        ("ts_code", "trade_date", "price", "vol", "amount", "buy_dp", "sell_dp"),
    ),
    "yc_cb": (
        201,
        2000,
        None,
        "trade_date",
        ("ts_code", "trade_date", "curve_type", "curve_term"),
    ),
    "bc_otcqt": (
        322,
        2000,
        500,
        "trade_date",
        ("ts_code", "trade_date", "qt_time", "bank"),
    ),
    "bc_bestotcqt": (
        323,
        2000,
        500,
        "trade_date",
        ("ts_code", "trade_date", "best_buy_bank", "best_sell_bank"),
    ),
}
BOND_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _axis, _keys) in _DOCS.items():
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in ("ts_code", _axis)],
        extra=FIELDS[_api],
        rpm=30,
        split=_api != "cb_rating",
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[
            f for f, m in FIELD_METADATA[_api].items() if m["default"] != "Y"
        ],
        field_metadata=FIELD_METADATA[_api],
        required_params=["ts_code"]
        if _api in CONVERTIBLE_APIS
        else ["curve_type"]
        if _api == "yc_cb"
        else [],
        request_identity_fields=["curve_type"] if _api == "yc_cb" else [],
        preserve_distinct_rows=True,
        date_field=_axis,
        split_axis=_axis,
        dependencies=["bonds"] if _api in CONVERTIBLE_APIS else [],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission="ChinaBond yield-curve separate permission; contact provider administrator"
        if _api == "yc_cb"
        else None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        permission_gap="Documented points are eligibility descriptions only; actual account rights, daily limits and request frequency remain unprobed. Local30rpm is a conservative ceiling, not measured capacity.",
        history_start=None,
        history_bound_verified=False,
        history_gap="Official earliest date is unspecified. Examples are not lower bounds. An explicit history_start is requested scope only; lack of an empty response or a cap does not prove complete history.",
        pagination_gap="No offset/limit/page input is documented. Use only legal date ranges, exact dates and optional source-code filters. Terminal saturated partitions remain unresolved.",
        identity_gap="No immutable supplier record identifier is documented. Preserve distinct source rows as well as natural keys; content hashes do not prove equal-valued trade multiplicity or reconstruct removed records.",
        pit_gap="Report, rating, announcement, quote and collection dates are distinct. Original availability/revisions are unverified; observed_at does not turn historical records into point-in-time evidence.",
        refresh_gap="Recent overlap is finite; older revisions, deletions and newly discovered retired instruments require further coverage audit. No published update clock or earliest immutable observation is established.",
        unit_note="Preserve every source scalar and per-field documented unit. Do not round curve_term, rescale percentages or guess a currency/par value/lot size for fields whose units are not stated.",
        field_selection_note="Explicitly request every known column including defaultN fields; keep additional source columns and nulls. fields='' or a short example cannot establish field completeness.",
        field_gaps={
            f: ["actual_field_presence_unprobed", "availability_revision_unverified"]
            for f in FIELDS[_api]
        },
        update_status="no_stop_notice_in_reviewed_page_current_freshness_unverified",
    )
    BOND_EXTRA_CONTRACTS[_api] = spec

for _api in CONVERTIBLE_APIS:
    BOND_EXTRA_CONTRACTS[_api].update(
        source_namespace="CB:<original ts_code>",
        namespace_note="Only the convertible master and verified convertible source observations populate bonds. Preserve delisted/redeemed/historical/T supplier codes; never infer a mainland equity from its six-digit SH/SZ spelling. Namespace conversion belongs to future runtime integration, not this pure planner.",
        discovery_gap="Requires cb_basic plus historical convertible source observations, including redeemed/retired issues. Current listings and returned holders/ratings are not a complete historical convertible universe.",
    )
BOND_EXTRA_CONTRACTS["top10_cb_holders"].update(
    date_note="period and start_date/end_date filter report end_date, never ann_date. Documented reports are interim/annual; range planning avoids inventing quarterly reports or excluding nonstandard observed period dates. Output lacks announcement time.",
    unit_note="hold_amount is ten-thousand bonds (万张); hold_ratio is percent, not decimal. Do not substitute stock shares or assume a bond face value.",
    recent_partition="per_code_report_range_previous_calendar_year_through_today",
    history_partition="per_code_explicit_report_range_before_recent_window",
    saturation_gap="3000-row per-code report range must bisect by report date; period is a legal exact report filter. Single-code/report cap cannot split holder rank/name (output-only); observed periods do not prove the period universe.",
)
BOND_EXTRA_CONTRACTS["cb_rating"].update(
    date_note="Output ann_date is rating publication, rating_date is rating assessment. Neither is a legal request filter; only required ts_code (including optional comma-separated codes) is documented.",
    documentation_gap="Interface/header/input/output define cb_rating, but the example calls cb_daily with rating fields and omits rating_way/rating_type in displayed results. This is an unresolved example error, not an alias or permission grant for cb_daily.",
    history_scope_gap="Only code is filterable: one request necessarily asks for all available ratings, even if configured history_start is later. Never add ann_date/start_date/end_date/period/offset to enforce a nonexistent filter.",
    saturation_gap="3000-row single-convertible result has no documented smaller date/page/rating filter. Requesting one code already avoids multi-code saturation; terminal cap stays blocked.",
)
for _api, _namespace, _discovery in (
    ("repo_daily", "REPO", "repo_instruments"),
    ("bond_blk", "BOND", "bond_trade_instruments"),
    ("bond_blk_detail", "BOND", "bond_trade_instruments"),
    ("yc_cb", "YC", "bond_curves"),
    ("bc_otcqt", "BOND", "otc_bonds"),
    ("bc_bestotcqt", "BOND", "otc_bonds"),
):
    BOND_EXTRA_CONTRACTS[_api].update(
        source_namespace=_namespace + ":<original ts_code>",
        namespace_note="Preserve opaque supplier source code in its declared asset namespace, including SH/SZ/IB/BC or unsuffixed curve labels. Neither numeric-looking bond/repo IDs nor yield-curve IDs are A-share stock codes. Cross-venue equivalence requires an audited mapping.",
        saturation_fallback=_discovery,
        saturation_param="ts_code",
        saturation_dependencies=[_discovery],
        discovery_gap="Initial date requests need no guessed master or current-stock list. Source-observed instruments can support later fanout, but their full historical universe is unknown and cannot certify a saturated parent complete.",
        saturation_gap="At cap, legal ranges may bisect to exact days, then only observed source codes may fan out. A single-code/day result has no documented offset; do not claim its cap resolved without a validated further filter/universe.",
    )
BOND_EXTRA_CONTRACTS["repo_daily"].update(
    unit_note="pre_close/open/high/low/close/weight/weight_r are percent rates, not equity prices; amount is ten-thousand currency units (万元), num is transactions. weight_r refers to interest-rate bonds. repo_maturity is an opaque tenor label; do not parse it as an equity identifier or calendar maturity.",
    coverage_gap="Examples cover exchange SH/SZ and interbank IB repo tenors. A stock calendar/master or CB-only code list does not cover this market.",
)
BOND_EXTRA_CONTRACTS["bond_blk"].update(
    unit_note="price is yuan; amount is 万元. vol documentation says 万股/万份/万张/万手 without per-instrument choice, so retain original scale and unknown instrument lot unit. Page calls vol/amount cumulative yet shows multiple same-code/day trades; never aggregate them into one row.",
)
BOND_EXTRA_CONTRACTS["bond_blk_detail"].update(
    coverage_gap="Official note says this endpoint currently includes only Shenzhen details; Shanghai details are included in bond_blk. They are complementary APIs, not aliases; do not manufacture Shanghai rows or claim both independently cover both exchanges.",
    unit_note="price yuan, amount万元; vol could 万股/万份/万张/万手 per page, mapping unspecified. buy_dp/sell_dp are source department strings, not persistent institution IDs; preserve empty or revised labels.",
)
BOND_EXTRA_CONTRACTS["yc_cb"].update(
    permission_gap="This API explicitly requires independent permission. User points and purchased news/reports/announcements rights do not establish ChinaBond-curve permission. Remain unprobed until separately tested/authorized.",
    curve_types=["0", "1"],
    documentation_gap="Input documents 1001.CB but sample output ts_code is101; example requests curve_type0 yet displayed tail contains1. Preserve source IDs and immutable requested curve_type; mapping/filter behavior must be probed rather than assuming equivalence or dropping rows.",
    unit_note="curve_term is years (floating tenor, including0), yield is percent. Preserve decimal/scalar representation and do not assume a uniform tenor grid or convert to bond prices.",
    saturation_gap="Legal date/type/code filters preserve curve_type0/1 identity. curve_term is an optional exact numeric filter, but its full continuous/discrete source grid is unknown; do not invent a tenor grid or generic term fanout. Terminal saturated code/day/type remains unresolved.",
)
for _api in ("bc_otcqt", "bc_bestotcqt"):
    BOND_EXTRA_CONTRACTS[_api]["permission_gap"] = (
        "The page describes500points for trial and2000points for relatively higher frequency, not a full permission/quota guarantee. Exact frequency/daily limits and current account entitlement remain unprobed; local30rpm is only an operational ceiling."
    )

BOND_EXTRA_CONTRACTS["bc_otcqt"].update(
    historical_quote_note="Historical date/range endpoint includes qt_time per bank; no minute subscription or live polling is introduced. Trading/quote date and within-day quote time are distinct; quote timezone and completeness/update cadence are undocumented.",
    saturation_gap="Date range/day/code filters are legal; bank is a legal further filter but complete historic bank universe and generic second-dimension split are unimplemented. qt_time is output-only, not a pagination cursor. Terminal code/day/bank saturation remains unresolved.",
    unit_note="coupon_rate/buy_yield/sell_yield are percentages. buy_price/sell_price are investor full prices; currency, face-value basis, accrued-interest convention and executable size are unspecified. Keep maturity/remain_maturity textual values.",
)
BOND_EXTRA_CONTRACTS["bc_bestotcqt"].update(
    historical_quote_note="Historical date/range best-quote snapshots have no within-day timestamp. They do not reconstruct every intraday best quote or prove executable prices. Bank identity changes must remain visible.",
    unit_note="best_buy_yield/best_sell_yield percent; best_buy_price/best_sell_price investor full prices, currency/par/accrued-interest basis unspecified. Preserve buy/sell perspective exactly, without swapping sides to a dealer perspective.",
)


def _enabled(config):
    selected = config.get("bond_extra_apis", tuple(BOND_EXTRA_CONTRACTS))
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(a, str) or a not in BOND_EXTRA_CONTRACTS for a in selected
    ):
        raise ValueError("bond_extra_apis must list known APIs")
    return tuple(dict.fromkeys(selected))


def _starts(config, enabled):
    setting = config.get("bond_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("bond_extra_history_start must be YYYYMMDD or API mapping")
    if isinstance(setting, dict) and setting.keys() - BOND_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API history scope")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = config.get("history_start") if value is None else value
        starts[api] = _parse(value) if value is not None else None
    return starts


def bond_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["bond_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    bonds = (
        _codes(identifiers or {}, "bonds")
        if set(enabled) & set(CONVERTIBLE_APIS)
        else []
    )
    gaps = []
    for api in enabled:
        spec = BOND_EXTRA_CONTRACTS[api]
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
        if api in CONVERTIBLE_APIS:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["bonds"],
                    "reason": "historical_convertible_discovery_unverified",
                    "observed_codes": len(bonds),
                    "universe_complete": False,
                }
            )
        elif spec.get("saturation_fallback"):
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


def _daily(api, begin, end):
    for params in _days(begin, end):
        for variant in (
            ({"curve_type": "0"}, {"curve_type": "1"}) if api == "yc_cb" else ({},)
        ):
            yield {**params, **variant}


def _reports(begin, end, bonds):
    if begin <= end:
        for code in bonds:
            yield {
                "ts_code": code,
                "start_date": begin.strftime("%Y%m%d"),
                "end_date": end.strftime("%Y%m%d"),
            }


def iter_bond_extra_jobs(config, today, identifiers=None):
    """Lazy recent7 daily slices, overlapping report ranges, code-only ratings.

    identifiers['bonds'] is the existing convertible discovery family, accepting
    raw cb_basic records and source strings without filtering retired/T issues.
    History dates are requested scope, not fabricated earliest-data claims.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(value and value > today for value in starts.values()):
        raise ValueError("History start cannot be after today")
    bonds = (
        _codes(identifiers or {}, "bonds")
        if set(enabled) & set(CONVERTIBLE_APIS)
        else []
    )
    recent = today - timedelta(days=6)
    report_recent = date(max(1, today.year - 1), 1, 1)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            start = starts[api]
            if api == "cb_rating":
                if not history:
                    streams[api] = ({"ts_code": code} for code in bonds)
            elif api == "top10_cb_holders":
                if history:
                    if start and start < report_recent:
                        streams[api] = iter(
                            _reports(start, report_recent - timedelta(days=1), bonds)
                        )
                else:
                    streams[api] = iter(
                        _reports(
                            max(start or report_recent, report_recent), today, bonds
                        )
                    )
            elif history:
                if start and start < recent:
                    streams[api] = iter(_daily(api, start, recent - timedelta(days=1)))
            else:
                streams[api] = iter(_daily(api, max(start or recent, recent), today))
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
