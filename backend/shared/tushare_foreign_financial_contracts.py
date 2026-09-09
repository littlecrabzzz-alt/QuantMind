"""Pure HK/US financial contracts; no runtime registration or permission assertion."""

from datetime import date, datetime, timedelta

from backend.shared.tushare_global_contracts import _identifiers, _interleave
from backend.shared.tushare_structured_contracts import _contract, _parse

# Generated from the full official output tables reviewed 2026-09-09. Each
# field occurs once in its table; selectors/types/defaults derive from this data.
# Tuple columns: supplier name, documented type, default flag, supplier meaning.
HK_STATEMENT = [
    ("ts_code", "str", "Y", "股票代码"),
    ("end_date", "str", "Y", "报告期"),
    ("name", "str", "Y", "股票名称"),
    ("ind_name", "str", "Y", "财务科目名称"),
    ("ind_value", "float", "Y", "财务科目值"),
]

US_STATEMENT = [
    ("ts_code", "str", "Y", "股票代码"),
    ("end_date", "str", "Y", "报告期"),
    ("ind_type", "str", "Y", "报告期类型(Q1一季报Q2半年报Q3三季报Q4年报)"),
    ("name", "str", "Y", "股票名称"),
    ("ind_name", "str", "Y", "财务科目名称"),
    ("ind_value", "float", "Y", "财务科目值"),
    ("report_type", "str", "Y", "报告类型"),
]

