"""Reviewed contracts added by the 2026-09-19 public catalogue refresh.

Pure planning only: no credentials, network access, or storage mutation.  The two
realtime/auction APIs retain independent entitlement gates; the five point based
leaf APIs use deterministic date partitions and the shared durable pipeline.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "rt_hk_k": "ts_code pre_close close high open low vol amount".split(),
    "etf_auction": "ts_code trade_date vol price amount pre_close turnover_rate volume_ratio float_share".split(),
    "stk_seasoned": """ts_code ann_date first_ann_date proj_info_source board_approval_dt sh_approval_dt sasac_approval_dt csrc_approval_dt fo_type fo_stock_type cur_stage valid_st_dt valid_end_dt plan_chg_type plan_chg_ann_dt pricing_method pricing_base_dt price_basis fo_vol_high fo_vol_low fo_price_high fo_price_low fo_price_ratio fo_raise_total fo_purpose fo_investor sub_method fo_price_act fo_vol_act fo_raise_total_act fo_raise_net_act fo_exp_total uw_fee fo_exp_audit fo_exp_legal fo_exp_inst fo_exp_pub fo_exp_reg fo_exp_other fo_exp_per_share issue_obj_type pe_issue pub_plac_qty onl_pch_vol onl_pch_num onl_pch_excess onl_winning_rate inst_plac_qty inst_sub_eff_total inst_sub_eff_cnt inst_oversub_times a_inv_plac_qty b_inv_plac_qty old_sh_pre_plac_qty old_sh_pre_plac_ratio clw_between_inst_pub prospectus_pub_dt offer_intent_pub_dt apply_date old_sh_pre_plac_dt onl_issue_date uw_start_dt uw_end_dt uw_mode new_share_list_dt list_circ_qty right_reg_dt ex_right_dt update_flag""".split(),
    "fut_inv_weekly": "ts_code trade_date fut_name exchange area warehouse grade pre_total pre_futures cur_total cur_futures chg_total chg_futures pre_capacity cur_capacity chg_capacity unit".split(),
    "fut_rcpt_mat": "trade_date exchange fut_code fut_name unit cur_month next_month next_two_month".split(),
    "fut_trade_param": "trade_date fut_code exchange trade_unit tick_size pre_settle_price price_limit position_limit trade_limit min_order_qty max_limit_order_qty max_market_order_qty".split(),
    "vix_index": "trade_date high low open close pct_change".split(),
}
INPUT_FIELDS = {
    "rt_hk_k": ["ts_code"],
    "etf_auction": "ts_code trade_date start_date end_date ts_type".split(),
    "stk_seasoned": "ts_code ann_date start_date end_date".split(),
    "fut_inv_weekly": "trade_date ts_code start_date end_date".split(),
    "fut_rcpt_mat": "trade_date ts_code start_date end_date".split(),
    "fut_trade_param": "trade_date fut_code start_date end_date".split(),
    "vix_index": "trade_date start_date end_date".split(),
}
DOCS = {
    "rt_hk_k": (383, 5000, None, None),
    "etf_auction": (493, 3000, None, "20250101"),
    "stk_seasoned": (494, 3000, 2000, None),
    "fut_inv_weekly": (495, 3000, 5000, None),
    "fut_rcpt_mat": (496, 3000, 5000, None),
    "fut_trade_param": (497, 3000, 5000, None),
    "vix_index": (498, 300, 5000, None),
}
KEYS = {
    "rt_hk_k": ("ts_code",),
    "etf_auction": ("ts_code", "trade_date"),
    "stk_seasoned": (
        "ts_code",
        "ann_date",
        "first_ann_date",
        "cur_stage",
        "plan_chg_ann_dt",
        "new_share_list_dt",
    ),
    "fut_inv_weekly": (
        "ts_code",
        "trade_date",
        "exchange",
        "area",
        "warehouse",
        "grade",
        "unit",
    ),
    "fut_rcpt_mat": ("trade_date", "exchange", "fut_code", "unit"),
    "fut_trade_param": ("trade_date", "fut_code", "exchange"),
    "vix_index": ("trade_date",),
}
REQUIRED = {
    "rt_hk_k": ("ts_code",),
    "etf_auction": ("ts_code", "trade_date"),
    "stk_seasoned": ("ts_code", "ann_date"),
    "fut_inv_weekly": ("ts_code", "trade_date"),
    "fut_rcpt_mat": ("trade_date", "exchange", "fut_code"),
    "fut_trade_param": ("trade_date", "fut_code", "exchange"),
    "vix_index": ("trade_date",),
}
WINDOWS = {
    "etf_auction": "day",
    "stk_seasoned": "year",
    "fut_inv_weekly": "month",
    "fut_rcpt_mat": "month",
    "fut_trade_param": "day",
    "vix_index": "year",
}

CATALOG_DELTA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start) in DOCS.items():
    _independent = _points is None
    _spec = _contract(
        _cap,
        KEYS[_api],
        required=REQUIRED[_api],
        nullable=tuple(field for field in FIELDS[_api] if field not in REQUIRED[_api]),
        split=_api not in ("rt_hk_k", "etf_auction", "fut_trade_param"),
        start=_start,
        rpm=200 if _independent else 500,
        extra=FIELDS[_api],
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=_independent,
        documented_requests_per_minute=None,
        history_bound_verified=_api == "etf_auction",
        history_gap=(
            "snapshot_only_no_history"
            if _api == "rt_hk_k"
            else None
            if _start
            else "official_earliest_date_unspecified"
        ),
        dependencies=["hk_stocks"] if _api == "rt_hk_k" else [],
        split_axis="snapshot"
        if _api == "rt_hk_k"
        else "announcement_date"
        if _api == "stk_seasoned"
        else "trade_date",
        pagination_gap=(
            "No offset/limit input is documented; a saturated exact-day partition remains an explicit gap."
            if _api in ("etf_auction", "fut_trade_param")
            else "No offset/limit input is documented; saturated ranges use the reviewed date split only."
        ),
    )
    CATALOG_DELTA_CONTRACTS[_api] = _spec

CATALOG_DELTA_CONTRACTS["rt_hk_k"].update(
    snapshot_only=True,
    parameter_note="Use exact retained five-digit .HK supplier codes. Wildcard completeness and batching semantics are not documented well enough to synthesize a catch-all request.",
    scope_note="A realtime snapshot cannot reconstruct history and is not a substitute for hk_daily.",
)
CATALOG_DELTA_CONTRACTS["etf_auction"].update(
    history_start_precision="month",
    parameter_note="All-market exact trade_date requests avoid assuming undocumented ts_type values. A 3000-row hit remains a terminal gap until a source-code fanout is verified.",
)
CATALOG_DELTA_CONTRACTS["stk_seasoned"].update(
    preserve_distinct_rows=True,
    revision_note="Announcement stages and update_flag may revise. Preserve every raw observation; recent overlap does not certify older revisions.",
)
for _api in ("fut_inv_weekly", "fut_rcpt_mat", "fut_trade_param"):
    CATALOG_DELTA_CONTRACTS[_api].update(
        identity_note="Preserve supplier futures/product/exchange spelling. Do not apply equity code normalization or infer coverage for exchanges the page says are still pending.",
        scope_note="The current page names one exchange and says others are pending; successful rows do not prove all-exchange coverage.",
    )
CATALOG_DELTA_CONTRACTS["vix_index"].update(
    identity_note="VIX is a volatility index series, not a stock security or a tradeable instrument identifier.",
    field_type_note="The official table publishes OHLC and pct_change as strings; preserve source values before any typed research projection.",
)


def _enabled(config):
    values = config.get("catalog_delta_apis", tuple(CATALOG_DELTA_CONTRACTS))
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(api, str) or api not in CATALOG_DELTA_CONTRACTS
        for api in values
    ):
        raise ValueError(
            "catalog_delta_apis must list known CATALOG_DELTA_CONTRACTS APIs"
        )
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    value = config.get("catalog_delta_history_start", config.get("history_start"))
    if value is not None and not isinstance(value, (str, dict)):
        raise ValueError(
            "catalog_delta_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(value, dict) and value.keys() - CATALOG_DELTA_CONTRACTS.keys():
        raise ValueError("Unknown API in catalog_delta_history_start")
    starts = {}
    for api in enabled:
        if api == "rt_hk_k":
            starts[api] = None
            continue
        supplied = value.get(api, config.get("history_start")) if isinstance(value, dict) else value
        floor = CATALOG_DELTA_CONTRACTS[api]["history_start"]
        parsed = _parse(supplied) if supplied is not None else None
        starts[api] = (
            max(parsed, _parse(floor))
            if parsed and floor
            else parsed or (_parse(floor) if floor else None)
        )
    return starts


def _hk_codes(identifiers):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to values")
    values = identifiers.get("hk_stocks", ())
    if not isinstance(values, (list, tuple)):
        raise ValueError("hk_stocks must be a list of codes or discovery records")
    result = set()
    for row in values:
        code = row.get("ts_code") if isinstance(row, dict) else row
        if not isinstance(code, str) or not re.fullmatch(
            r"[0-9]{5}(?:![A-Z]{0,8})?\.HK", code
        ):
            raise ValueError("Invalid retained HK supplier code")
        result.add(code)
    return sorted(result)


def catalog_delta_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["catalog_delta_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    hk_codes = _hk_codes(identifiers or {}) if "rt_hk_k" in enabled else []
    gaps = []
    for api in enabled:
        spec = CATALOG_DELTA_CONTRACTS[api]
        if spec["independent_permission"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "independent_permission_requires_live_verification",
                }
            )
        if api == "rt_hk_k":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": ["hk_stocks"],
                    "reason": "snapshot_source_universe_unverified",
                    "observed_codes": len(hk_codes),
                    "universe_complete": False,
                }
            )
        elif starts[api] is None:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_explicit_scope",
                }
            )
        elif spec.get("history_gap"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        if spec.get("scope_note"):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "source_scope_unverified",
                    "detail": spec["scope_note"],
                }
            )
    return gaps


def _windows(api, begin, end):
    precision = WINDOWS[api]
    cursor = begin
    while cursor <= end:
        if precision == "day":
            yield {"trade_date": cursor.strftime("%Y%m%d")}
            cursor += timedelta(days=1)
            continue
        if precision == "month":
            right = min(
                end,
                date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]),
            )
        else:
            right = min(end, date(cursor.year, 12, 31))
        yield {
            "start_date": cursor.strftime("%Y%m%d"),
            "end_date": right.strftime("%Y%m%d"),
        }
        cursor = right + timedelta(days=1)


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def iter_catalog_delta_jobs(config, today, identifiers=None):
    """Yield current work first and bounded stable history partitions second."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    if "rt_hk_k" in enabled:
        for code in _hk_codes(identifiers or {}):
            yield _job("rt_hk_k", {"ts_code": code}, epoch, 20)
    recent_floor = today - timedelta(days=6)
    for api in enabled:
        if api == "rt_hk_k":
            continue
        start = max(starts[api] or recent_floor, recent_floor)
        for params in _windows(api, start, today):
            yield _job(api, params, epoch, 20)
    history_end = recent_floor - timedelta(days=1)
    for api in enabled:
        start = starts[api]
        if api == "rt_hk_k" or start is None or start > history_end:
            continue
        for params in _windows(api, start, history_end):
            yield _job(api, params, "history", 40)
