"""Pure stock context contracts: distinct availability and input date axes.

No registry, network or storage side effects. Source suffix identifiers are used
only at the outbound query boundary; full account authorization is unprobed.
"""

from datetime import date, datetime, timedelta
import hashlib
import json
import re

from backend.shared.tushare_equity_event_contracts import _stocks
from backend.shared.tushare_structured_contracts import _contract, _parse
from backend.shared.tushare_technical_extra_contracts import _days

# Complete reviewed technical schema: field/type/default/meaning, including N.
_OUTPUT_TABLES = {
    "stk_premarket": """
trade_date|str|Y|交易日期
ts_code|str|Y|TS股票代码
total_share|float|Y|总股本（万股）
float_share|float|Y|流通股本（万股）
pre_close|float|Y|昨日收盘价
up_limit|float|Y|今日涨停价
down_limit|float|Y|今日跌停价
""",
    "stk_managers": """
ts_code|str|Y|TS股票代码
ann_date|str|Y|公告日期
name|str|Y|姓名
gender|str|Y|性别
lev|str|Y|岗位类别
title|str|Y|岗位
edu|str|Y|学历
national|str|Y|国籍
birthday|str|Y|出生年月
begin_date|str|Y|上任日期
end_date|str|Y|离任日期
resume|str|N|个人简历
""",
    "stk_rewards": """
ts_code|str|Y|TS股票代码
ann_date|str|Y|公告日期
end_date|str|Y|截止日期
name|str|Y|姓名
title|str|Y|职务
reward|float|Y|报酬（元）
hold_vol|float|Y|持股数（股）
""",
    "stk_auction_o": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
close|float|Y|开盘集合竞价收盘价
open|float|Y|开盘集合竞价开盘价
high|float|Y|开盘集合竞价最高价
low|float|Y|开盘集合竞价最低价
vol|float|Y|开盘集合竞价成交量
amount|float|Y|开盘集合竞价成交额
vwap|float|Y|开盘集合竞价均价
""",
    "stk_auction_c": """
ts_code|str|Y|股票代码
trade_date|str|Y|交易日期
close|float|Y|收盘集合竞价收盘价
open|float|Y|收盘集合竞价开盘价
high|float|Y|收盘集合竞价最高价
low|float|Y|收盘集合竞价最低价
vol|float|Y|收盘集合竞价成交量
amount|float|Y|收盘集合竞价成交额
vwap|float|Y|收盘集合竞价均价
""",
    "stk_nineturn": """
ts_code|str|Y|股票代码
trade_date|datetime|Y|交易日期
freq|str|Y|频率(日daily)
open|float|Y|开盘价
high|float|Y|最高价
low|float|Y|最低价
close|float|Y|收盘价
vol|float|Y|成交量
amount|float|Y|成交额
up_count|float|Y|上九转计数
down_count|float|Y|下九转计数
nine_up_turn|str|Y|是否上九转)+9表示上九转
nine_down_turn|str|Y|是否下九转-9表示下九转
""",
    "stk_ah_comparison": """