HK_INDICATOR = [
    ("ts_code", "str", "Y", "股票代码"),
    ("name", "str", "Y", "股票名称"),
    ("end_date", "str", "Y", "报告期"),
    ("ind_type", "str", "Y", "报告类型,Q-按报告期(季度),Y-按年度"),
    ("report_type", "str", "Y", "报告期类型"),
    ("std_report_date", "str", "Y", "标准报告期"),
    ("per_netcash_operate", "float", "Y", "每股经营现金流(元)"),
    ("per_oi", "float", "Y", "每股营业收入(元)"),
    ("bps", "float", "Y", "每股净资产(元)"),
    ("basic_eps", "float", "Y", "基本每股收益(元)"),
    ("diluted_eps", "float", "Y", "稀释每股收益(元)"),
    ("operate_income", "float", "Y", "营业总收入(元)"),
    ("operate_income_yoy", "float", "Y", "营业总收入同比增长(%)"),
    ("gross_profit", "float", "Y", "毛利润(元)"),
    ("gross_profit_yoy", "float", "Y", "毛利润同比增长(%)"),
    ("holder_profit", "float", "Y", "归母净利润(元)"),
    ("holder_profit_yoy", "float", "Y", "归母净利润同比增长(%)"),
    ("gross_profit_ratio", "float", "Y", "毛利率(%)"),
    ("eps_ttm", "float", "Y", "ttm每股收益(元)"),
    ("operate_income_qoq", "float", "Y", "营业总收入滚动环比增长(%)"),
    ("net_profit_ratio", "float", "Y", "净利率(%)"),
    ("roe_avg", "float", "Y", "平均净资产收益率(%)"),
    ("gross_profit_qoq", "float", "Y", "毛利润滚动环比增长(%)"),
    ("roa", "float", "Y", "总资产净利率(%)"),
    ("holder_profit_qoq", "float", "Y", "归母净利润滚动环比增长(%)"),
    ("roe_yearly", "float", "Y", "年化净资产收益率(%)"),
    ("roic_yearly", "float", "Y", "年化投资回报率(%)"),
    ("total_assets", "float", "Y", "资产总额"),
    ("total_liabilities", "float", "Y", "负债总额"),
    ("tax_ebt", "float", "Y", "所得税/利润总额(%)"),
    ("ocf_sales", "float", "Y", "经营现金流/营业收入(%)"),
    ("total_parent_equity", "float", "Y", "本公司权益持有人应占权益"),
    ("debt_asset_ratio", "float", "Y", "资产负债率(%)"),
    ("operate_profit", "float", "Y", "经营盈利"),
    ("pretax_profit", "float", "Y", "除税前盈利"),
    ("netcash_operate", "float", "Y", "经营活动所得现金流量净额"),
    ("netcash_invest", "float", "Y", "投资活动耗用现金流量净额"),
    ("netcash_finance", "float", "Y", "融资活动耗用现金流量净额"),
    ("end_cash", "float", "Y", "期末的现金及现金等价物"),
    ("divi_ratio", "float", "Y", "分红比例"),
    ("dividend_rate", "float", "Y", "股息率"),
    ("current_ratio", "float", "Y", "流动比率(倍)"),
    ("common_acs", "float", "Y", "普通股应计股息"),
    ("currentdebt_debt", "float", "Y", "流动负债/总负债(%)"),
    ("issued_common_shares", "float", "Y", "已发行普通股"),
    ("hk_common_shares", "float", "Y", "港股本(不建议使用数据源有误)"),
    ("per_shares", "float", "Y", "每手股数"),
    ("total_market_cap", "float", "Y", "总市值"),
    ("hksk_market_cap", "float", "Y", "港股市值"),
    ("pe_ttm", "float", "Y", "滚动市盈率"),
    ("pb_ttm", "float", "Y", "滚动市净率"),
    ("report_date_sq", "str", "Y", "季报日期"),
    ("report_type_sq", "str", "Y", "报告类型"),
    ("operate_income_sq", "float", "Y", "营业收入"),
    ("dps_hkd", "float", "Y", "每股股息（港元）"),
    ("operate_income_qoq_sq", "float", "Y", "营业收入环比"),
    ("net_profit_ratio_sq", "float", "Y", "净利润率"),
    ("holder_profit_sq", "float", "Y", "归属于股东净利润"),
    ("holder_profit_qoq_sq", "float", "Y", "归母净利润环比"),
    ("roe_avg_sq", "float", "Y", "平均净资产收益率"),
    ("pe_ttm_sq", "float", "Y", "季报滚动市盈率"),
    ("pb_ttm_sq", "float", "Y", "季报滚动市净率"),
    ("roa_sq", "float", "Y", "总资产收益率"),
    ("start_date", "float", "Y", "会计年度起始日"),
    ("fiscal_year", "float", "Y", "会计年度截止日"),
    ("currency", "str", "Y", "币种\u2003港元（hkd）"),
    ("is_cny_code", "float", "Y", "是否人民币代码"),
    ("dps_hkd_ly", "float", "Y", "上一年每股股息"),
    ("org_type", "str", "Y", "企业类型"),
    ("premium_income", "float", "Y", "保费收入"),
    ("premium_income_yoy", "float", "Y", "保费收入同比"),
    ("net_interest_income", "float", "Y", "净利息收入"),
    ("net_interest_income_yoy", "float", "Y", "净利息收入同比"),
    ("fee_commission_income", "float", "Y", "手续费及佣金收入"),
    ("fee_commission_income_yoy", "float", "Y", "手续费及佣金收入同比"),
    ("accounts_rece_tdays", "float", "Y", "应收账款周转率(次)"),
    ("inventory_tdays", "float", "Y", "存货周转率(次)"),
    ("current_assets_tdays", "float", "Y", "流动资产周转率(次)"),
    ("total_assets_tdays", "float", "Y", "总资产周转率(次)"),
    ("premium_expense", "float", "Y", "保险赔付支出"),
    ("loan_deposit", "float", "Y", "贷款/存款"),
    ("loan_equity", "float", "Y", "贷款/股东权益"),
    ("loan_assets", "float", "Y", "贷款/总资产"),
    ("deposit_equity", "float", "Y", "存款/股东权益"),
    ("deposit_assets", "float", "Y", "存款/总资产"),
    ("equity_multiplier", "float", "Y", "权益乘数"),
    ("equity_ratio", "float", "Y", "产权比率"),
]

