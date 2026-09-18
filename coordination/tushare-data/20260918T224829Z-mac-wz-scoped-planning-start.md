# Tushare WZ scoped planning correction started

- Owner: Mac archive node
- Scope: remove redundant unfiltered `wz_index` / `gz_index` discovery jobs when an explicit history start is configured.
- Migration: retire only a blocked unfiltered parent after hash-verified, terminal date-range coverage proves the configured interval; preserve supplier results and attempts.
- Network: migration makes zero upstream calls.
- Safety: implementation is isolated in a worktree; the production archive worker remains active during development and testing.
