"""Reviewed contracts only; catalogue presence never authorizes an API call."""

from backend.shared.tushare_text_contracts import TEXT_CONTRACTS, iter_text_jobs
from backend.shared.tushare_structured_contracts import (
    STRUCTURED_CONTRACTS,
    iter_structured_jobs,
)

from backend.shared.tushare_market_contracts import MARKET_CONTRACTS, iter_market_jobs
from backend.shared.tushare_rrg_contracts import RRG_CONTRACTS

from backend.shared.tushare_global_contracts import GLOBAL_CONTRACTS, iter_global_jobs

from backend.shared.tushare_other_contracts import OTHER_CONTRACTS, iter_other_jobs
from backend.shared.tushare_supplement_contracts import (
    SUPPLEMENT_CONTRACTS,
    iter_supplement_jobs,
)

from backend.shared.tushare_equity_event_contracts import (
    ANNOUNCEMENTS,
    EQUITY_EVENT_CONTRACTS,
    iter_equity_event_jobs,
)
from backend.shared.tushare_futures_extra_contracts import (
    FUTURES_EXTRA_CONTRACTS,
    iter_futures_extra_jobs,
)
from backend.shared.tushare_research_extra_contracts import (
    RESEARCH_EXTRA_CONTRACTS,
    iter_research_extra_jobs,
)

from backend.shared.tushare_credit_extra_contracts import (
    CREDIT_EXTRA_CONTRACTS,
    iter_credit_extra_jobs,
)

from backend.shared.tushare_etf_basket_contracts import (
    ETF_BASKET_CONTRACTS,
    iter_etf_basket_jobs,
)

from backend.shared.tushare_connect_contracts import (
    CONNECT_CONTRACTS,
    VARIANTS as CONNECT_VARIANTS,
    iter_connect_jobs,
)
from backend.shared.tushare_legacy_connect_contracts import (
    LEGACY_CONNECT_CONTRACTS,
    iter_legacy_connect_jobs,
)
from backend.shared.tushare_offcatalog_contracts import (
    OFFCATALOG_CONTRACTS,
    iter_offcatalog_jobs,
)

from backend.shared.tushare_trading_event_contracts import (
    TRADING_EVENT_CONTRACTS,
    iter_trading_event_jobs,
)

from backend.shared.tushare_listing_extra_contracts import (
    LISTING_EXTRA_CONTRACTS,
    iter_listing_extra_jobs,
)

from backend.shared.tushare_limit_extra_contracts import (
    LIMIT_EXTRA_CONTRACTS,
    iter_limit_extra_jobs,
)

from backend.shared.tushare_concept_extra_contracts import (
    CONCEPT_EXTRA_CONTRACTS,
    iter_concept_extra_jobs,
)

from backend.shared.tushare_dc_extra_contracts import (
    DC_EXTRA_CONTRACTS,
    iter_dc_extra_jobs,
)

from backend.shared.tushare_risk_event_contracts import (
    RISK_EVENT_CONTRACTS,
    iter_risk_event_jobs,
    risk_event_prerequisites,
)

from backend.shared.tushare_technical_extra_contracts import (
    TECHNICAL_EXTRA_CONTRACTS,
    iter_technical_extra_jobs,
    technical_extra_prerequisites,
)

from backend.shared.tushare_foreign_financial_contracts import (
    FOREIGN_FINANCIAL_CONTRACTS,
    iter_foreign_financial_jobs,
    foreign_financial_prerequisites,
)

from backend.shared.tushare_cross_asset_extra_contracts import (
    CROSS_ASSET_EXTRA_CONTRACTS,
    cross_asset_extra_prerequisites,
    cross_asset_identifiers,
    iter_cross_asset_extra_jobs,
)

CROSS_ASSET_NAMESPACES = {
    "idx_factor_pro": "IDX:",
    "fund_factor_pro": "FUND:",
    "cb_factor_pro": "CB:",
    "index_global": "GIDX:",
    "sz_daily_info": "SZBOARD:",
    "etf_limit": "FUND:",
}
CROSS_ASSET_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "cross_asset_extra",
        "dependencies": [],
        "saturation_fallback": spec["saturation_fallback"]
        if spec["saturation_fallback"].startswith("cross_asset_")
        else "cross_asset_" + spec["saturation_fallback"],
        "source_namespace": CROSS_ASSET_NAMESPACES[api],
        "namespace_note": spec["namespace_note"]
        + " Canonical ts_code is "
        + CROSS_ASSET_NAMESPACES[api]
        + " plus the unchanged supplier code; source_ts_code preserves the original. Other datasets are not implicitly joined.",
    }
    for api, spec in CROSS_ASSET_EXTRA_CONTRACTS.items()
}