US_INDICATOR = [
    ("ts_code", "str", "Y", "股票代码"),
    ("end_date", "str", "Y", "报告期"),
    ("ind_type", "str", "Y", "报告类型,Q1一季报,Q2中报,Q3三季报,Q4年报"),
    ("security_name_abbr", "str", "Y", "股票名称"),
    ("accounting_standards", "str", "Y", "会计准则"),
    ("notice_date", "str", "Y", "公告日期"),
    ("start_date", "str", "Y", "报告期开始时间"),
    ("std_report_date", "str", "Y", "标准报告期"),
    ("financial_date", "str", "Y", "年结日"),
    ("currency", "str", "Y", "币种"),
    ("date_type", "str", "Y", "报告期类型"),
    ("report_type", "str", "Y", "报告类型"),
    ("operate_income", "float", "Y", "收入"),
    ("operate_income_yoy", "float", "Y", "收入增长"),
    ("gross_profit", "float", "Y", "毛利"),
    ("gross_profit_yoy", "float", "Y", "毛利增长"),
    ("parent_holder_netprofit", "float", "Y", "归母净利润"),
    ("parent_holder_netprofit_yoy", "float", "Y", "归母净利润增长"),
    ("basic_eps", "float", "Y", "基本每股收益"),
    ("diluted_eps", "float", "Y", "稀释每股收益"),
    ("gross_profit_ratio", "float", "Y", "销售毛利率"),
    ("net_profit_ratio", "float", "Y", "销售净利率"),
    ("accounts_rece_tr", "float", "Y", "应收账款周转率(次)"),
    ("inventory_tr", "float", "Y", "存货周转率(次)"),
    ("total_assets_tr", "float", "Y", "总资产周转率(次)"),
    ("accounts_rece_tdays", "float", "Y", "应收账款周转天数"),
    ("inventory_tdays", "float", "Y", "存货周转天数"),
    ("total_assets_tdays", "float", "Y", "总资产周转天数"),
    ("roe_avg", "float", "Y", "净资产收益率"),
    ("roa", "float", "Y", "总资产净利率"),
    ("current_ratio", "float", "Y", "流动比率(倍)"),
    ("speed_ratio", "float", "Y", "速动比率(倍)"),
    ("ocf_liqdebt", "float", "Y", "经营业务现金净额/流动负债"),
    ("debt_asset_ratio", "float", "Y", "资产负债率"),
    ("equity_ratio", "float", "Y", "产权比率"),
    ("basic_eps_yoy", "float", "Y", "基本每股收益同比增长"),
    ("gross_profit_ratio_yoy", "float", "Y", "毛利率同比增长(%)"),
    ("net_profit_ratio_yoy", "float", "Y", "净利率同比增长(%)"),
    ("roe_avg_yoy", "float", "Y", "平均净资产收益率同比增长(%)"),
    ("roa_yoy", "float", "Y", "净资产收益率同比增长(%)"),
    ("debt_asset_ratio_yoy", "float", "Y", "资产负债率同比增长(%)"),
    ("current_ratio_yoy", "float", "Y", "流动比率同比增长(%)"),
    ("speed_ratio_yoy", "float", "Y", "速动比率同比增长(%)"),
    ("currency_abbr", "str", "Y", "币种"),
    ("total_income", "float", "Y", "收入总额"),
    ("total_income_yoy", "float", "Y", "收入总额同比增长"),
    ("premium_income", "float", "Y", "保费收入"),
    ("premium_income_yoy", "float", "Y", "保费收入同比"),
    ("basic_eps_cs", "float", "Y", "基本每股收益"),
    ("basic_eps_cs_yoy", "float", "Y", "基本每股收益同比增长"),
    ("diluted_eps_cs", "float", "Y", "稀释每股收益"),
    ("payout_ratio", "float", "Y", "保费收入/赔付支出"),
    ("capitial_ratio", "float", "Y", "总资产周转率"),
    ("roe", "float", "Y", "净资产收益率"),
    ("roe_yoy", "float", "Y", "净资产收益率同比增长"),
    ("debt_ratio", "float", "Y", "资产负债率"),
    ("debt_ratio_yoy", "float", "Y", "资产负债率同比增长"),
    ("net_interest_income", "float", "Y", "净利息收入"),
    ("net_interest_income_yoy", "float", "Y", "净利息收入增长"),
    ("diluted_eps_cs_yoy", "float", "Y", "稀释每股收益增长"),
    ("loan_loss_provision", "float", "Y", "贷款损失准备"),
    ("loan_loss_provision_yoy", "float", "Y", "贷款损失准备增长"),
    ("loan_deposit", "float", "Y", "贷款/存款"),
    ("loan_equity", "float", "Y", "贷款/股东权益(倍)"),
    ("loan_assets", "float", "Y", "贷款/总资产"),
    ("deposit_equity", "float", "Y", "存款/股东权益(倍)"),
    ("deposit_assets", "float", "Y", "存款/总资产"),
    ("rol", "float", "Y", "贷款回报率"),
    ("rod", "float", "Y", "存款回报率"),
]

