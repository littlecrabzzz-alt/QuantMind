# Tushare off-catalog public history batch ready

- Node/worktree: Mac isolated worktree `/Users/lizeyu/.codex/worktrees/QuantMind-tushare-discovery-next`
- Branch: `codex/tushare-catalog-discovery-next`
- Rebased base: `222a3791cda67d544e8a0d869657665b2f4a6e34` (includes verified `ggt_top10` registration)
- Candidate implementation commit: `1be032ce94c66f968ff3513af2df87201273fa9c`
- Scope: eight default-disabled public read contracts: `film_record`, `teleplay_record`, `bo_monthly`, `bo_weekly`, `bo_daily`, `bo_cinema`, `fund_sales_ratio`, `fund_sales_vol`; 73 documented output fields.
- Runtime: complete registry/planner/store/fixed-release query path, recent-first lazy historical planning, conservative local 30 rpm ceiling, no production/token/provider data call. Enablement requires both `enable_offcatalog=true` and an explicit `offcatalog_apis` list.
- Audit result: 249 named APIs, 238 runtime-readable, 11 unregistered; six public contract gaps remain (`ggt_monthly`, three current minute APIs, two TMT income APIs), plus two private reads, two mutations and one SDK wrapper.
- Validation: Python 3.10.19 full `test_tushare*.py` suite 916 passed, 5 skipped in 44.603s after rebase; focused 29 passed; full Tushare Ruff passed; JSON parse and `git diff --check` passed.
- Required before enablement: bounded real permission/default-field probes for each API, field/null/cap/oldest-history observations; verify the Chinese-labeled `fund_sales_ratio` year wire name before filtered planning. Current page evidence does not prove entitlement, complete history, PIT, corrections or deletions.
