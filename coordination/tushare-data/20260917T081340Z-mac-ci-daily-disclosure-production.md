# Tushare CITIC index disclosure handling deployed

- UTC evidence time: 2026-09-17T08:13:40Z
- Code commit: `fbe8d225eb2d7a410ec54eef90fcd0128ae0e745`
- Archive owner: Mac, `/Users/lizeyu/Library/Application Support/QuantMind/tushare`

## Provider contract and preserved evidence

The official `ci_daily` page states that CITIC no longer discloses the open,
high, low, volume, and amount fields. Live historical responses also contain
periods where `pre_close`, `change`, and `pct_change` are null while `close`,
`ts_code`, and `trade_date` remain available.

Official source: <https://tushare.pro/document/2?doc_id=308>

The capture assessment now treats every `ci_daily` market-value field except
`close` as nullable and checks positivity only for `close`. The requested field
list remains unchanged, nulls remain in the raw and normalized observation, and
the assessment continues to require `ts_code`, `trade_date`, and `close`.

Current contract assessment is applied at capture time. Existing queued job
JSON, logical keys, and historical attempts are not rewritten, so the fix does
not create duplicate queue identities or erase the original quality evidence.

## Production acceptance

Acceptance replayed one existing formal history task through the normal HTTP,
raw-object, normalization, attempt, and state-transition path:

- job: `db3382632a2f48b9b8590be54ab11f375ae986de0109941015082e3e6a10c218`
- API and range: `ci_daily`, `CI005030.CI`, `20190101..20191231`
- task identity: unchanged
- attempts: 1 -> 2, preserving the first `schema_gap` result
- second result: `done/sample_ok`, 244 rows
- positive validation: `close` has zero invalid values
- retained nulls: `open/high/low` each have 221 nulls; `vol/amount` each have
  222 nulls; `pre_close/change/pct_change` each have 222 nulls

After deployment, the first ordinary acquisition cycle made 372 real requests
in 100.026 seconds at the configured 500 RPM account ceiling. The cycle
completed every stage with `failed_stage=null`, left 2,946,079 pending jobs,
and reported about 2.565 TB free.

From the production-acceptance watermark through the evidence query, 573 newer
attempts were durable: 263 `sample_ok`, 300 `empty_unverified`, 9
`possibly_truncated`, and 1 `schema_gap`. There were no `rate_limited`,
`transport_error`, `api_error`, or `invalid_response` results. The one schema
gap is a real `cctv_news` response with one null `content` field; it remains
visible rather than being filled or suppressed.

Full historical completeness remains open. The Mac worker continues the local
archive backfill, and QuantDB was not stopped or reconfigured during deployment.

## Verification and dual-node boundary

- RRG contract tests: 5 passed.
- Field-coverage tests: 11 passed.
- Intake tests: 7 passed.
- Core pipeline tests: 17 passed.
- Compile and `git diff --check` passed for the changed paths.
- Runtime/source SHA-256 matched for `tushare_intake.py` and
  `tushare_rrg_contracts.py` before activation.
- `scripts/dual-node.sh handoff --align-git mac` passed at `fbe8d225`.
- Cloud Git metadata matched `fbe8d225`,
  `tushare-research-cache.timer` was active, and no cloud full-archive worker
  process or unit was present.

The cloud continues to receive only the bounded research cache. Full Tushare
acquisition, its credentials, and the complete archive remain Mac-owned.
