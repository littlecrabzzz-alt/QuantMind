# RRG PIT/ETF fixed-release bridge start

- UTC 2026-09-10 03:19:59; Mac; `rrg_data_closure_next`.
- Status: in progress. Branch `codex/rrg-data-closure-next`, isolated worktree `/Users/lizeyu/.codex/worktrees/quantmind-rrg-data-closure-next`, baseline `origin/master` `9ce875e0`.
- Scope: new fixed-release, offline RRG bridge and tests/docs only. It will map existing `ci_index_member`, ETF daily/adjustment, announcement-bounded `fund_portfolio`, and exact-day exchange baskets while retaining explicit PIT/tradability gaps. No shared main-tree edit, credentials, upstream call, production write, research promotion, or strategy/backtest.
- Existing evidence: `ci_index_member` has effective dates but no verified publication/known-at time; ETF datasets exist in the current mirror but current lists and observations do not prove a historical universe. The bridge will not derive historical membership from current membership, fill execution prices, or turn partial holdings/PCF rows into full exposure.

Next: implement the narrow bridge, run fixture and latest-fixed-release checks, then record exact remaining gates and a reviewable commit.
