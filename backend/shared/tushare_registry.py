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

EXTENDED_CONTRACTS = {
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