DOCUMENTS = {
    "hk_income": (
        389,
        "9e5bb342d62e52d727542e8575dd72c7f4b678d592004f750f8099b7158a03da",
    ),
    "hk_balancesheet": (
        390,
        "5a409bf047ae1dd4770a7127ed200be16ceb86aac9404cccd3394ecaa447309b",
    ),
    "hk_cashflow": (
        391,
        "9115f941f31a99be4b198b37307459aa3834dcf91b8ad6cea9c66096fed5e098",
    ),
    "hk_fina_indicator": (
        388,
        "d653abe07dee37de9c7fa1c9c84e374f10ed8739465e2c16e75c55eb16283116",
    ),
    "us_income": (
        394,
        "459b1be0ca191d2be35075ab6595a3ec80055ed40b08e598dbabb6efcb93baee",
    ),
    "us_balancesheet": (
        395,
        "50531d91275252ca64d3165a0f0cdbe75937bc4c8e40ba131628097a2e8a6896",
    ),
    "us_cashflow": (
        396,
        "9a0e10869759addafbc2d14b8a192aa6d8b3e2a50b87da2cee9e01e07baf6f8e",
    ),
    "us_fina_indicator": (
        393,
        "c50e870d240d83acb1cda978ca110d20e97bf99cf60b82b584e804b8e4f519bf",
    ),
}

INPUT_FIELDS = {
    "hk_income": ["ts_code", "period", "ind_name", "start_date", "end_date"],
    "hk_balancesheet": ["ts_code", "period", "ind_name", "start_date", "end_date"],
    "hk_cashflow": ["ts_code", "period", "ind_name", "start_date", "end_date"],
    "hk_fina_indicator": ["ts_code", "period", "report_type", "start_date", "end_date"],
    "us_income": [
        "ts_code",
        "period",
        "ind_name",
        "report_type",
        "start_date",
        "end_date",
    ],
    "us_balancesheet": [
        "ts_code",
        "period",
        "ind_name",
        "report_type",
        "start_date",
        "end_date",
    ],
    "us_cashflow": [
        "ts_code",
        "period",
        "ind_name",
        "report_type",
        "start_date",
        "end_date",
    ],
    "us_fina_indicator": ["ts_code", "period", "report_type", "start_date", "end_date"],
}