def cross_asset_runtime_prerequisites(identifiers, config=None):
    projected = {
        spec["saturation_fallback"]: identifiers.get(
            CROSS_ASSET_RUNTIME_CONTRACTS[api]["saturation_fallback"], []
        )
        for api, spec in CROSS_ASSET_EXTRA_CONTRACTS.items()
    }
    names = {
        spec["saturation_fallback"]: CROSS_ASSET_RUNTIME_CONTRACTS[api][
            "saturation_fallback"
        ]
        for api, spec in CROSS_ASSET_EXTRA_CONTRACTS.items()
    }
    return [
        {
            **gap,
            "dependencies": [
                names.get(name, name) for name in gap.get("dependencies", [])
            ],
        }
        for gap in cross_asset_extra_prerequisites(projected, config=config)
    ]


from backend.shared.tushare_market_sentiment_contracts import (
    MARKET_SENTIMENT_CONTRACTS,
    iter_market_sentiment_jobs,
    market_sentiment_prerequisites,
)

MARKET_SENTIMENT_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "market_sentiment",
        "namespace_note": spec["namespace_note"].replace(
            "Runtime normalization is not implemented by this pure module.",
            "Runtime projection uses immutable request market; unknown market remains UNVERIFIED_MARKET and missing request identity blocks fixed reads.",
        ),
        "canonical_namespace_note": "TDX:/KP: board codes; THS:I:/THS:N: ranking boards; FUND: ETF/funds; CB: convertibles; FUT: futures; validated CN suffix identities become exchange prefix including T, validated HK suffix identities become HK prefix including historical !, US symbols retain opaque source spelling after US prefix. Unknown source spellings retain explicit asset namespace; source_ts_code/source_con_code remain unchanged. Cross-dataset source joins still require verified market and date semantics.",
    }
    for api, spec in MARKET_SENTIMENT_CONTRACTS.items()
}

from backend.shared.tushare_history_minutes_contracts import (
    HISTORY_MINUTES_CONTRACTS, iter_history_minutes_jobs, history_minutes_prerequisites,
)

HISTORY_MINUTES_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "history_minutes"}
    for api, spec in HISTORY_MINUTES_CONTRACTS.items()
}
# Source endpoint, not code shape, determines asset family. Keep old family
# discovery unchanged and use observations (including expired/delisted rows).
MINUTE_SOURCE_FAMILIES = {
    **{api: spec["dependencies"][0] for api, spec in HISTORY_MINUTES_CONTRACTS.items()},
    **dict.fromkeys(("stock_basic", "daily", "daily_basic", "adj_factor", "weekly", "monthly", "bak_basic"), "minute_stocks"),
    **dict.fromkeys(("etf_basic", "etf_share_size", "etf_limit"), "minute_etfs"),
    **dict.fromkeys(("index_basic", "index_daily", "idx_factor_pro", "ci_daily"), "minute_indexes"),
    **dict.fromkeys(("index_classify", "sw_daily"), "minute_sw_indexes"),
    **dict.fromkeys(("fut_basic", "fut_daily", "fut_mapping"), "minute_futures"),
    **dict.fromkeys(("opt_basic", "opt_daily"), "minute_options"),
    **dict.fromkeys(("hk_basic", "hk_daily", "hk_daily_adj"), "minute_hk_stocks"),
}


def history_minutes_runtime_prerequisites(identifiers=None, config=None):
    gaps = history_minutes_prerequisites(identifiers, config=config)
    if (identifiers or {}).get("minute_futures_unmapped") and "ft_mins" in (config or {}).get("history_minutes_apis", HISTORY_MINUTES_CONTRACTS):
        gaps.append({"api_name": "ft_mins", "dependencies": ["minute_futures_unmapped"],
                     "reason": "continuous_symbols_require_dated_actual_contract_mapping",
                     "observed_unmapped": len(identifiers["minute_futures_unmapped"]),
                     "universe_complete": False})
    return gaps


from backend.shared.tushare_calendar_extra_contracts import (
    CALENDAR_EXTRA_CONTRACTS,
    iter_calendar_extra_jobs,
    calendar_extra_prerequisites,
)
from backend.shared.tushare_factor_library_contracts import (
    FACTOR_LIBRARY_CONTRACTS,
    iter_factor_library_jobs,
    factor_library_prerequisites,
)

CALENDAR_EXTRA_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "calendar_extra"}
    for api, spec in CALENDAR_EXTRA_CONTRACTS.items()
}
FACTOR_LIBRARY_RUNTIME_CONTRACTS = {
    api: {
        **spec, "group": "factor_library",
        **({"saturation_fallback": "factor_library_stocks",
            "saturation_dependencies": ["factor_library_stocks"]}
           if api == "factor_value" else {}),
    }
    for api, spec in FACTOR_LIBRARY_CONTRACTS.items()
}