hk_code|str|Y|港股股票代码
ts_code|str|Y|A股股票代码
trade_date|str|Y|交易日期
hk_name|str|Y|港股股票名称
hk_pct_chg|float|Y|港股股票涨跌幅
hk_close|float|Y|港股股票收盘价
name|str|Y|A股股票名称
close|float|Y|A股股票收盘价
pct_chg|float|Y|A股股票涨跌幅
ah_comparison|float|Y|比价(A/H)
ah_premium|float|Y|溢价(A/H)%
""",
}
FIELD_METADATA = {
    api: {
        row.split("|", 3)[0]: dict(
            zip(("type", "default", "description"), row.split("|", 3)[1:], strict=True)
        )
        for row in table.strip().splitlines()
    }
    for api, table in _OUTPUT_TABLES.items()
}
FIELDS = {api: list(fields) for api, fields in FIELD_METADATA.items()}
INPUT_FIELDS = {
    "stk_premarket": ["ts_code", "trade_date", "start_date", "end_date"],
    "stk_managers": ["ts_code", "ann_date", "start_date", "end_date"],
    "stk_rewards": ["ts_code", "end_date"],
    "stk_auction_o": ["ts_code", "trade_date", "start_date", "end_date"],
    "stk_auction_c": ["ts_code", "trade_date", "start_date", "end_date"],
    "stk_nineturn": ["ts_code", "trade_date", "freq", "start_date", "end_date"],
    "stk_ah_comparison": ["hk_code", "ts_code", "trade_date", "start_date", "end_date"],
}
SOURCE_HTML_SHA256 = {
    "stk_premarket": "e855a9c23b1cf62f4cae3a184256303b95c772e3b35303b5c9a632deadcd7fcc",
    "stk_managers": "41dc0600cc48ebc9e630ae93ecf98c5d538613ede151b6847a7676e5307e4c8c",
    "stk_rewards": "f640e1ef2120aab9af52459fa460e9cbdbd34bae02bd473c9abdb9e6256bef19",
    "stk_auction_o": "75ea8f58cbad454e95d47b70e9bd0221b65132ddb84e2f3176f1ff701487a37a",
    "stk_auction_c": "fcae5f89fdf473cedcf5a5c25d8e3949c754188f110e7865309a26c07b973c04",
    "stk_nineturn": "6a07a3aa58d89c5736a1de6adfb2a4a072456ae8b5250b49117247bf18039a5c",
    "stk_ah_comparison": "b35e72d0fed6446c28a32e34a61b04830025b1ee68cf83e00ab2f141cc4d1be5",
}
_DOCS = {
    "stk_premarket": (329, 8000, None, None, True),
    "stk_managers": (193, 1000, None, 2000, False),
    "stk_rewards": (194, 1000, None, 2000, False),
    "stk_auction_o": (353, 10000, None, None, True),
    "stk_auction_c": (354, 10000, None, None, True),
    "stk_nineturn": (364, 10000, "20230101", 6000, True),
    "stk_ah_comparison": (399, 1000, "20250812", 5000, True),
}
STOCK_CONTEXT_CONTRACTS = {}
for _api, (_doc, _cap, _start, _points, _cap_known) in _DOCS.items():
    axis = "ann_date" if _api in ("stk_managers", "stk_rewards") else "trade_date"
    keys = {
        "stk_managers": [
            "ts_code",
            "ann_date",
            "name",
            "lev",
            "title",
            "begin_date",
            "end_date",
        ],
        "stk_rewards": ["ts_code", "ann_date", "end_date", "name", "title"],
        "stk_nineturn": ["ts_code", "trade_date", "freq"],
        "stk_ah_comparison": ["ts_code", "hk_code", "trade_date"],
    }.get(_api, ["ts_code", "trade_date"])
    spec = _contract(
        _cap,
        keys,
        required=FIELDS[_api],
        nullable=[
            f
            for f in FIELDS[_api]
            if f not in ("ts_code", axis)
            and not (_api == "stk_nineturn" and f == "freq")
            and not (_api == "stk_ah_comparison" and f == "hk_code")
        ],
        extra=FIELDS[_api],
        start=_start,
        rpm=30,
        cap_verified=_cap_known,
        split=_api != "stk_rewards",
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        source_html_sha256=SOURCE_HTML_SHA256[_api],
        input_fields=INPUT_FIELDS[_api],
        input_type="str",
        required_input_fields=["ts_code"] if _api == "stk_rewards" else [],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[
            f for f, m in FIELD_METADATA[_api].items() if m["default"] != "Y"
        ],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=True if _points is None else None,
        documented_requests_per_minute=None,
        documented_daily_requests=None,
        permission_gap="Thresholds and separately purchased rights are not observed account permission; probe each API independently. Local 30 rpm is a conservative ceiling, not supplier entitlement.",
        dependencies=["stocks"] if _api == "stk_rewards" else [],
        saturation_fallback="stocks",
        saturation_param="ts_code",
        preserve_distinct_rows=True,
        date_field=axis,
        split_axis=axis,
        history_bound_verified=False,
        history_gap="No exact oldest observation is proved by samples or the current security universe; an explicit 1990 scope remains a requested scope, not a supplier start. Known starts bound requests but do not certify every day/security.",
        pagination_gap="No offset/limit inputs are documented. Preserve all filters in legal date/code partitions; single-code/date saturation stays blocked and observed codes are not a complete universe.",
        discovery_gap="Union historical/delisted/T stock identities and source-observed securities without clipping to currently listed stocks. Preserve source suffix codes and distinct reused identities; ETFs/indexes are not inferred to be stocks.",
        pit_gap="Keep source data dates and observed_at separately. Availability/update schedules do not prove historical intraday knowledge, immutable revisions, trade eligibility or complete historical coverage.",
        refresh_gap="A seven-day recent overlap cannot prove old revisions/deletions. Missing sessions need source calendar checks, not weekend heuristics or empty-success inference.",
        field_selection_note="Explicitly request all reviewed columns including N defaults; retain extra returned fields, signed values and nullable/partial dates. Do not infer the presence of a field from fields='' or selected-column samples.",
        field_gaps={
            f: ["actual_field_presence_unprobed", "availability_revision_unverified"]
            for f in FIELDS[_api]
        },
    )
    if not _cap_known:
        spec["cap_note"] = (
            "The page publishes no row limit. 1000 is a local saturation guard, not a documented maximum; even a subguard response cannot establish exhaustive history. No legal offset is given."
        )
    STOCK_CONTEXT_CONTRACTS[_api] = spec

STOCK_CONTEXT_CONTRACTS["stk_premarket"].update(
    documented_update_times=["09:00", "18:10"],
    update_timezone_verified=False,
    permission_source_url="https://tushare.pro/document/1?doc_id=290",
    documented_requests_per_minute=500,
    history_gap="Permission table says recent two years and updating next-day data; the endpoint describes the current day and two updates. This moving retention/next-day label is not an exact earliest day or proof old data remains queryable. Do not synthesize a two-year cutoff or backfill earlier premarket states from current values.",
    date_axis_note="trade_date is the target stock session, potentially next day per permission page, not observed_at. Current-day recent jobs do not capture two intraday versions or guarantee next-session premarket capture; that scheduling/availability gap remains open.",
    unit_note="total_share/float_share are ten-thousand shares; price currency/adjustment is unstated. pre_close can be null for newly listed BJ securities. Do not infer limit-band rules from returned prices.",
    intraday_gap="Pure date planner does not guarantee morning/evening snapshots or next-session observations. Requires verified source calendar and execution-time scheduling before premarket/PIT claims.",
)
STOCK_CONTEXT_CONTRACTS["stk_managers"].update(
    date_axis_note="Input start_date/end_date filter ANNOUNCEMENT dates. Output begin_date/end_date are appointment/termination dates; birthday may contain only year or year-month. Never use output tenure end as the request upper-date filter.",
    hidden_fields_gap="resume is default N and must be explicitly requested, response-checked and preserved in raw/Parquet. Nullable biography is valid; missing column is a schema gap.",
    identity_gap="Names are not unique persons; multiple roles/terms/announcements and distinct raw rows must survive. No supplier person or appointment ID is provided; identical-row multiplicity and corrected/deleted histories remain unknown.",
    multi_code_note="Comma-separated ts_code is explicitly supported, but this planner uses all-market exact announcement days and legal single-code saturation fallback, without guessing multi-code count limits.",
)
STOCK_CONTEXT_CONTRACTS["stk_rewards"].update(
    date_axis_note="Only ts_code (required) and optional end_date REPORT PERIOD are legal inputs. Output ann_date is publication date; end_date is the financial period, never a request interval end. Store default ann_date for availability-oriented filtering, explicit end_date for report cohorts.",
    dependencies=["stocks", "reward_periods"],
    history_request="observed_single_stock_report_periods",
    recent_request="unbounded_single_stock_and_latest_observed_period_each_epoch",
    history_gap="No start or announcement-range input and no oldest date is documented. One code-only request returns supplier-available periods without invented quarterly coverage or local date clipping; configuration scopes cannot trim it.",
    unit_note="reward is CNY yuan, hold_vol shares. Unknown/unreported reward is nullable; zero holdings is a valid value, not missing. Annualization, currencies for unusual entities and retrospective revisions need evidence.",
    saturation_gap="Code-only request has no legal start_date/offset partition. end_date can filter an actually observed stock/report-period pair. Supplemental period jobs do not partition or complete the code-only parent: the period inventory is incomplete, and capped parents or individual periods remain blocked.",
    identity_gap="Same name/title across periods or revisions is not a globally unique manager; preserve distinct source rows and avoid inferring individual identity or an exhaustive payroll census.",
)
for _api in ("stk_auction_o", "stk_auction_c"):
    STOCK_CONTEXT_CONTRACTS[_api].update(
        permission_source_url="https://tushare.pro/document/1?doc_id=290",
        permission_gap="Each endpoint explicitly needs independent permission. The linked general table's auction row describes current-day pre-09:30 access and links another endpoint; its 500rpm or entitlement cannot automatically be assigned to these historical opening/closing APIs.",
        documented_session_time="09:30" if _api == "stk_auction_o" else "15:00",
        documented_update_time="after_market_close",
        update_timezone_verified=False,
        date_axis_note="trade_date labels the source auction session; source session timestamp does not establish same-time availability because updates are documented after close. Opening and closing datasets stay separate, not daily bar aliases.",
        unit_note="OHLC/vwap are auction price statistics. vol/amount units and adjustment/currency are not explicit; sample arithmetic is evidence to test, not permission to inherit daily lots/thousand-CNY scales.",
    )
STOCK_CONTEXT_CONTRACTS["stk_nineturn"].update(
    split={"start_param": "start_date", "end_param": "end_date", "precision": "second"},
    documented_update_time="21:00",
    update_timezone_verified=False,
    date_field="trade_date",
    date_format="YYYY-MM-DD HH:MM:SS",
    supported_planned_freqs=["daily"],
    request_identity_fields=["freq"],
    date_axis_note="Input trade_date is a datetime string, output trade_date datetime; reviewed daily examples use midnight. Emit explicit freq=daily and YYYY-MM-DD 00:00:00; never send YYYYMMDD, infer exchange timezone, or collapse intraday values to dates.",
    frequency_gap="Description references 60min/minute data, but input table/example only establishes literal daily. Other legal freq labels, minute rights and complete timestamp/session grid remain unresolved; preserve the obligation instead of guessing 60min or silently claiming all frequencies.",
    unit_note="OHLC/vol/amount units and adjustment are not specified. Counts are float; nine_up_turn/nine_down_turn are source strings (including sign markers) or null, not booleans.",
    formula_gap="TD-style naming and nine-count descriptions do not fully define initialization, comparison prices, pauses, corporate actions or repaint behavior; retain supplier indicators without research causality claims.",
)
STOCK_CONTEXT_CONTRACTS["stk_ah_comparison"].update(
    documented_update_time="17:00",
    update_timezone_verified=False,
    history_gap="Explicit start is 20250812; supplier says older history is difficult to reconstruct and can only accumulate forward. An earlier configured scope cannot manufacture pre-start coverage.",
    date_axis_note="trade_date is a cross-market comparison date. Hong Kong and mainland sessions/holidays can diverge; no assumption that both closes are same-session, contemporaneous, or current for that date.",
    namespace_note="ts_code is mainland suffix identity; hk_code is separate five-digit.HK identity. Preserve source_hk_code/source_ts_code and pair identity including historical reuse markers if returned; never coerce HK into A-share or drop leading zeros. HK canonical field projection still needs runtime integration.",
    unit_note="ah_comparison is A/H ratio, ah_premium A/H premium percent. FX conversion, quote currencies, dividend adjustment, stale-price policy and numeric precision are unstated; do not recompute ratio directly from the two closes without evidence.",
    saturation_gap="A-code fanout preserves the HK paired output; a saturated single A-code/day can require hk_code second dimension, whose complete historical pair universe is unknown. Keep blocked rather than treating known HK rows as exhaustive.",
)


def _enabled(config):
    selected = config.get("stock_context_apis", tuple(STOCK_CONTEXT_CONTRACTS))
    if not isinstance(selected, (list, tuple)) or any(
        not isinstance(api, str) or api not in STOCK_CONTEXT_CONTRACTS
        for api in selected
    ):
        raise ValueError("stock_context_apis must list known APIs")
    return tuple(dict.fromkeys(selected))


def _starts(config, enabled):
    setting = config.get("stock_context_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "stock_context_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - STOCK_CONTEXT_CONTRACTS.keys():
        raise ValueError("Unknown API in stock_context_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        floor = STOCK_CONTEXT_CONTRACTS[api]["history_start"]
        candidates = [_parse(v) for v in (value, floor) if v is not None]
        starts[api] = max(candidates) if candidates else None
    return starts


def stock_context_stock_inventory(identifiers):
    """Keep unsupported source identifiers observable without blocking valid leaves.

    Container/configuration errors stay strict. The source inventory itself is
    never modified; only this family's outbound stock requests are selected.
    """
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to records")
    values = identifiers.get("stocks", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("stocks must contain supplier codes or discovery records")
    stocks, invalid_count, examples = set(), 0, []
    for value in values:
        try:
            stocks.update(_stocks({"stocks": [value]}))
        except ValueError:
            invalid_count += 1
            if len(examples) < 5:
                code = value.get("ts_code") if isinstance(value, dict) else value
                payload = json.dumps(
                    code,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=lambda item: type(item).__name__,
                )
                example = {
                    "type": type(code).__name__,
                    "value_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                }
                if isinstance(code, str) and re.fullmatch(
                    r"[A-Za-z0-9!]{1,16}\.[A-Za-z]{2,4}", code
                ):
                    example["source_code"] = code
                examples.append(example)
    return sorted(stocks), {
        "valid_stock_count": len(stocks),
        "invalid_identifier_count": invalid_count,
        "invalid_identifier_examples": examples,
        "example_limit": 5,
        "source_inventory_complete": False,
        "original_identifiers_retained": True,
    }


def observed_reward_periods(identifiers):
    """Return only valid observed code/period pairs; malformed evidence stays a gap."""
    values = identifiers.get("reward_periods", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("reward_periods must contain source observation records")
    pairs, invalid = set(), 0
    for row in values:
        try:
            if not isinstance(row, dict) or set(row) != {"ts_code", "end_date"}:
                raise ValueError("Expected source stock/report-period identity")
            code = _stocks({"stocks": [row["ts_code"]]})[0]
            period = row["end_date"]
            _parse(period)  # Exact valid YYYYMMDD; never substitute ann_date.
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        pairs.add((code, period))
    return sorted(pairs), invalid


def _reward_recent_requests(stocks, periods):
    latest = {}
    for code, period in periods:
        latest[code] = max(period, latest.get(code, period))
    for code in sorted(set(stocks) | set(latest)):
        # Preserve unrestricted discovery even when its local cap is reached.
        yield {"ts_code": code}
        if code in latest:
            yield {"ts_code": code, "end_date": latest[code]}


def stock_context_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["stock_context_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    stocks, stock_inventory = (
        stock_context_stock_inventory(identifiers if identifiers is not None else {})
        if "stk_rewards" in enabled
        else ([], {})
    )
    gaps = []
    if stock_inventory.get("invalid_identifier_count"):
        gaps.append(
            {
                "api_name": "stk_rewards",
                "dependencies": [],
                "reason": "malformed_stock_supplier_identifiers",
                **stock_inventory,
                "detail": "Unsupported source identities remain in raw/discovery. Valid stock leaves continue; no prefix repair, inferred market or complete-universe claim.",
            }
        )
    for api in enabled:
        spec = STOCK_CONTEXT_CONTRACTS[api]
        for kind in (
            "permission_gap",
            "history_gap",
            "pagination_gap",
            "discovery_gap",
            "pit_gap",
            "refresh_gap",
            "cap_note",
            "intraday_gap",
            "hidden_fields_gap",
            "identity_gap",
            "saturation_gap",
            "frequency_gap",
            "formula_gap",
        ):
            if spec.get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": spec[kind],
                    }
                )
        gaps.append(
            {
                "api_name": api,
                "dependencies": [],
                "reason": "unbounded_stock_request_not_date_scoped"
                if api == "stk_rewards"
                else "unknown_history_start_requires_scope"
                if starts[api] is None
                else "configured_scope_not_verified_complete",
            }
        )
        if api == "stk_rewards":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["stocks"],
                    "reason": "stored_discovery_completeness_unverified"
                    if stocks
                    else "awaiting_stored_stocks",
                    "observed_codes": len(stocks),
                    "universe_complete": False,
                }
            )
    if "stk_rewards" in enabled:
        periods, invalid = observed_reward_periods(identifiers or {})
        gaps.append(
            {
                "api_name": "stk_rewards",
                "dependencies": [],
                "reason": "observed_period_inventory_unverified",
                "observed_pairs": len(periods),
                "invalid_period_identities": invalid,
                "period_inventory_complete": False,
                "parent_saturation_resolved": False,
                "detail": "Only actual stk_rewards code/end_date pairs supplement discovery; neither returned periods nor successful single-period requests certify the unbounded parent or revisions to older periods.",
            }
        )
    return gaps


def _params(api, begin, end):
    for params in _days(begin, end):
        day = params["trade_date"]
        if api == "stk_managers":
            yield {"ann_date": day}
        elif api == "stk_nineturn":
            yield {"trade_date": _parse(day).isoformat() + " 00:00:00", "freq": "daily"}
        else:
            yield params


def iter_stock_context_jobs(config, today, identifiers=None):
    """Fair source dates; rewards preserve discovery plus observed-period supplements."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    stocks = (
        stock_context_stock_inventory(identifiers if identifiers is not None else {})[0]
        if "stk_rewards" in enabled
        else []
    )
    reward_periods = (
        observed_reward_periods(identifiers or {})[0]
        if "stk_rewards" in enabled
        else []
    )
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    for history in (False, True):
        streams = {}
        for api in enabled:
            start = starts[api]
            if api == "stk_rewards":
                if history:
                    streams[api] = (
                        {"ts_code": code, "end_date": period}
                        for code, period in reward_periods
                    )
                else:
                    streams[api] = iter(_reward_recent_requests(stocks, reward_periods))
            elif not history:
                streams[api] = iter(_params(api, max(start or recent, recent), today))
            elif start and start < recent:
                streams[api] = iter(_params(api, start, recent - timedelta(days=1)))
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
