# RRG ETF acquisition batch preparation start

- Node: Mac isolated worktree
- Branch: `codex/rrg-acquisition-prep`
- Baseline: `01265aa70bdc67e0e434304a06a441405a21a848`
- Input: reviewed fixed-release audit batch from `data-03885aef45ce7be5ce812f4305734a7c8852646a09cfa567383215d10e5f6d22`.
- Scope: deterministic, sharded, non-enqueuing preparation for fund_div terminal receipts and etf_limit monthly windows; optional fund_daily diagnostics remain separately gated.
- Boundaries: no credentials, upstream calls, production writes, enablement, price filling, suspension inference, PIT inference, or research/trading state changes.