# Independent planning scope, deliberately absent from PLANNERS consumption
# groups. Contracts, job identities, permissions and fair group remain unchanged.
MARKET_MEMBER_APIS = ("tdx_member", "kpl_concept_cons")
MARKET_MEMBER_DEPENDENCIES = {
    "tdx_member": "tdx_indices", "kpl_concept_cons": "kpl_concepts"
}


def _market_member_config(config):
    if not config.get("enable_market_sentiment"):
        raise ValueError("market_members requires enabled market_sentiment group")
    old = config.get("market_sentiment_apis", tuple(MARKET_SENTIMENT_CONTRACTS))
    if (
        not isinstance(old, (list, tuple))
        or any(not isinstance(api, str) or api not in MARKET_SENTIMENT_CONTRACTS for api in old)
        or set(old).intersection(MARKET_MEMBER_APIS)
    ):
        raise ValueError("market_sentiment_apis must exclude both member APIs")
    selected = config.get("market_members_apis", MARKET_MEMBER_APIS)
    if not isinstance(selected, (list, tuple)) or not selected or any(
        api not in MARKET_MEMBER_APIS for api in selected
    ):
        raise ValueError("market_members_apis must select reviewed member APIs")
    start = config.get("market_members_history_start")
    if isinstance(start, dict) and set(start) - set(MARKET_MEMBER_APIS):
        raise ValueError("Unknown market_members history API")
    # The old family's start is not evidence for this new scope's history.
    return {
        "market_sentiment_apis": list(dict.fromkeys(selected)),
        "market_sentiment_history_start": start,
        **({"planning_epoch": config["planning_epoch"]} if "planning_epoch" in config else {}),
    }


def _market_member_codes(identifiers, selected):
    import re

    result = {}
    for api in selected:
        codes = identifiers.get(MARKET_MEMBER_DEPENDENCIES[api], [])
        suffix = "TDX" if api == "tdx_member" else "KP"
        if not isinstance(codes, (list, tuple, set)) or any(
            not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\." + suffix, code)
            for code in codes
        ):
            raise ValueError("Invalid observed member board namespace: " + api)
        result[api] = sorted(set(codes))
    return result


def market_member_prerequisites(identifiers=None, config=None):
    projected = _market_member_config(config or {})
    selected = projected["market_sentiment_apis"]
    codes = _market_member_codes(identifiers or {}, selected)
    gaps = market_sentiment_prerequisites(identifiers, config=projected)
    for api in selected:
        gaps.append({
            "api_name": api, "dependencies": [MARKET_MEMBER_DEPENDENCIES[api]],
            "reason": "observed_board_scope_not_universe",
            "observed_boards": len(codes[api]), "universe_complete": False,
            "detail": "Bulk discovery plus observed boards; second member axis, historical universe and PIT remain unverified.",
        })
    return gaps


def iter_market_member_jobs(config, today, identifiers=None):
    projected = _market_member_config(config)
    codes = _market_member_codes(identifiers or {}, projected["market_sentiment_apis"])
    for job in iter_market_sentiment_jobs(projected, today, identifiers):
        # Retain the bulk request: known boards must not hide future discoveries.
        yield job
        for code in codes[job["api_name"]]:
            yield {**job, "params": {**job["params"], "ts_code": code}}


APPEND_PLANNERS = {"market_members": iter_market_member_jobs}


from backend.shared.tushare_bond_extra_contracts import (
    BOND_EXTRA_CONTRACTS,
    iter_bond_extra_jobs,
    bond_extra_prerequisites,
)

BOND_EXTRA_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "bond_extra",
        "dependencies": ["bond_extra_convertibles"] if spec["dependencies"] else [],
        "source_namespace": spec["source_namespace"].split("<", 1)[0],
        "namespace_note": spec["namespace_note"].replace(
            "Namespace conversion belongs to future runtime integration, not this pure planner.", ""
        )
        + " Runtime prefixes the unchanged source string with this asset namespace and preserves source_ts_code. Non-string source codes require schema review; no inferred curve-code alias or A-share conversion.",
    }
    for api, spec in BOND_EXTRA_CONTRACTS.items()
}


def _bond_extra_identifiers(identifiers):
    return {"bonds": identifiers.get("bond_extra_convertibles", [])}


def bond_extra_runtime_prerequisites(identifiers, config=None):
    return [
        {**gap, "dependencies": ["bond_extra_convertibles" if name == "bonds" else name for name in gap.get("dependencies", [])]}
        for gap in bond_extra_prerequisites(_bond_extra_identifiers(identifiers), config=config)
    ]


FOREIGN_FINANCIAL_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "foreign_financial",
        "date_field": "end_date",
        "requested_fields": list(spec["extra_fields"]),
    }
    for api, spec in FOREIGN_FINANCIAL_CONTRACTS.items()
}


def _foreign_financial_identifiers(identifiers):
    return {name: identifiers.get(name, []) for name in ("hk_stocks", "us_stocks")}


