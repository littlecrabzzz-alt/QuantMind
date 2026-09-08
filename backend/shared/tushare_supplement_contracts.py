"""Reviewed pure plans for five equity/fund supplementary data sources.

Supplier identifiers and source-specific measurements stay distinct. No network,
credentials, storage, guessed history bounds, or implicit entitlement checks.
"""

from datetime import date, datetime, timedelta
import re

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "moneyflow_mkt_dc": [
        "trade_date",
        "close_sh",
        "pct_change_sh",
        "close_sz",
        "pct_change_sz",
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
    ],
    "moneyflow_dc": [
        "trade_date",
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
    ],
    "moneyflow_ths": [
        "trade_date",
        "ts_code",
        "name",
        "pct_change",
        "latest",
        "net_amount",
        "net_d5_amount",
        "buy_lg_amount",
        "buy_lg_amount_rate",
        "buy_md_amount",
        "buy_md_amount_rate",
        "buy_sm_amount",
        "buy_sm_amount_rate",
    ],
    "etf_share_size": [
        "trade_date",
        "ts_code",
        "etf_name",
        "total_share",
        "total_size",
        "nav",
        "close",
        "exchange",
    ],
    "mkt_idx_bmk": [
        "ts_code",
        "symbol",
        "name",
        "fullname",
        "bmk_level",
        "bmk_type",
        "bmk_src",
        "idx_type",
    ],
}

# API -> (official doc id, row cap, documented minimum points)
_DOCS = {
    "moneyflow_mkt_dc": (345, 3000, 6000),
    "moneyflow_dc": (349, 6000, 5000),
    "moneyflow_ths": (348, 6000, 6000),
    "etf_share_size": (408, 5000, 8000),
    "mkt_idx_bmk": (462, 500, 5000),
}
BASIC = "mkt_idx_bmk"
MARKET_TOTAL = "moneyflow_mkt_dc"
FAMILIES = {
    "moneyflow_dc": "stocks",
    "moneyflow_ths": "stocks",
    "etf_share_size": "funds",
    BASIC: "indexes",
}
SUPPLEMENT_CONTRACTS = {}
for _api, (_doc, _cap, _points) in _DOCS.items():
    _keys = (
        ("ts_code", "bmk_level")
        if _api == BASIC
        else ("trade_date",)
        if _api == MARKET_TOTAL
        else ("ts_code", "trade_date")
    )
    _start = "20230911" if _api == "moneyflow_dc" else None
    _spec = _contract(
        _cap,
        _keys,
        nullable=tuple(f for f in FIELDS[_api] if f not in _keys),
        extra=FIELDS[_api],
        split=_api != BASIC,
        start=_start,
        rpm=50,
    )
    _spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=False,
        documented_requests_per_minute=None,
        history_bound_verified=_start is not None,
        history_gap=None
        if _start or _api == BASIC
        else "official_earliest_date_unspecified",
        dependencies=[],
        split_axis="snapshot" if _api == BASIC else "trade_date",
        pagination_gap="No offset/limit parameters documented; use exact documented dates/codes, never invented pagination.",
        revision_note="Keep all observation versions. Recent overlap does not prove older source values have not changed.",
    )
    if _api in FAMILIES:
        _spec.update(
            saturation_fallback=FAMILIES[_api],
            saturation_param="ts_code",
            saturation_dependencies=[FAMILIES[_api]],
        )
    SUPPLEMENT_CONTRACTS[_api] = _spec

SUPPLEMENT_CONTRACTS[MARKET_TOTAL].update(
    permission_note="120 points grants trial only; docs specify 6000 for regular access. Neither proves this account entitlement.",
    amount_unit="CNY",
    natural_identity_note="One aggregate row per trade_date; no stock-code or exchange input.",
)
for _api in ("moneyflow_dc", "moneyflow_ths"):
    SUPPLEMENT_CONTRACTS[_api].update(
        amount_unit="10000 CNY",
        percentage_unit="percent",
        dataset_note="Preserve this vendor series separately from moneyflow and the other vendor; metric definitions and units are not interchangeable.",
    )
SUPPLEMENT_CONTRACTS["moneyflow_ths"]["field_note"] = (
    "latest and net_d5_amount are distinct documented fields; do not substitute DC close/net amounts."
)
SUPPLEMENT_CONTRACTS["etf_share_size"].update(
    hidden_fields=["nav", "close"],
    share_unit="10000 fund units",
    amount_unit="10000 CNY",
    publication_note="Exchange data enters in batches around next-day 08:30; overseas ETF observations can arrive later. Re-fetch recent overlap and retain late/revised observations.",
    exchange_note="Input docs enumerate SSE/SZSE but output includes BSE. Keep all-market queries; never infer a complete two-exchange universe.",
    discovery_note="Use retained ETF/fund discovery including retired codes. fund_share and etf_share_size remain separate datasets.",
)
SUPPLEMENT_CONTRACTS[BASIC].update(
    discovery_family="indexes",
    instrument_type="index",
    documented_input_fields=["ts_code", "bmk_type", "bmk_level"],
    parameter_note="bmk_type input descriptions say 宽基指数/策略指数/行业主题指数 but example/output use 宽基/策略/行业主题. Do not guess a closed type enumeration; start unfiltered and by documented library level.",
    documented_levels=["一类库", "二类库"],
    discovery_note="A benchmark can belong to a library level; retain ts_code+bmk_level and observation revisions. 500-row responses remain saturated, even though docs say one call returns the full list.",
    identifier_note="Index suffixes such as .CSI are valid supplier codes. Parent must normalize as index identifiers, preserve source_ts_code, and not assume every symbol is an equity.",
    dataset_note="mkt_idx_bmk is not an alias of etf_index or index_basic; this API does not establish historical ETF membership or point-in-time benchmark eligibility.",
)


