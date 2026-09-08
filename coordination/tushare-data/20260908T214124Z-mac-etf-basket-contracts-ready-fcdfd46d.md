# ETF basket contracts ready

Owner: text_contracts; branch codex/tushare-text; commit 95c3ba1, based on parent e7eedbf.
Only new backend/shared/tushare_etf_basket_contracts.py, scripts/test_tushare_etf_basket_contracts.py, docs/tushare-etf-basket-intake.md.

Official doc 471/472 verified: etf_sh_cons / etf_sz_cons, all output fields, 3000 documented rows, 8000 points; no runtime requests or permissions probe. Preserve zero quantities, cash rows, HK components, raw '-' scalars and differing SH/SZ cash semantics. Unknown earliest history, exact publication time, revisions and actual universe remain explicit gaps; no known_at invention.

Exports ETF_BASKET_CONTRACTS, iter_etf_basket_jobs(config,today,identifiers=None), etf_basket_prerequisites(identifiers=None,enabled_apis=None,config=None). Family etfs; recent first, stable scoped historical windows; unknown history emits unfiltered per-ETF discovery and unresolved gap. Standard range date split; single ETF/day saturation not complete, no undocumented pagination or stock-universe fallback. Parent owns registry/pipeline/store integration.

Validation: 6 offline socket-disabled tests passed; Ruff format/check and git diff --check passed. No production/API/config/runtime changes. Ownership released.