def foreign_financial_runtime_prerequisites(identifiers, config=None):
    return foreign_financial_prerequisites(
        _foreign_financial_identifiers(identifiers), config=config
    )


from backend.shared.tushare_stock_context_contracts import (
    STOCK_CONTEXT_CONTRACTS,
    iter_stock_context_jobs,
    stock_context_prerequisites,
)

STOCK_CONTEXT_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "stock_context",
        "dependencies": [{"stocks": "stock_context_stocks", "reward_periods": "stock_context_reward_periods"}[dep] for dep in spec.get("dependencies", [])],
        "saturation_fallback": "stock_context_stocks",
        "saturation_dependencies": ["stock_context_stocks"],
    }
    for api, spec in STOCK_CONTEXT_CONTRACTS.items()
}

STOCK_CONTEXT_RUNTIME_CONTRACTS["stk_ah_comparison"]["namespace_note"] = (
    STOCK_CONTEXT_CONTRACTS["stk_ah_comparison"]["namespace_note"].replace(
        "HK canonical field projection still needs runtime integration.",
        "Runtime canonicalizes only validated five-digit HK suffix identities; unknown shapes remain source values and require namespace review.",
    )
)


def _stock_context_identifiers(identifiers):
    return {
        "stocks": identifiers.get("stock_context_stocks", []),
        "reward_periods": identifiers.get("stock_context_reward_periods", []),
    }


def stock_context_runtime_prerequisites(identifiers, config=None):
    return [
        {
            **gap,
            "dependencies": ["stock_context_stocks"] if gap.get("dependencies") else [],
        }
        for gap in stock_context_prerequisites(
            _stock_context_identifiers(identifiers), config=config
        )
    ]


def iter_reward_period_append_jobs(config, today, identifiers=None):
    """Only observed supplements; same source contract, group and history IDs."""
    ids = {"reward_periods": (identifiers or {}).get("stock_context_reward_periods", [])}
    for job in iter_stock_context_jobs({"stock_context_apis": ["stk_rewards"]}, today, ids):
        if job["epoch"] == "history":
            yield job


APPEND_PLANNERS["stock_rewards_periods"] = iter_reward_period_append_jobs


def iter_equity_announcement_jobs(config, today, identifiers=None):
    """History-only all-market announcements, independent of stock fanout."""
    selected = [
        api
        for api in config.get("equity_event_apis", EQUITY_EVENT_CONTRACTS)
        if api in ANNOUNCEMENTS
    ]
    projected = {
        "equity_event_apis": selected,
        **(
            {"history_start": config["history_start"]}
            if "history_start" in config
            else {}
        ),
        **(
            {"equity_event_history_start": config["equity_event_history_start"]}
            if "equity_event_history_start" in config
            else {}
        ),
        **(
            {"planning_epoch": config["planning_epoch"]}
            if "planning_epoch" in config
            else {}
        ),
    }
    for job in iter_equity_event_jobs(projected, today, identifiers):
        if job["epoch"] == "history":
            yield job


APPEND_PLANNERS["equity_announcements"] = iter_equity_announcement_jobs


def iter_fund_share_history_jobs(config, today, identifiers=None):
    """History-only fund-share dates, independent of the larger market cursor."""
    projected = {
        "market_apis": ["fund_share"],
        "history_start": config["history_start"],
        **(
            {"planning_epoch": config["planning_epoch"]}
            if "planning_epoch" in config
            else {}
        ),
    }
    for job in iter_market_jobs(projected, today, identifiers):
        if job["epoch"] == "history":
            yield job


APPEND_PLANNERS["fund_share_history"] = iter_fund_share_history_jobs


TECHNICAL_EXTRA_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "technical_extra",
        "dependencies": ["technical_stocks"] if spec.get("dependencies") else [],
        "saturation_fallback": "technical_stocks",
        "saturation_dependencies": ["technical_stocks"],
    }
    for api, spec in TECHNICAL_EXTRA_CONTRACTS.items()
}


def _technical_identifiers(identifiers):
    return {"stocks": identifiers.get("technical_stocks", [])}


def technical_extra_runtime_prerequisites(identifiers, config=None):
    return [
        {**gap, "dependencies": ["technical_stocks"] if gap.get("dependencies") else []}
        for gap in technical_extra_prerequisites(
            _technical_identifiers(identifiers), config=config
        )
    ]


RISK_EVENT_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "risk_event",
        "dependencies": ["risk_stocks"] if api == "st" else [],
        "saturation_fallback": "risk_securities"
        if api == "stk_alert"
        else "risk_stocks",
        "saturation_dependencies": [
            "risk_securities" if api == "stk_alert" else "risk_stocks"
        ],
    }
    for api, spec in RISK_EVENT_CONTRACTS.items()
}


def _risk_identifiers(identifiers):
    # The pure planner's logical stocks dependency uses a wider, isolated
    # historical-risk discovery family; never mutate other planners' stocks.
    return {"stocks": identifiers.get("risk_stocks", [])}


