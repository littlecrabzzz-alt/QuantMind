# `fina_mainbz_vip` legacy contract retirement start

- Owner: Mac Tushare archive authority.
- Scope: extend the existing VIP coverage compactor so an old no-pagination blocker is superseded only after the same period/type has a complete, gap-free 10,000-row pagination chain under the live-verified contract.
- Production evidence: all 239 old blocked period/type requests currently match one of 299 complete modern chains; 139 other modern roots remain empty/open and are not coverage evidence.
- Safety boundary: preserve every old result, attempt, raw object, observation and Parquet artifact; do not retire incomplete chains, recent jobs, ordinary stock jobs outside existing full-year coverage, shared partition children, or any unrelated state. No upstream requests are part of retirement.

