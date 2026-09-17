# Mac Tushare retained normalization recovery production rollout

- Time: 2026-09-17T10:17:10Z
- Archive owner: Mac
- Code commit: `cbf91931` (`Recover retained normalization timeouts`)
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and production behavior

Three retained upstream responses were complete, successful, and accepted by their data contracts, but older cloud tasks timed out while converting the raw JSON rows to Parquet. The jobs therefore remained blocked even though their immutable observations and objects were intact:

- `daily_basic`: one `TimeoutError`
- `stk_limit`: one `TimeoutError`
- `stk_nineturn`: one `SoftTimeLimitExceeded`

The recovery verifies the retained object and observation hashes, reruns the current response assessment, and performs only local normalization. It does not call Tushare. The original attempt keeps its original normalization error and artifact references. The recovered job result receives a content-addressed Parquet artifact plus a `normalization_recovery` marker. A separate `normalization_recoveries` overlay makes the locally derived dataset part of every later immutable manifest without rewriting the attempt ledger.

## Production migration

- Dry-run candidates and recoverable jobs: 3
- Applied recoveries: 3
- Unchanged candidates: 0
- Upstream calls: 0
- Attempts before and after: 385,497
- Result-bearing jobs before and after: 382,163
- Recovery evidence rows: 3
- `normalization_recovered` capabilities: 3
- Every recovered Parquet size and SHA-256: verified
- Every source attempt retains its original normalization error: verified
- `PRAGMA quick_check`: `ok`
- Receipt: `normalization-recovery-v1.f38f19d153b7fe1aa62d7918fc396f13e340a939a34862add597ca13ef91caf2.json`
- Receipt filename hash: verified

The source and deployed recovery script both have SHA-256 `f0a65d3454cf7f2216200bf2b2aab6a44f662e9bdfb86a2e6fa9a436c330ef85`. The recorded normalizer source fingerprint is `9aebf1185bccfa32571dbd8e9a2610c2aed8baa29701ee1f7876da07888a6064`.

## Production publication

- Release: `data-85972a7c6a0b6c6c14496da44be578d6281e9fa48be38bb2a278af96b95fe4b2`
- Manifest identity: verified
- Publication upstream calls: 0
- Publication failed stage: none
- Normalization recovery datasets: 3, one for each API above
- Recovery markers preserving the source attempt and zero upstream calls: 3 of 3
- Blocked jobs with `sample_ok` assessments: 0
- Manifest `coverage.blocked`: 1,302, down from 1,305
- Existing contract reassessment datasets retained: 767
- Existing request-contract supersession capabilities retained: 14,745
- Existing supplier-empty reassessment capabilities retained: 105
- Manifest size: 404,521,818 bytes

The publisher held `.archive-worker.lock`, `pipeline.lock`, and `documents.lock`, wrote the immutable release, atomically updated `CURRENT.json`, and verified its hash. Publication took 180.219 seconds.

## Real acquisition after restore

LaunchAgent `com.quantmind.tushare-archive` resumed with PID 80322. An overdue planning-only cycle completed first in 169.510 seconds with no upstream request and no failed stage. The following complete production acquisition cycle reported:

- Status: `completed_cycle`
- Requests and first-cycle attempt rows: 194
- Attempt row boundary: 385,498 through 385,691
- `sample_ok`: 96
- `empty_unverified`: 95
- `possibly_truncated`: 3
- Transport, rate-limit, permission, API, and invalid-response errors: 0
- Acquisition failed stage: none
- Document processing: 211, status `ok`
- Elapsed: 101.293 seconds
- Pending after the cycle: 2,970,585
- Blocked after the cycle: 1,302
- Publication remained deferred and pinned to the verified release above

The worker continued into subsequent production cycles. QuantDB was not stopped or modified.

## Validation, retained gaps, and capacity

- Runtime environment: 46 related pipeline, publication, field-coverage, and recovery tests passed
- System Python: 44 passed; two reader tests could not import `duckdb`, which is installed in the deployed runtime
- Three focused migration tests plus six earlier reassessment tests passed separately
- Ruff, compileall, and `git diff --check`: passed
- The known pre-existing manifest serialization expectation mismatch remains unchanged.
- Local filesystem: about 3.6 TiB total, 1.3 TiB used, 2.3 TiB available
- Full historical synchronization remains active and incomplete.

The remaining dominant blocked groups still require evidence rather than local normalization: `dc_member` and `moneyflow_dc` lack proof of complete historical universes, `fina_mainbz_vip` has a terminal period/type request shape and observed row cap, and the remaining saturated interfaces need legal partition or pagination proofs before closure.