def risk_event_runtime_prerequisites(identifiers, config=None):
    return [
        {**gap, "dependencies": ["risk_stocks"] if gap.get("dependencies") else []}
        for gap in risk_event_prerequisites(
            _risk_identifiers(identifiers), config=config
        )
    ]


DC_EXTRA_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "dc_extra"} for api, spec in DC_EXTRA_CONTRACTS.items()
}

CONCEPT_EXTRA_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "concept_extra"}
    for api, spec in CONCEPT_EXTRA_CONTRACTS.items()
}

LIMIT_EXTRA_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "limit_extra"} for api, spec in LIMIT_EXTRA_CONTRACTS.items()
}

LISTING_EXTRA_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "listing_extra",
        **(
            {"saturation_fallback": "historical_listing_securities"}
            if api == "bak_basic"
            else {}
        ),
        **(
            {
                "saturation_fallback": "market_stat_categories",
                "saturation_param": "ts_code",
            }
            if api == "daily_info"
            else {}
        ),
    }
    for api, spec in LISTING_EXTRA_CONTRACTS.items()
}

TRADING_EVENT_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "trading_event",
        **(
            {"saturation_fallback": "trading_event_securities"}
            if api != "hm_list"
            else {}
        ),
    }
    for api, spec in TRADING_EVENT_CONTRACTS.items()
}

CONNECT_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "connect",
        "request_identity_fields": list(CONNECT_VARIANTS.get(api, [{}])[0]),
        "row_identity_note": "Keep distinct source rows and immutable request type/market_type/content_type; an identical response under different requested channels is not interchangeable coverage evidence.",
    }
    for api, spec in CONNECT_CONTRACTS.items()
}

LEGACY_CONNECT_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "legacy_connect"}
    for api, spec in LEGACY_CONNECT_CONTRACTS.items()
}

OFFCATALOG_RUNTIME_CONTRACTS = {
    api: {**spec, "group": "offcatalog"}
    for api, spec in OFFCATALOG_CONTRACTS.items()
}

from backend.shared.tushare_securities_lending_history_contracts import (
    SECURITIES_LENDING_HISTORY_CONTRACTS,
    iter_securities_lending_history_jobs,
    securities_lending_history_prerequisites,
)

SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "group": "securities_lending_history",
        "requested_fields": list(spec["extra_fields"]),
        "date_field": "trade_date",
        "namespace_note": "Supplier stock codes retain source_ts_code; internal SH/SZ/BJ prefixes preserve distinct historical T identities.",
    }
    for api, spec in SECURITIES_LENDING_HISTORY_CONTRACTS.items()
}

from backend.shared.tushare_account_history_contracts import (
    ACCOUNT_HISTORY_CONTRACTS,
    iter_account_history_jobs,
    account_history_prerequisites,
    project_account_period,
)

ACCOUNT_HISTORY_RUNTIME_CONTRACTS = {
    api: {
        **spec,
        "date_field": "date",
        "local_date_filter_note": (
            "Default date filtering uses inclusive overlap of the recognized source "
            "period; explicit _period_start or _period_end filters that endpoint. "
            "This local interpretation does not establish supplier range semantics."
            if api == "stk_account_old" else
            "Date filtering compares the weekly source label without inventing a week start or a trading-day series."
        ),
    }
    for api, spec in ACCOUNT_HISTORY_CONTRACTS.items()
}

# Output period parsing does not establish the supplier's range-selection axis.
# Keep a saturated old-series window unresolved until that coverage is proven.
ACCOUNT_HISTORY_RUNTIME_CONTRACTS["stk_account_old"].update(
    split=None,
    saturation_gap="Unverified local1000-row guard. Automatic range subdivision is disabled while supplier period-range coverage is unknown; retain raw/Parquet and the unresolved cap, with no invented offset or date parameter.",
)

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re

from backend.shared.tushare_realtime_extra_contracts import (
    REALTIME_EXTRA_CONTRACTS, iter_realtime_extra_jobs, realtime_extra_prerequisites,
)
from backend.shared.tushare_realtime_replay_contracts import (
    REALTIME_REPLAY_CONTRACTS, iter_realtime_replay_jobs, realtime_replay_prerequisites,
)
from backend.shared.tushare_discovered_contracts import _epoch as _realtime_epoch

