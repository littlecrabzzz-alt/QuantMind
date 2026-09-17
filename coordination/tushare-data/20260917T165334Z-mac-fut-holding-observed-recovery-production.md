# Mac fut_holding observed-fanout recovery production acceptance

- Time: 2026-09-17T16:53:34Z
- Archive owner: Mac
- Code commit: `8814d40dd1fe0f2c4c96956f0a5eb60761a66cdd`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and implementation

Four retained exact-day `fut_holding` parents from 2026-09-03, 2026-09-04, 2026-09-07 and 2026-09-08 each returned 4,000 rows with explicit `has_more=true`. They predated the production observed-futures fanout path and remained blocked even though their retained rows contained the legal `(exchange, symbol)` partition values required to continue without another discovery request.

The pipeline now recognizes retained legacy `fut_holding` and `fut_weekly_detail` objects as local `observed_futures_fanout` recovery work. It creates exact `trade_date + exchange + symbol` children from the retained supplier response and can continue acquisition in the same cycle. This preserves the original object and attempts and does not claim that the observed exchange/symbol universe is complete.

## Validation and production migration

- Related runtime tests: 52 passed: futures observed split 9, futures extra contracts 11, deferred split 15, pipeline 17.
- Python compilation, Ruff and `git diff --check`: passed.
- Candidate parents: 4.
- Retained rows: 16,000.
- Every raw object, observation and Parquet size/hash: verified unchanged.
- Original result-bearing jobs, attempts and tries: preserved; attempt rows remained 423,830 across the migration.
- Upstream calls during migration: 0.
- Created direct child edges: 541 (131, 137, 139 and 134 by parent date).
- Parent result: all four moved from blocked to split-pending; `fut_holding blocked=0`.
- Coverage remains unproven with gap `observed_exchange_symbol_universe_unverified`.
- `PRAGMA quick_check`: `ok`.
- Private migration receipt: `fut-holding-observed-recovery-v1.b60c2b75c2670f4587f56f8e95c0e708ea2c35c7836426e1657e6052f8096198.json`.

## Scoped real-request acceptance

At a natural worker boundary, a hash-pinned exact scope selected two pristine direct children from each recovered parent. Each task was verified as `pending`, `tries=0`, with no prior attempt and exactly the legal `trade_date + exchange + symbol` request shape.

- Real Tushare requests: 8.
- Result: 8 `sample_ok`, 8 done, 0 errors.
- Returned rows: 26, 34, 26, 31, 28, 33, 26 and 33.
- Attempt delta: exactly 8; each selected task now has one try and one attempt.
- Elapsed: 1.524 seconds under the configured tiered account/API rate gates.
- Publication: none; authority config and `CURRENT.json` hashes remained unchanged.
- Private acceptance receipt: `fut-holding-exact-acceptance-v1.fbcc4f6dfe6e1302578ff9913bbd1f90d6cee76c1dac1dfb9f355a8bb20f18b9.json`.

## Runtime and continuing acquisition

The LaunchAgent resumed after the scoped acceptance with PID 15970. The first complete post-restart production cycle ended at 2026-09-17T16:55:05.811910Z:

- Real Tushare requests: 360.
- Acquisition elapsed: 100.010 seconds.
- Failed stage: none.
- Queue: done 213,087; pending 2,821,715; blocked 1,192; quality 308; split-pending 5,745.
- Document processing: 240.
- Runtime/source hashes match: pipeline `2caa07270a4e309881c90b67637f0986723edef088f995e7aa9f1e0c56165897`; futures contract `d898a2efc2ac3eb24a9ebefc94bc837f6739b873844e719b047790e5cd9ea65b`.
- Worker stderr: empty at acceptance time.

## Dual-node boundary

After the implementation and evidence commit was pushed, dual-node Git alignment passed at `d7cdcf600312a4a2d8c88bbd553b69b5c089d03e` with source digest `a4225cce361f6869a49c47999d02b4fe1ff735ac94813e007e2a3f8bb4171e05`. The cloud research-cache timer is enabled and active, no cloud full-archive writer unit is loaded, and `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json` remains present. The cloud `quantmind` and `quantmind-db` containers are healthy.

Mac remains the only full Tushare archive writer. The cloud keeps the research cache only.

Full local historical synchronization remains active and incomplete.