OUTPUT_FIELDS = {}
FOREIGN_FINANCIAL_CONTRACTS = {}
for _api, (_doc, _sha) in DOCUMENTS.items():
    _indicator = _api.endswith("fina_indicator")
    _hk = _api.startswith("hk_")
    _rows = (
        (HK_INDICATOR if _hk else US_INDICATOR)
        if _indicator
        else (HK_STATEMENT if _hk else US_STATEMENT)
    )
    # The HK balance sheet lists name before end_date; preserve its source order.
    if _api == "hk_balancesheet":
        _rows = [_rows[i] for i in (0, 2, 1, 3, 4)]
    OUTPUT_FIELDS[_api] = list(_rows)
    _names = [row[0] for row in _rows]
    _keys = ["ts_code", "end_date"]
    if not _indicator:
        _keys.append("ind_name")
    if _indicator or not _hk:
        _keys += ["ind_type", "report_type"]
    if _indicator:
        _keys.append("currency")
    _spec = _contract(
        200 if _indicator else 10000,
        _keys,
        required=("ts_code", "end_date"),
        nullable=tuple(f for f in _names if f not in ("ts_code", "end_date")),
        extra=_names,
        rpm=50,
        start="20000101",
        cap_verified=not _indicator,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=_sha,
        reviewed_at="2026-09-09",
        group="foreign_financial",
        input_fields=INPUT_FIELDS[_api],
        default_fields=[r[0] for r in _rows if r[2] == "Y"],
        hidden_fields=[r[0] for r in _rows if r[2] != "Y"],
        field_types={r[0]: r[1] for r in _rows},
        field_notes={r[0]: r[3] for r in _rows},
        required_params=["ts_code"],
        pagination=None,
        documented_requests_per_minute=500,
        permission_source="https://tushare.pro/document/1?doc_id=290",
        independent_permission="港股财报" if _hk else "美股财报",
        minimum_points=None,
        permission_status="unprobed",
        rate_note="50/min local conservative ceiling; 500/min is the financial permission package specification, not verified account access. Shared account gates still apply.",
        documented_history_start_year=2000,
        history_bound_verified=False,
        history_gap="Permission table gives year 2000 only; Jan 1 is its planning envelope, not the exact earliest available report or proof that pre-2000 observations do not exist. Explicit earlier starts are allowed.",
        dependencies=["hk_stocks" if _hk else "us_stocks"],
        source_namespace="HK" if _hk else "US",
        discovery_gap="Stored basic discovery must include historical/delisted/special source identifiers and observed union. Nonempty discovery and successful leaves never establish universe completeness.",
        coverage_gap="HK listed-company coverage is not independently certified."
        if _hk
        else "Official endpoint limits coverage to major US and Chinese ADR issuers; missing smaller/delisted companies remain a source coverage gap.",
        preserve_distinct_rows=True,
        split_axis="end_date",
        date_filter_semantics="start_date/end_date filter report-period end dates, not announcement dates or the output start_date fiscal field.",
        saturation_gap="No offset/limit documented. Bisect bounded inclusive report-date ranges. A saturated single-code single-day leaf remains a gap; do not invent pagination or treat observed line-item names as the complete universe.",
        pit_gap="No immutable revision ID or publication timestamp contract. Preserve every distinct source row and observation. notice_date on US indicators is a source date, not independently verified market availability; other seven endpoints lack an announcement-date output.",
        refresh_gap="Recent report-period refresh cannot guarantee late filings or revisions of older periods. History reconciliation remains required; do not treat report end or fetched_at as PIT.",
        unit_gap="Preserve indicator currency verbatim without FX conversion. Six statement tables have no currency/unit column; do not assume HKD/USD or join a later indicator currency retroactively.",
        field_coverage_gap="All reviewed output rows are explicitly requested, including any non-default fields. The current eight pages mark every field Y; undocumented/new supplier columns still require raw preservation and field drift validation.",
        report_type_values=["Q1", "Q2", "Q3", "Q4"]
        if "report_type" in INPUT_FIELDS[_api]
        else [],
    )
    if _indicator:
        _spec["cap_gap"] = (
            "Endpoint text conflicts: 200 records in description, 10000 in hint/permission table. Use 200 as conservative saturation trigger until bounded real-return verification."
        )
    if not _hk:
        _spec["period_gap"] = (
            "Input prose mentions calendar quarter ends, but official examples include fiscal end 20250427/20050501. Preserve arbitrary valid fiscal dates; never generate only 0331/0630/0930/1231. Request report_type Q1..Q4 is not the output report_type label (e.g. 单季报)."
        )
    FOREIGN_FINANCIAL_CONTRACTS[_api] = _spec
FIELDS = {api: [row[0] for row in rows] for api, rows in OUTPUT_FIELDS.items()}


def _settings(config):
    apis = config.get("foreign_financial_apis", tuple(FOREIGN_FINANCIAL_CONTRACTS))
    if not isinstance(apis, (list, tuple)) or any(
        a not in FOREIGN_FINANCIAL_CONTRACTS for a in apis
    ):
        raise ValueError("foreign_financial_apis must list known APIs")
    starts = config.get("foreign_financial_history_start", config.get("history_start"))
    if starts is not None and not isinstance(starts, (str, dict)):
        raise ValueError("history start must be YYYYMMDD or an API mapping")
    if isinstance(starts, dict) and set(starts) - FOREIGN_FINANCIAL_CONTRACTS.keys():
        raise ValueError("Unknown history-start API")
    result = {}
    for api in dict.fromkeys(apis):
        value = starts.get(api) if isinstance(starts, dict) else starts
        result[api] = _parse(value or FOREIGN_FINANCIAL_CONTRACTS[api]["history_start"])
    recent = config.get("foreign_financial_recent_days", 400)
    if (
        isinstance(recent, bool)
        or not isinstance(recent, int)
        or not 1 <= recent <= 3660
    ):
        raise ValueError("recent days must be 1..3660")
    return result, recent


