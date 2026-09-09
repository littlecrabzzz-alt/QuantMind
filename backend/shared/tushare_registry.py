"""Reviewed contracts only; catalogue presence never authorizes an API call."""

from backend.shared.tushare_text_contracts import TEXT_CONTRACTS, iter_text_jobs
from backend.shared.tushare_structured_contracts import (
    STRUCTURED_CONTRACTS,
    iter_structured_jobs,
)

from backend.shared.tushare_market_contracts import MARKET_CONTRACTS, iter_market_jobs

from backend.shared.tushare_global_contracts import GLOBAL_CONTRACTS, iter_global_jobs

from backend.shared.tushare_other_contracts import OTHER_CONTRACTS, iter_other_jobs
from backend.shared.tushare_supplement_contracts import (
    SUPPLEMENT_CONTRACTS,
    iter_supplement_jobs,
)

from backend.shared.tushare_equity_event_contracts import (
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
        "dependencies": ["stock_context_stocks"] if spec.get("dependencies") else [],
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
    return {"stocks": identifiers.get("stock_context_stocks", [])}


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

EXTENDED_CONTRACTS = {
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
