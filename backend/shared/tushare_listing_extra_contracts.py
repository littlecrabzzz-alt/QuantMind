"""Pure historical listing, IPO, BSE mapping and market-statistics contracts."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from backend.shared.tushare_structured_contracts import _contract, _parse

FIELDS = {
    "bak_basic": "trade_date ts_code name industry area pe float_share total_share total_assets liquid_assets fixed_assets reserved reserved_pershare eps bvps pb list_date undp per_undp rev_yoy profit_yoy gpr npr holder_num".split(),
    "new_share": "ts_code sub_code name ipo_date issue_date amount market_amount price pe limit_amount funds ballot".split(),
    "bse_mapping": "name o_code n_code list_date".split(),
    "daily_info": "trade_date ts_code ts_name com_count total_share float_share total_mv float_mv amount vol trans_count pe tr exchange".split(),
}
INPUT_FIELDS = {
    "bak_basic": ["trade_date", "ts_code"],
    "new_share": ["start_date", "end_date"],
    "bse_mapping": ["o_code", "n_code"],
    "daily_info": [
        "trade_date",
        "ts_code",
        "exchange",
        "start_date",
        "end_date",
        "fields",
    ],
}
# Values of ts_code, not input parameter names or equity security identities.
DAILY_INFO_STARTS = {
    "SZ_MARKET": "20041231",
    "SZ_MAIN": "20081231",
    "SZ_A": "20080103",
    "SZ_B": "20080103",
    "SZ_GEM": "20091030",
    "SZ_SME": "20040602",
    **dict.fromkeys(
        "SZ_FUND SZ_FUND_ETF SZ_FUND_LOF SZ_FUND_CEF SZ_FUND_SF SZ_BOND SZ_BOND_CN SZ_BOND_REP SZ_BOND_ABS SZ_BOND_GOV SZ_BOND_ENT SZ_BOND_COR SZ_BOND_CB SZ_WR".split(),
        "20080103",
    ),
    "SH_MARKET": "20190102",
    "SH_A": "19910102",
    "SH_B": "19920221",
    "SH_STAR": "20190722",
    "SH_REP": "20190102",
    **dict.fromkeys(
        "SH_FUND SH_FUND_ETF SH_FUND_LOF SH_FUND_REP SH_FUND_CEF SH_FUND_METF".split(),
        "19901219",
    ),
}
_DOCS = {
    "bak_basic": (262, 7000, 5000, "20160101", ("trade_date", "ts_code")),
    "new_share": (123, 2000, 120, None, ("ts_code", "ipo_date", "sub_code")),
    "bse_mapping": (375, 1000, 2000, None, ("o_code", "n_code")),
    "daily_info": (
        215,
        4000,
        600,
        min(DAILY_INFO_STARTS.values()),
        ("trade_date", "ts_code", "exchange"),
    ),
}
LISTING_EXTRA_CONTRACTS = {}
for _api, (_doc, _cap, _points, _start, _keys) in _DOCS.items():
    _nonnull = (
        ("o_code", "n_code")
        if _api == "bse_mapping"
        else ("ts_code", "ipo_date")
        if _api == "new_share"
        else ("trade_date", "ts_code")
    )
    spec = _contract(
        _cap,
        _keys,
        required=FIELDS[_api],
        nullable=[f for f in FIELDS[_api] if f not in _nonnull],
        extra=FIELDS[_api],
        start=_start,
        split=_api in ("new_share", "daily_info"),
        rpm=50,
    )
    spec.update(
        source_url=f"https://tushare.pro/document/2?doc_id={_doc}",
        input_fields=INPUT_FIELDS[_api],
        requested_fields=FIELDS[_api].copy(),
        hidden_fields=[],
        permission_status="unprobed",
        minimum_points=_points,
        independent_permission=None,
        permission_note="Published points are not verified account access. No independent entitlement or numerical account rate is established; 50 rpm is only an operational ceiling.",
        dependencies=[],
        preserve_distinct_rows=True,
        history_bound_verified=False,
        date_field="ipo_date"
        if _api == "new_share"
        else None
        if _api == "bse_mapping"
        else "trade_date",
        history_gap="A documented planning floor is not proof of complete earlier records or point-in-time availability."
        if _start
        else "No earliest history is documented; configured scope does not prove older data absent.",
        pagination_gap="No offset/limit inputs are documented. Exhausted legal partitions remain gaps; never invent pagination from 'loop retrieval'.",
        refresh_gap="Recent overlap does not certify older revisions/deletions. Retain immutable observations and distinct source rows; content identity does not establish supplier event multiplicity.",
        field_note="Request reviewed fields explicitly, audit returned schema and preserve newly observed unknown columns. Nullable source metrics and negative/zero values are not filled or filtered.",
    )
    LISTING_EXTRA_CONTRACTS[_api] = spec

LISTING_EXTRA_CONTRACTS["bak_basic"].update(
    history_precision="year",
    saturation_fallback="stocks",
    saturation_param="ts_code",
    saturation_dependencies=["stocks", "historical_listing_securities"],
    discovery_gap="Historical lists can discover retired or renamed securities missing from today's master. Saturation requires historical/T master plus observed source codes, not current-listed-only filtering; universe completeness remains unverified.",
    unit_note="float_share/total_share and asset measures are in hundred-millions, unlike premarket ten-thousand-share units. Preserve source financial metrics and their undocumented availability dates; this is not a PIT financial-statement replacement.",
)
LISTING_EXTRA_CONTRACTS["new_share"].update(
    split_axis="ipo_date",
    discovery_snapshot=True,
    namespace_note="ts_code is the security code; sub_code is an opaque subscription code (e.g. 780162 vs 601162.SH). Do not infer an exchange from sub_code or merge it into a tradable identity.",
    date_axis_note="Input start_date/end_date filter online issuance (ipo_date), not listing (issue_date). issue_date can be null or future and may be completed after the original issuance window ages out.",
    discovery_gap="An unfiltered recent snapshot discovers supplier-returned past/upcoming issues without inventing a future cutoff. At 2000 rows this snapshot is not complete and has no generic range to bisect; do not derive an exhaustive history or future horizon from its extrema.",
    terminal_gap="A one-day issuance window at cap has no documented ts_code filter. Preserve blocked coverage; a stock-universe fanout would be illegal.",
    unit_note="amount/market_amount/limit_amount are ten-thousand shares; funds is hundred-million CNY. Preserve source pe/ballot scaling and signed/zero values.",
)
LISTING_EXTRA_CONTRACTS["bse_mapping"].update(
    snapshot_only=True,
    namespace_note="Keep o_code/n_code as distinct supplier .BJ source codes and preserve both mapping directions; do not rewrite historical datasets or treat this as an exchange transfer.",
    date_axis_note="list_date is listing date, not code-change effective date. No valid_from/ann_date/date filter is exposed; a snapshot cannot establish a historical alias effective interval.",
    discovery_gap="The page's total below 300 is time-specific. At cap 1000, observed o_code/n_code filters cannot prove missing mappings absent; no dated history or exhaustive code universe is documented.",
)
LISTING_EXTRA_CONTRACTS["daily_info"].update(
    history_precision="per_category_day",
    documented_category_starts=DAILY_INFO_STARTS,
    documented_exchanges=["SH", "SZ"],
    namespace_note="ts_code contains market/category names such as SH_A and SZ_BOND_CB, not stock/index security codes. Keep opaque source labels in a dedicated market-statistics discovery namespace; do not pass them into stocks or equity prefix conversion.",
    discovery_gap="The 31 documented categories have different starts and may change or retire. All-market exact-day requests discover additional categories. A capped day needs reviewed exchange/category partitions; the known table is not proof of future category completeness.",
    field_note="fields is a top-level selector, not a board filter. tr is unavailable for Shenzhen and must allow null; if the whole column is omitted, retain a schema gap and raw evidence pending a verified market-specific contract.",
    unit_note="Shares/volume are hundred-million shares; values/amount hundred-million CNY; trans_count ten-thousand trades. Category units and cross-asset comparability remain supplier semantics, not normalized stock volumes.",
)


def _enabled(config):
    values = config.get("listing_extra_apis", tuple(LISTING_EXTRA_CONTRACTS))
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(a, str) or a not in LISTING_EXTRA_CONTRACTS for a in values
    ):
        raise ValueError("listing_extra_apis must list known APIs")
    return tuple(dict.fromkeys(values))


def _starts(config, enabled):
    setting = config.get("listing_extra_history_start")
    if setting is not None and not isinstance(setting, (str, dict)):
        raise ValueError(
            "listing_extra_history_start must be YYYYMMDD or an API mapping"
        )
    if isinstance(setting, dict) and setting.keys() - LISTING_EXTRA_CONTRACTS.keys():
        raise ValueError("Unknown API in listing_extra_history_start")
    result = {}
    for api in enabled:
        value = setting.get(api) if isinstance(setting, dict) else setting
        if value is None:
            value = config.get("history_start")
        configured = _parse(value) if value is not None else None
        floor = LISTING_EXTRA_CONTRACTS[api]["history_start"]
        floor = _parse(floor) if floor else None
        result[api] = (
            None
            if api == "bse_mapping"
            else max(configured or floor, floor)
            if floor
            else configured
        )
    return result


def listing_extra_prerequisites(identifiers=None, enabled_apis=None, config=None):
    config = dict(config or {})
    if enabled_apis is not None:
        config["listing_extra_apis"] = enabled_apis
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    gaps = []
    for api in enabled:
        for kind in (
            "history_gap",
            "pagination_gap",
            "refresh_gap",
            "discovery_gap",
            "terminal_gap",
        ):
            if LISTING_EXTRA_CONTRACTS[api].get(kind):
                gaps.append(
                    {
                        "api_name": api,
                        "dependencies": [],
                        "reason": kind,
                        "detail": LISTING_EXTRA_CONTRACTS[api][kind],
                    }
                )
        if api != "bse_mapping":
            gaps.append(
                {
                    "api_name": api,
                    "dependencies": [],
                    "reason": "unknown_history_start_requires_scope_or_discovery"
                    if starts[api] is None
                    else "planned_scope_not_verified_complete",
                    "planned_start": starts[api].strftime("%Y%m%d")
                    if starts[api]
                    else None,
                }
            )
    return gaps


def _windows(api, start, end):
    day = start
    while day <= end:
        if api == "new_share":
            last = min(
                end, date(day.year, day.month, monthrange(day.year, day.month)[1])
            )
            yield {
                "start_date": day.strftime("%Y%m%d"),
                "end_date": last.strftime("%Y%m%d"),
            }
            day = last + timedelta(days=1)
        else:
            yield {"trade_date": day.strftime("%Y%m%d")}
            day += timedelta(days=1)


def iter_listing_extra_jobs(config, today, identifiers=None):
    """Recent discovery/dates first; fair lazy history with fixed caller anchor."""
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    enabled = _enabled(config)
    starts = _starts(config, enabled)
    if any(start and start > today for start in starts.values()):
        raise ValueError("History start cannot be after today")
    recent = today - timedelta(days=6)
    epoch = str(config.get("planning_epoch", today.strftime("%Y%m%d")))
    histories = {}
    for api in enabled:
        if api in ("bse_mapping", "new_share"):
            yield {
                "api_name": api,
                "params": {},
                "fields": ",".join(FIELDS[api]),
                "priority": 20,
                "epoch": epoch,
            }
        if api == "bse_mapping":
            continue
        start = starts[api]
        for params in _windows(api, max(start or recent, recent), today):
            yield {
                "api_name": api,
                "params": params,
                "fields": ",".join(FIELDS[api]),
                "priority": 20,
                "epoch": epoch,
            }
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
                    "fields": ",".join(FIELDS[api]),
                    "priority": 55,
                    "epoch": "history",
                }
