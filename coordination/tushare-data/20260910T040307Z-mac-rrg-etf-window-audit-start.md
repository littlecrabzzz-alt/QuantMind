# RRG ETF full-window fixed-release audit start

- Node: Mac isolated worktree
- Branch: `codex/rrg-data-closure-next-2`
- Baseline: `68c18fc2676ab1bf7e915dfca5ccda105dc29b9e`
- Scope: read-only audit of the pinned Tushare release for ETF prices, adjustment factors, dividend events, limit/trading-status evidence, PCF holdings, and PIT mapping gaps.
- Boundaries: no credentials, upstream calls, production writes, price filling, current-to-historical mapping inference, or return/trading claims.
- Planned outputs: deterministic offline audit/report and exact bounded missing-input contract with tests.
