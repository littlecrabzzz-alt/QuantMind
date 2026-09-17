# Mac Tushare invalid-request retirement production rollout

- Time: 2026-09-17T09:41:33Z
- Archive owner: Mac
- Code commits: `c2698df5`, `e2ee116e`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and production behavior

Older planners had created request shapes that the current reviewed contract rejects:

- `idx_factor_pro`, `fund_factor_pro`, and `cb_factor_pro`: bare `start_date/end_date` without `ts_code` or exact `trade_date`
- `fut_index_daily`: exact `trade_date` without a `.NH` `ts_code`

The corrected planners already create all-market exact-day factor requests and code-bound futures-index ranges. The migration retires an old blocked request only after proving that usable corrected jobs with the same requested fields and row cap cover every old calendar day. Futures coverage additionally requires every one of the 56 codes published in the reviewed official code table. Pending corrected jobs count as retained queue coverage; their data result is not claimed complete before acquisition.

The migration preserves source jobs, results, attempts, replacement jobs, and partition graphs. It changes the old job state to `superseded` and records `request_contract_superseded` capability evidence with `coverage_proven=true` and `upstream_calls=0`.

## Production migration

Initial history transaction:

- Candidates and superseded jobs: 14,717
- `fut_index_daily`: 13,394
- Each factor Pro API: 441
- Factor calendar-day coverage units: 40,179
- Futures code-day coverage units: 750,064
- Factor replacement jobs used: 40,179
- Futures replacement jobs available: 2,128
- Related attempts preserved: 3,477
- Missing coverage units: 0
- Active split-parent children: 0
- Receipt: `invalid-request-retirement-v1.b1c784866b5a5ffa6b2d684a086f2e3446d176bd87f505ff5a3a4990f7fc1129.json`

The first publication exposed 28 safely retained `fut_index_daily` requests in recent epochs `20260909` through `20260912`. Commit `e2ee116e` extended candidate selection to all blocked epochs while requiring replacements from the candidate epochs plus stable `history`. The follow-up transaction verified 1,568 further futures code-day units, retired all 28, preserved 137 related attempts, and wrote `invalid-request-retirement-v1.f9176baa202f072753e758f9aa2d96db00fa578c7bc921221e7bd15f1778f4f5.json`.

Final database checks:

- Total retired requests: 14,745
- Retirement evidence: 14,745, all coverage-proven
- Target API blocked requests remaining: 0
- Attempts before and after the second transaction: 382,852
- Result-bearing jobs before and after: 379,518
- `PRAGMA quick_check`: `ok` after each production transaction
- Migration upstream calls: 0

## Final publication

- Release: `data-22d291c18ed2f275f3273e49d349c70b5f8b9f941bc13ae45816ad807756aa3b`
- Manifest identity: verified
- Target API blocked gaps: 0
- Retirement capabilities: 14,745
  - `fut_index_daily`: 13,422
  - `idx_factor_pro`: 441
  - `fund_factor_pro`: 441
  - `cb_factor_pro`: 441
- Manifest `coverage.blocked`: 1,410, representing other preserved gaps
- Manifest `coverage.superseded`: 5,372,041
- Existing contract reassessment markers retained: 767
- Publication failed stage: none
- Publication upstream calls: 0

The final publication held `.archive-worker.lock`, `pipeline.lock`, and `documents.lock`, wrote an immutable release, atomically changed `CURRENT.json`, and verified the manifest checksum.

## Real acquisition after restore

LaunchAgent `com.quantmind.tushare-archive` resumed with PID 67705. The first complete real acquisition cycle reported:

- Status: `completed_cycle`
- Requests: 211
- Preserved attempt rows: 234
- `sample_ok`: 113
- `empty_unverified`: 113
- `possibly_truncated`: 7
- `schema_gap`: 1 (`cctv_news`, one null `content`, retained as a real quality gap)
- Transport, rate-limit, permission, API, invalid-response, and invalid-value errors: 0
- Acquisition failed stage: none
- Document processing: 240, status `ok`
- Elapsed: 102.894 seconds
- Pending after the cycle: 2,966,412
- Blocked after the cycle: 1,410

The worker continued into subsequent production cycles. QuantDB was not stopped or modified.

## Validation and capacity

- New retirement and related migration/contract tests: 35 passed, 34 subtests passed
- Ruff, compileall, and `git diff --check`: passed
- A broader run had 56 passing tests plus two environment failures because the system Python lacks `duckdb`.
- The known pre-existing manifest serialization expectation also remains failing and was reproduced before this change.
- Local filesystem: about 3.6 TiB total, 1.3 TiB used, 2.3 TiB available
- Full historical synchronization remains active and incomplete.