def _enabled(config):
    values = config.get("supplement_apis", tuple(SUPPLEMENT_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(v, str) or v not in SUPPLEMENT_CONTRACTS for v in values
    ):
        raise ValueError("supplement_apis must list known SUPPLEMENT_CONTRACTS APIs")
    return tuple(dict.fromkeys(values))


def _identifiers(identifiers, enabled):
    if not isinstance(identifiers, dict):
        raise ValueError("identifiers must map discovery families to records")
    result = {}
    for family in sorted({FAMILIES[a] for a in enabled if a in FAMILIES}):
        values = identifiers.get(family, ())
        if not isinstance(values, (tuple, list)):
            raise ValueError(
                f"{family} must contain supplier codes or discovery records"
            )
        codes = set()
        for row in values:
            code = (
                row.get("ts_code") or row.get("index_code")
                if isinstance(row, dict)
                else row
            )
            if not isinstance(code, str) or not re.fullmatch(
                r"[A-Za-z0-9]{1,32}\.[A-Z]{1,8}", code
            ):
                raise ValueError(f"Invalid supplier identifier in {family}")
            codes.add(code)
        result[family] = sorted(codes)
    return result


def _requested_starts(config, enabled):
    setting = config.get("supplement_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError("supplement_history_start must be YYYYMMDD or an API mapping")
    if isinstance(setting, dict) and set(setting) - SUPPLEMENT_CONTRACTS.keys():
        raise ValueError("Unknown API in supplement_history_start")
    starts = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        starts[api] = _parse(value) if value is not None else None
    return starts


def supplement_prerequisites(identifiers=None, enabled_apis=None, config=None):
    """Report unknown history and incomplete fallback discovery, without calls.

    A nonempty discovery list is not evidence that a saturated cross-section can
    be fully reconstructed. Parent must persist these gaps and own verification.
    """
    config = dict(config or {})
    if enabled_apis is not None:
        config["supplement_apis"] = enabled_apis
    enabled = _enabled(config)
    ids = _identifiers(identifiers if identifiers is not None else {}, enabled)
    starts = _requested_starts(config, enabled)
    gaps = []
    for api in enabled:
        spec = SUPPLEMENT_CONTRACTS[api]
        family = FAMILIES.get(api)
        if family:
            count = len(ids[family])
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [family],
                    "reason": "stored_discovery_completeness_unverified"
                    if count
                    else "awaiting_complete_stored_discovery_for_saturation",
                    "observed_codes": count,
                    "universe_complete": False,
                }
            )
        if spec["history_gap"]:
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_explicit_scope_or_evidence"
                    if starts[api] is None
                    else "configured_scope_does_not_prove_earlier_history_absent",
                }
            )
        known = spec["history_start"]
        if known and starts[api] and starts[api] > _parse(known):
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "configured_start_excludes_documented_history",
                }
            )
    return gaps


def _job(api, params, epoch, priority):
    return {"api_name": api, "params": params, "epoch": epoch, "priority": priority}


def _range(start, end):
    return {"start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")}


def iter_supplement_jobs(config, today, identifiers=None):
    """Recent first; market totals by year, equity/ETF cross-sections by day.

    Use documented source start only where known (moneyflow_dc=20230911). Older
    generic requested ranges are clipped to that documented start, never to an
    inferred first observed row. Missing bounds keep historical-prefix gaps.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    _identifiers(identifiers if identifiers is not None else {}, enabled)
    requested = _requested_starts(config, enabled)
    if any(start and start > today for start in requested.values()):
        raise ValueError("History start cannot be after today")
    starts = {}
    for api in enabled:
        known = SUPPLEMENT_CONTRACTS[api]["history_start"]
        boundary = _parse(known) if known else None
        start = requested[api]
        starts[api] = max(start, boundary) if start and boundary else start or boundary
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    recent = today - timedelta(days=6)
    if BASIC in enabled:
        for level in (None, "一类库", "二类库"):
            yield _job(BASIC, {"bmk_level": level} if level else {}, epoch, 20)
    if MARKET_TOTAL in enabled:
        start = max(recent, starts[MARKET_TOTAL] or recent)
        if start <= today:
            yield _job(MARKET_TOTAL, _range(start, today), epoch, 20)
    day = recent
    while day <= today:
        for api in enabled:
            if api not in (BASIC, MARKET_TOTAL) and day >= (starts[api] or recent):
                yield _job(api, {"trade_date": day.strftime("%Y%m%d")}, epoch, 20)
        day += timedelta(days=1)
    cursors = {a: s for a, s in starts.items() if a != BASIC and s and s < recent}
    while cursors:
        for api, start in tuple(cursors.items()):
            if api == MARKET_TOTAL:
                end = min(date(start.year, 12, 31), recent - timedelta(days=1))
                yield _job(api, _range(start, end), "history", 40)
            else:
                end = start
                yield _job(api, {"trade_date": start.strftime("%Y%m%d")}, "history", 40)
            following = end + timedelta(days=1)
            if following < recent:
                cursors[api] = following
            else:
                del cursors[api]