REALTIME_SOURCE_FAMILIES = {
    "stk_auction": "realtime_auction_untyped", "rt_k": "realtime_stocks",
    "rt_min": "realtime_stocks",
    "rt_etf_k": "realtime_etfs", "rt_etf_sz_iopv": "realtime_etfs",
    "rt_etf_min": "realtime_etfs", "rt_etf_min_daily": "realtime_etfs",
    "rt_idx_k": "realtime_indexes", "rt_idx_min": "realtime_indexes",
    "rt_idx_min_daily": "realtime_indexes", "rt_sw_k": "realtime_sw_indexes",
    "rt_fut_min": "realtime_futures", "rt_fut_min_daily": "realtime_futures",
}
REALTIME_DISCOVERY_INPUTS = {
    "stocks": ("stocks", "minute_stocks", "realtime_stocks"),
    "etfs": ("etfs", "minute_etfs", "realtime_etfs"),
    "indexes": ("indexes", "minute_indexes", "realtime_indexes"),
    "sw_indexes": ("sw_indexes", "minute_sw_indexes", "realtime_sw_indexes"),
    "minute_futures": ("minute_futures", "realtime_futures"),
}
REALTIME_RUNTIME_CONTRACTS = {}
for _api, _spec in {**REALTIME_EXTRA_CONTRACTS, **REALTIME_REPLAY_CONTRACTS}.items():
    _optional = {
        "stk_auction": ["ts_type"], "rt_etf_k": ["topic"],
        "rt_fut_min_daily": ["date_str"],
    }.get(_api, [])
    REALTIME_RUNTIME_CONTRACTS[_api] = {
        **_spec,
        "optional_request_identity_fields": _optional,
        "dependencies": sorted({name for dep in _spec.get("dependencies", [])
                                for name in REALTIME_DISCOVERY_INPUTS.get(dep, (dep,))}),
        "realtime_dispatch_guard": _api != "stk_auction",
        "request_identity_note": "Documented omitted optional dimensions are stored as explicit null request identity, distinct from supplied values; required frequency/source dimensions remain mandatory.",
    }
REALTIME_RUNTIME_CONTRACTS["stk_auction"]["group"] = "realtime_auction"
REALTIME_RUNTIME_CONTRACTS["stk_auction"]["namespace_gap"] += (
    " Untyped rows use AUCTION_UNTYPED: plus original code until independently classified; they are not added to stock discovery. Explicit STK/ETF request variants remain distinct."
)
REALTIME_RUNTIME_CONTRACTS["rt_fut_min"].update(
    allowed_params=["ts_code", "freq"],
    catalog_gap="Catalog340 includes date_str from the separate daily table. Runtime enqueue uses this API's reviewed output fields only, never the contaminated input name as an output field.",
)


def realtime_identifiers(identifiers):
    ids = identifiers or {}
    projected = {
        target: sorted({value for source in sources for value in ids.get(source, [])})
        for target, sources in REALTIME_DISCOVERY_INPUTS.items()
    }
    # No automatic producer for eligibility evidence yet; current replay remains
    # usable while prior-day scope stays explicitly blocked, never config-guessed.
    projected["realtime_replay_futures_windows"] = {}
    return projected


def _realtime_config(config, today, family):
    adjusted = dict(config)
    key = family + "_snapshot_epoch"
    try:
        _realtime_epoch({"discovered_snapshot_epoch": config.get(key)}, today)
    except ValueError:
        adjusted[key] = None  # Does not mutate persisted config or auction history.
    return adjusted


def _auction_config(config):
    selected = config.get("realtime_auction_apis", ["stk_auction"])
    if not isinstance(selected, (list, tuple)) or any(api != "stk_auction" for api in selected):
        raise ValueError("realtime_auction_apis only accepts stk_auction")
    return {**config, "enable_realtime_extra": config.get("enable_realtime_auction", False),
            "realtime_extra_apis": list(dict.fromkeys(selected)),
            "realtime_extra_history_start": config.get("realtime_auction_history_start", config.get("history_start", "20250101")),
            "realtime_extra_snapshot_epoch": None}


def realtime_runtime_prerequisites(identifiers=None, config=None, *, family="realtime_extra"):
    config = config or {}
    if family == "realtime_auction":
        return realtime_extra_prerequisites(realtime_identifiers(identifiers), config=_auction_config(config))
    if family == "realtime_extra":
        config = {**config, "realtime_extra_apis": config.get("realtime_extra_apis", [a for a in REALTIME_EXTRA_CONTRACTS if a != "stk_auction"])}
        if "stk_auction" in config["realtime_extra_apis"]:
            raise ValueError("stk_auction uses the separate realtime_auction history scope")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    adjusted = _realtime_config(config, today, family)
    pure = realtime_extra_prerequisites if family == "realtime_extra" else realtime_replay_prerequisites
    gaps = pure(realtime_identifiers(identifiers), config=adjusted)
    if adjusted.get(family + "_snapshot_epoch") != config.get(family + "_snapshot_epoch"):
        for api in config.get(family + "_apis", (
            REALTIME_EXTRA_CONTRACTS if family == "realtime_extra" else REALTIME_REPLAY_CONTRACTS
        )):
            if api != "stk_auction":
                gaps.append({"api_name": api, "reason": "stale_or_invalid_config_snapshot_epoch", "detail": "No stale epoch is replayed; set a new explicit current slot after authorization."})
    return gaps