def foreign_financial_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["foreign_financial_apis"] = enabled_apis
    starts, _ = _settings(config)
    ids = _identifiers(identifiers or {})
    gaps = []
    for api in starts:
        spec = FOREIGN_FINANCIAL_CONTRACTS[api]
        dependency = spec["dependencies"][0]
        if not ids[dependency]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [dependency],
                    "reason": "awaiting_stored_historical_discovery",
                }
            )
        for kind in (
            "history_gap",
            "discovery_gap",
            "coverage_gap",
            "pit_gap",
            "refresh_gap",
            "unit_gap",
            "cap_gap",
            "period_gap",
        ):
            if spec.get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": spec[kind],
                        "universe_complete": False,
                    }
                )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "independent_permission_unprobed",
            }
        )
    return gaps


def validate_foreign_financial_request(api, params):
    if api not in FOREIGN_FINANCIAL_CONTRACTS or not isinstance(params, dict):
        raise ValueError("Unknown API or invalid params")
    if set(params) - set(INPUT_FIELDS[api]):
        raise ValueError(
            "Undocumented parameter; offset/limit and A-share VIP fields are not supported"
        )
    family = FOREIGN_FINANCIAL_CONTRACTS[api]["dependencies"][0]
    _identifiers({family: [params.get("ts_code")]})
    for key in ("period", "start_date", "end_date"):
        if key in params:
            _parse(params[key])
    if "period" in params and ("start_date" in params or "end_date" in params):
        raise ValueError("Combined period/range semantics are unverified")
    if (
        "start_date" in params
        and "end_date" in params
        and _parse(params["start_date"]) > _parse(params["end_date"])
    ):
        raise ValueError("Reversed report-date range")
    if "report_type" in params and params["report_type"] not in (
        "Q1",
        "Q2",
        "Q3",
        "Q4",
    ):
        raise ValueError(
            "Request report_type must be Q1..Q4, not a source output label"
        )
    if "ind_name" in params and (
        not isinstance(params["ind_name"], str) or not params["ind_name"].strip()
    ):
        raise ValueError("ind_name must be nonempty source text")


def split_foreign_financial_request(api, params):
    """Pure saturation candidate; caller persists parent/child evidence and gaps."""
    validate_foreign_financial_request(api, params)
    if "start_date" not in params or "end_date" not in params:
        return {
            "children": [],
            "gap": "saturated_without_bounded_report_date_range",
            "universe_complete": False,
        }
    begin, end = _parse(params["start_date"]), _parse(params["end_date"])
    if begin == end:
        return {
            "children": [],
            "gap": "saturated_single_code_report_day_no_documented_pagination",
            "universe_complete": False,
        }
    middle = begin + (end - begin) // 2
    return {
        "children": [
            dict(params, end_date=middle.strftime("%Y%m%d")),
            dict(params, start_date=(middle + timedelta(days=1)).strftime("%Y%m%d")),
        ],
        "gap": None,
        "universe_complete": False,
    }


def iter_foreign_financial_jobs(config, today, identifiers=None):
    """Lazy fair per-symbol ranges; all recent windows before stable history.

    No report-type/line-item filter on normal acquisition, so source variants are
    not discarded. A range spans every fiscal day, including non-quarter ends.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    starts, recent_days = _settings(config)
    ids = _identifiers(identifiers or {})
    end = today - timedelta(days=1)
    recent = today - timedelta(days=recent_days)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))

    def jobs(api, begin, last, priority, job_epoch):
        if begin > last:
            return
        for code in ids[FOREIGN_FINANCIAL_CONTRACTS[api]["dependencies"][0]]:
            yield {
                "api_name": api,
                "params": {
                    "ts_code": code,
                    "start_date": begin.strftime("%Y%m%d"),
                    "end_date": last.strftime("%Y%m%d"),
                },
                "priority": priority,
                "epoch": job_epoch,
            }

    yield from _interleave(
        [jobs(api, max(start, recent), end, 25, epoch) for api, start in starts.items()]
    )
    yield from _interleave(
        [
            jobs(api, start, min(end, recent - timedelta(days=1)), 45, "history")
            for api, start in starts.items()
        ]
    )
