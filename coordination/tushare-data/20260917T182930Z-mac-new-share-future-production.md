# Mac new_share open-future discovery production acceptance

- Time: 2026-09-17T18:29:30Z
- Archive owner: Mac
- Code commit: `58a7cc5c`
- Archive root: `~/Library/Application Support/QuantMind/tushare`

## Problem and implementation

The official `new_share` contract allows optional `start_date` and `end_date`, limits one response to 2,000 rows, and states that total retrieval is unlimited. The local planner previously emitted one unfiltered discovery request per recent epoch. Every retained unfiltered request returned exactly 2,000 rows with `has_more=true`, so the request could not prove completeness and accumulated repeated blockers.

The planner now emits a legal lower-bounded request with only `start_date=today`. This asks for all supplier-known online issuance dates from today forward without inventing a future cutoff. Existing bounded date ranges continue to cover the past. A start-only response at cap remains blocked because there is no legal upper date boundary, code filter or pagination parameter to partition it safely.

- Related tests: 54 passed: listing-extra contracts and runtime, deferred split, pipeline and intake.
- Python compilation, Ruff and `git diff --check`: passed.
- The installed source hash matched the repository after a natural-boundary runtime upgrade.
- Installed planner output for 2026-09-18 contains `{"start_date":"20260918"}` plus the bounded recent range `20260912..20260918`; it contains no unfiltered `new_share` job.

## Retained snapshot audit

Seven prior unfiltered blocked snapshots contained 14,000 retained rows and 2,004 distinct natural keys. Each snapshot was at the 2,000-row cap; their combined issuance dates ranged from 2020-04-08 through 2026-09-24.

The bounded historical jobs provided 450 explicit terminal responses whose merged date coverage is continuous from 1990-01-01 through 2026-09-17. The new lower-bounded request covers 2026-09-18 forward, so the two scopes meet without a date gap.

The new production task `defae214db7f0a4dd2c2d99d62feebff47dd8e901c9815ab7ffd27f8e69bf915` was promoted only within the queue, from priority 20 to 1. Its state, tries, result, credentials and rate gates were unchanged by prioritization. The worker then made one real supplier attempt:

- Request: `new_share(start_date=20260918)`.
- Result: `sample_ok`, three rows, `has_more=false`, state `done`.
- Both natural keys dated 2026-09-18 or later from the seven old snapshots are present in the new response.
- The response also discovered one additional future natural key dated 2026-09-28.
- Priority receipt: `new-share-future-priority-v1.a9ad7eabdeb453cb443e3bbc7e369c27758d7fc1821880d04380b86323449a74.json`.

## Legacy retirement and integrity

After the combined date coverage proof:

- The seven result-bearing unfiltered blockers moved to `superseded`.
- Their original attempts, tries, raw objects, observations and Parquet remained retained.
- Twenty-four referenced artifact hashes were recomputed successfully.
- The retirement transaction made zero upstream calls and preserved 436,329 attempt rows.
- `PRAGMA quick_check`: `ok`.
- Capability `planning:listing_extra:new_share:legacy_unfiltered` records `replaced_by_legal_future_lower_bound`.
- Result-bearing retirement receipt: `new-share-legacy-retirement-v1.ce7c916c65cdc9eb30630a33c2e0017e43859b8b3770fd0824659acc69a36e73.json`.

One uncalled unfiltered job for epoch `20260918` had been planned by the old runtime before the upgrade. It remained pristine at `pending`, `tries=0`, with no result or attempt. It was also moved to `superseded` without an upstream call. Its receipt is `new-share-open-retirement-v1.69d23a861876ed85831b09092d2eafbd64bd37b0b98ee66943fea96d8f067b7d.json`.

Final `new_share` state has zero blocked jobs, zero pending unfiltered jobs and eight superseded unfiltered jobs retained as evidence.

## Continuing acquisition

Lock-protected queue and retirement transactions caused overlapping worker ticks to return `already_running`, as designed, instead of writing concurrently. After both locks released, the next production cycle completed at 2026-09-17T18:29:22.851577Z:

- Real Tushare requests: 315.
- Cycle elapsed: 100.746 seconds.
- Queue: done 219,410; pending 2,863,716; blocked 1,170; quality 353; split-pending 5,934.
- Worker PID: 42743; active/running; stderr size 0.

Mac remains the only full Tushare archive writer. Full local historical synchronization remains active and incomplete.
