"""Reviewed contracts only; catalogue presence never authorizes an API call."""

from backend.shared.tushare_text_contracts import TEXT_CONTRACTS, iter_text_jobs
from backend.shared.tushare_structured_contracts import (
    STRUCTURED_CONTRACTS,
    iter_structured_jobs,
)

from backend.shared.tushare_market_contracts import MARKET_CONTRACTS, iter_market_jobs

EXTENDED_CONTRACTS = {
    **{api: {**spec, "group": "market"} for api, spec in MARKET_CONTRACTS.items()},
    **{api: {**spec, "group": "text"} for api, spec in TEXT_CONTRACTS.items()},
    **{
        api: {**spec, "group": "structured"}
        for api, spec in STRUCTURED_CONTRACTS.items()
    },
}
PLANNERS = {
    "text": lambda config, today, ids: iter_text_jobs(config, today),
    "structured": iter_structured_jobs,
    "market": iter_market_jobs,
}


def contract_for(api):
    return EXTENDED_CONTRACTS.get(api, {})
