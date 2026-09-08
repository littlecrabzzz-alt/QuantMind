"""Pure reviewed Stock Connect and board-flow contracts, not runtime registration."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "stock_hsgt": ["ts_code", "trade_date", "type", "name", "type_name"],
    "hsgt_top10": [
        "trade_date",
        "ts_code",
        "name",
        "close",
        "change",
        "rank",
        "market_type",
        "amount",
        "net_amount",
        "buy",
        "sell",
    ],
    "moneyflow_cnt_ths": [
        "trade_date",
        "ts_code",
        "name",
        "lead_stock",
        "close_price",
        "pct_change",
        "industry_index",
        "company_num",
        "pct_change_stock",
        "net_buy_amount",
        "net_sell_amount",
        "net_amount",
    ],
    "moneyflow_ind_ths": [
        "trade_date",
        "ts_code",
        "industry",
        "lead_stock",
        "close",
        "pct_change",
        "company_num",
        "pct_change_stock",
        "close_price",
        "net_buy_amount",
        "net_sell_amount",
        "net_amount",
    ],
    "moneyflow_ind_dc": [
        "trade_date",
        "content_type",
        "ts_code",
        "name",
        "pct_change",
        "close",
        "net_amount",
        "net_amount_rate",
        "buy_elg_amount",
        "buy_elg_amount_rate",
        "buy_lg_amount",
        "buy_lg_amount_rate",
        "buy_md_amount",
        "buy_md_amount_rate",
        "buy_sm_amount",
        "buy_sm_amount_rate",
        "buy_sm_amount_stock",
        "rank",
    ],
}
INPUT_FIELDS = {
    "stock_hsgt": ["ts_code", "trade_date", "type", "start_date", "end_date"],
    "hsgt_top10": ["ts_code", "trade_date", "start_date", "end_date", "market_type"],
    "moneyflow_cnt_ths": ["ts_code", "trade_date", "start_date", "end_date"],
    "moneyflow_ind_ths": ["ts_code", "trade_date", "start_date", "end_date"],
    "moneyflow_ind_dc": [
        "ts_code",
        "trade_date",
        "start_date",
        "end_date",
        "content_type",
    ],
}

_DOCS = {
    "stock_hsgt": (398, 2000, 3000, ("trade_date", "ts_code", "type")),
    "hsgt_top10": (48, 1000, None, ("trade_date", "ts_code", "market_type")),
    "moneyflow_cnt_ths": (371, 5000, 6000, ("trade_date", "ts_code")),
    "moneyflow_ind_ths": (343, 5000, 6000, ("trade_date", "ts_code")),
    "moneyflow_ind_dc": (344, 5000, 6000, ("trade_date", "ts_code", "content_type")),
}
VARIANTS = {
    "stock_hsgt": [{"type": kind} for kind in ("HK_SZ", "SZ_HK", "HK_SH", "SH_HK")],
    "hsgt_top10": [{"market_type": kind} for kind in ("1", "3")],
    "moneyflow_ind_dc": [{"content_type": kind} for kind in ("行业", "概念", "地域")],
}
CONNECT_CONTRACTS = {}
for _api, (_doc, _cap, _points, _keys) in _DOCS.items():
    _spec = _contract(
        _cap,
        _keys,
        nullable=tuple(f for f in FIELDS[_api] if f not in _keys),
        extra=FIELDS[_api],
        rpm=50,
        start="20250812" if _api == "stock_hsgt" else None,
        cap_verified=_api != "hsgt_top10",
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        hidden_fields=[],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        documented_requests_per_minute=None,
        rate_note="50/min is a local conservative ceiling; these pages do not document a numeric per-minute allowance. Account gates must still apply.",
        history_bound_verified=_api == "stock_hsgt",
        stop_date=None,
        update_status="no_stop_date_in_current_reviewed_page",
        dependencies=[],
        split_axis="trade_date",
        saturation_fallback="connect_" + _api,
        saturation_param="ts_code",
        saturation_dependencies=[_api + "_observed_codes"],
        discovery_gap="Date/source-type bulk requests discover supplier identifiers. Observed codes and successful leaves do not prove a complete historical universe. Keep source/market/type filters on every child; never substitute a stock universe for HK securities or board codes.",
        saturation_gap="Use legal date bisection, then source-observed codes with existing filters unchanged. No offset/limit is documented; a saturated code/day/type remains a gap.",
        refresh_gap="Recent seven-day overlap does not certify corrections to older history. Observation timestamps are not historical publication-time or PIT proof.",
        source_identity_note="Keep source codes and labels verbatim, including .HK, .TI and opaque DC board codes. These are not interchangeable stock/industry taxonomies or verified tradable instruments.",
    )
    CONNECT_CONTRACTS[_api] = _spec
CONNECT_CONTRACTS["stock_hsgt"].update(
    update_note="Official daily update around 09:20; page states data starts 20250812.",
    required_params=["type"],
    filter_consistency_gap="The example for one requested type contains multiple types. Validate actual source type/date consistency; do not treat that example as proof of filtering or historical membership availability.",
    pit_gap="Daily eligibility observations begin only 20250812 in this source. They do not reconstruct earlier membership or announcement-effective-time changes.",
)
CONNECT_CONTRACTS["hsgt_top10"].update(
    update_note="Official daily update 18:00-20:00.",
    permission_note="The current endpoint page does not specify a points threshold or numeric cap. Access must be independently probed; the 1000-row cap is only a conservative saturation alarm.",
    required_one_of=["ts_code", "trade_date"],
    cap_gap="No documented numerical row cap; a non-saturated response alone is not completeness proof.",
    unit_note="amount/net_amount/buy/sell are CNY; change is a price change, not percent. Ranking covers only ten active stocks per route, not all Connect securities.",
)
for _api in ("moneyflow_cnt_ths", "moneyflow_ind_ths"):
    CONNECT_CONTRACTS[_api]["unit_note"] = (
        "net_buy_amount/net_sell_amount/net_amount are hundred-million CNY. Do not repair rounding or derive net amounts by subtracting displayed sample columns. Names of leading stocks remain names, not identifiers."
    )
CONNECT_CONTRACTS["moneyflow_ind_dc"]["unit_note"] = (
    "Amount fields are CNY; *_rate and pct_change are percentages. Keep buy_sm_amount_stock as supplier text. Industry/concept/region are distinct content_type values, not aliases."
)


def _settings(config, today):
    enabled = config.get("connect_apis", tuple(CONNECT_CONTRACTS))
    if not isinstance(enabled, (list, tuple)) or any(
        not isinstance(api, str) or api not in CONNECT_CONTRACTS for api in enabled
    ):
        raise ValueError("connect_apis must list reviewed CONNECT_CONTRACTS APIs")
    setting = config.get("connect_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("connect_history_start must be a date or API mapping")
    if isinstance(setting, dict) and setting.keys() - CONNECT_CONTRACTS.keys():
        raise ValueError("Unknown API in connect_history_start")
    starts = {}
    for api in dict.fromkeys(enabled):
        value = setting.get(api) if isinstance(setting, dict) else setting
        value = value if value is not None else config.get("history_start")
        start = _parse(value) if value is not None else None
        if today is not None and start and start > today:
            raise ValueError("History start cannot be after today")
        documented = CONNECT_CONTRACTS[api]["history_start"]
        if documented:
            start = max(start or _parse(documented), _parse(documented))
        starts[api] = start
    return starts


def connect_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["connect_apis"] = enabled_apis
    starts = _settings(config, None)
    gaps = []
    for api, start in starts.items():
        spec = CONNECT_CONTRACTS[api]
        gaps.append(
            {
                "api_name": api,
                "dependencies": spec["saturation_dependencies"],
                "reason": "source_observed_universe_unverified",
                "universe_complete": False,
            }
        )
        if not spec["history_bound_verified"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope"
                    if start is None
                    else "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        for kind in (
            "saturation_gap",
            "refresh_gap",
            "pit_gap",
            "cap_gap",
            "filter_consistency_gap",
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
    return gaps


def _windows(api, begin, end):
    day = begin
    while day <= end:
        if api.startswith("moneyflow_"):
            last = min(
                end, date(day.year, day.month, monthrange(day.year, day.month)[1])
            )
            params = {
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
        else:
            last, params = day, {"trade_date": day.strftime("%Y%m%d")}
        for variant in VARIANTS.get(api, [{}]):
            yield {**params, **variant}
        day = last + timedelta(days=1)


def iter_connect_jobs(config, today, identifiers=None):
    """All recent dates/types before fair, lazy history; no guessed initial date."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    starts = _settings(config, today)
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api, start in starts.items():
        day = max(start or recent, recent)
        while day <= today:
            for variant in VARIANTS.get(api, [{}]):
                yield {
                    "api_name": api,
                    "params": {"trade_date": day.strftime("%Y%m%d"), **variant},
                    "priority": 20,
                    "epoch": epoch,
                }
            day += timedelta(days=1)
        if start and start < recent:
            histories[api] = iter(_windows(api, start, recent - timedelta(days=1)))
    while histories:
        for api in tuple(histories):
            params = next(histories[api], None)
            if params is None:
                del histories[api]
            else:
                yield {
                    "api_name": api,
                    "params": params,
                    "priority": 40,
                    "epoch": "history",
                }