def iter_realtime_runtime_jobs(config, today, identifiers, *, family="realtime_extra"):
    if family == "realtime_auction":
        yield from iter_realtime_extra_jobs(_auction_config(config), today, realtime_identifiers(identifiers))
        return
    if family == "realtime_extra":
        config = {**config, "realtime_extra_apis": config.get("realtime_extra_apis", [a for a in REALTIME_EXTRA_CONTRACTS if a != "stk_auction"])}
        if "stk_auction" in config["realtime_extra_apis"]:
            raise ValueError("stk_auction uses the separate realtime_auction history scope")
    pure = iter_realtime_extra_jobs if family == "realtime_extra" else iter_realtime_replay_jobs
    yield from pure(_realtime_config(config, today, family), today, realtime_identifiers(identifiers))


def realtime_dispatch_status(api, epoch, config, now):
    """Return durable rejection state, or None; never changes another family."""
    spec = REALTIME_RUNTIME_CONTRACTS.get(api)
    if not spec or not spec["realtime_dispatch_guard"]:
        return None
    family = spec["group"]
    if not config.get("enable_" + family) or api not in config.get(family + "_apis", REALTIME_RUNTIME_CONTRACTS):
        return "snapshot_disabled"
    if not isinstance(epoch, str) or not re.fullmatch(r"snapshot-[0-9]{8}T[0-9]{6}Z", epoch):
        return "snapshot_invalid_epoch"
    try:
        planned = datetime.strptime(epoch, "snapshot-%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "snapshot_invalid_epoch"
    actual = datetime.fromtimestamp(now, timezone.utc)
    if planned > actual:
        return "snapshot_future_epoch"
    if planned.astimezone(ZoneInfo("Asia/Shanghai")).date() != actual.astimezone(ZoneInfo("Asia/Shanghai")).date():
        return "snapshot_expired"
    configured = config.get(family + "_snapshot_epoch")
    if not isinstance(configured, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", configured):
        return "snapshot_invalid_config_epoch"
    try:
        current_slot = datetime.strptime(configured, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "snapshot_invalid_config_epoch"
    if current_slot > actual or current_slot.astimezone(ZoneInfo("Asia/Shanghai")).date() != actual.astimezone(ZoneInfo("Asia/Shanghai")).date():
        return "snapshot_invalid_config_epoch"
    if planned != current_slot:
        return "snapshot_superseded"
    return None


def project_realtime_row(api, row, params):
    spec = REALTIME_RUNTIME_CONTRACTS[api]
    field = spec["source_code_field"]
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError("Realtime source code requires schema review")
    if api in (
        "rt_idx_min", "rt_idx_min_daily", "rt_fut_min", "rt_fut_min_daily",
        "rt_min", "rt_etf_min", "rt_etf_min_daily",
    ):
        requested = params.get("ts_code")
        codes = (
            requested.split(",")
            if isinstance(requested, str)
            and api in ("rt_idx_min", "rt_fut_min", "rt_min", "rt_etf_min")
            else [requested]
        )
        if value not in codes or ("freq" in row and row["freq"] != params.get("freq")):
            raise ValueError("Realtime source code/frequency does not match immutable request")
    row["source_" + field] = value
    kind = (params.get("ts_type") or "AUCTION_UNTYPED") if api == "stk_auction" else (
        "STK" if api in ("rt_k", "rt_min") else "ETF" if api in (
            "rt_etf_k", "rt_etf_sz_iopv", "rt_etf_min", "rt_etf_min_daily"
        )
        else "FUT" if api in ("rt_fut_min", "rt_fut_min_daily") else "IDX"
    )
    if kind == "STK" and re.fullmatch(r"T?[0-9]{6}\.(SH|SZ|BJ)", value):
        symbol, exchange = value.rsplit(".", 1)
        canonical = exchange + symbol
    else:
        canonical = {"ETF": "FUND", "STK": "STK_UNVERIFIED"}.get(kind, kind) + ":" + value
    row[field] = canonical
    if field == "code":
        row["source_ts_code"] = value
        row["ts_code"] = canonical
    return row


EXTENDED_CONTRACTS = {
    **{api: {**spec, "group": "rrg"} for api, spec in RRG_CONTRACTS.items()},
    **REALTIME_RUNTIME_CONTRACTS,
    **ACCOUNT_HISTORY_RUNTIME_CONTRACTS,
    **SECURITIES_LENDING_HISTORY_RUNTIME_CONTRACTS,
    **HISTORY_MINUTES_RUNTIME_CONTRACTS,
    **CALENDAR_EXTRA_RUNTIME_CONTRACTS,
    **FACTOR_LIBRARY_RUNTIME_CONTRACTS,
    **BOND_EXTRA_RUNTIME_CONTRACTS,
    **CROSS_ASSET_RUNTIME_CONTRACTS,
    **MARKET_SENTIMENT_RUNTIME_CONTRACTS,
    **FOREIGN_FINANCIAL_RUNTIME_CONTRACTS,
    **STOCK_CONTEXT_RUNTIME_CONTRACTS,
    **TECHNICAL_EXTRA_RUNTIME_CONTRACTS,
    **RISK_EVENT_RUNTIME_CONTRACTS,
    **DC_EXTRA_RUNTIME_CONTRACTS,
    **CONCEPT_EXTRA_RUNTIME_CONTRACTS,
    **LIMIT_EXTRA_RUNTIME_CONTRACTS,
    **LISTING_EXTRA_RUNTIME_CONTRACTS,
    **TRADING_EVENT_RUNTIME_CONTRACTS,
    **CONNECT_RUNTIME_CONTRACTS,
    **LEGACY_CONNECT_RUNTIME_CONTRACTS,
    **OFFCATALOG_RUNTIME_CONTRACTS,
    **{
        api: {**spec, "group": "etf_basket"}
        for api, spec in ETF_BASKET_CONTRACTS.items()
    },
    **{
        api: {**spec, "group": "credit_extra"}
        for api, spec in CREDIT_EXTRA_CONTRACTS.items()
    },
    **{
        api: {**spec, "group": "futures_extra"}
        for api, spec in FUTURES_EXTRA_CONTRACTS.items()
    },
    **{
        api: {**spec, "group": "research_extra"}
        for api, spec in RESEARCH_EXTRA_CONTRACTS.items()
    },
    **{
        api: {**spec, "group": "equity_event"}
        for api, spec in EQUITY_EVENT_CONTRACTS.items()
    },
    **{
        api: {**spec, "group": "supplement"}
        for api, spec in SUPPLEMENT_CONTRACTS.items()
    },
    **{api: {**spec, "group": "other"} for api, spec in OTHER_CONTRACTS.items()},
    **{api: {**spec, "group": "global"} for api, spec in GLOBAL_CONTRACTS.items()},
    **{api: {**spec, "group": "market"} for api, spec in MARKET_CONTRACTS.items()},
    **{api: {**spec, "group": "text"} for api, spec in TEXT_CONTRACTS.items()},
    **{
        api: {**spec, "group": "structured"}
        for api, spec in STRUCTURED_CONTRACTS.items()
    },
}
PLANNERS = {
    "realtime_auction": lambda config, today, ids: iter_realtime_runtime_jobs(config, today, ids, family="realtime_auction"),
    "realtime_extra": iter_realtime_runtime_jobs,
    "realtime_replay": lambda config, today, ids: iter_realtime_runtime_jobs(config, today, ids, family="realtime_replay"),
    "account_history": iter_account_history_jobs,
    "securities_lending_history": iter_securities_lending_history_jobs,
    "history_minutes": iter_history_minutes_jobs,
    "calendar_extra": iter_calendar_extra_jobs,
    "factor_library": iter_factor_library_jobs,
    "bond_extra": lambda config, today, ids: iter_bond_extra_jobs(config, today, _bond_extra_identifiers(ids)),
    "cross_asset_extra": iter_cross_asset_extra_jobs,
    "market_sentiment": iter_market_sentiment_jobs,
    "foreign_financial": lambda config, today, ids: iter_foreign_financial_jobs(
        config, today, _foreign_financial_identifiers(ids)
    ),
    "stock_context": lambda config, today, ids: iter_stock_context_jobs(
        config, today, _stock_context_identifiers(ids)
    ),
    "technical_extra": lambda config, today, ids: iter_technical_extra_jobs(
        config, today, _technical_identifiers(ids)
    ),
    "risk_event": lambda config, today, ids: iter_risk_event_jobs(
        config, today, _risk_identifiers(ids)
    ),
    "dc_extra": iter_dc_extra_jobs,
    "concept_extra": iter_concept_extra_jobs,
    "limit_extra": iter_limit_extra_jobs,
    "listing_extra": iter_listing_extra_jobs,
    "trading_event": iter_trading_event_jobs,
    "connect": iter_connect_jobs,
    "legacy_connect": iter_legacy_connect_jobs,
    "offcatalog": iter_offcatalog_jobs,
    "etf_basket": iter_etf_basket_jobs,
    "credit_extra": iter_credit_extra_jobs,
    "text": lambda config, today, ids: iter_text_jobs(config, today),
    "structured": iter_structured_jobs,
    "market": iter_market_jobs,
    "global": iter_global_jobs,
    "other": iter_other_jobs,
    "supplement": iter_supplement_jobs,
    "equity_event": iter_equity_event_jobs,
    "futures_extra": iter_futures_extra_jobs,
    "research_extra": iter_research_extra_jobs,
}


def contract_for(api):
    return EXTENDED_CONTRACTS.get(api, {})
