# cyq_chips daily quota candidate review

- Base e1481f35; candidate16d32fe6 plus fab8e32a in /private/tmp/quantmind-cyq-chips-daily-quota. Three paths only: daily_quota.py, rate_policy.py, test_tushare_rate_policy.py. No main source edits/deployment yet.
- Reuses API/day ledger; new chips activation day does not issue HTTP or count an attempt, existing perf counters survive. Reporting keeps legacy perf top-level fields and adds per-API views. Day guard uses unknown used/null without remaining. Both caps follow10100→8100 expiry200000→20000.
- Root found a partial-status error: corrupt chips count after ready perf could retain remaining. fab8e32a clears used/remaining on all unavailable entries, tested with valid perf7/chips-1. reserve/activate semantics unchanged.
- Candidate author65 tests passed. Root ran60 applicable tests successfully plus an incorrectly named request_guard module import error; corrected test_tushare_request_contract_guard ran5/5. Ruff check/format/diff passed. Independent next_window_audit review pending.
- Root will wait for currently due normal publisher to finish before any related worker drain. Document/QuantDB remain running. If this candidate is deployed today, cyq_chips alone defers to Beijing next midnight because pre-activation usage is unknown; no authority baseline count is invented.
