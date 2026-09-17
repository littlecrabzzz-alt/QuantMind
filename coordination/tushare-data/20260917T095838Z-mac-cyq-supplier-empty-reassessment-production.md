# Mac Tushare CYQ supplier-empty reassessment production rollout

- Time: 2026-09-17T09:58:38Z
- Archive owner: Mac
- Code commit: `f340370e` (`Reassess retained cyq chips empty responses`)
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and production behavior

The retained archive contained 105 blocked `cyq_chips` requests whose immutable raw payloads all carried the exact supplier response `code=50101`, `msg=指定数据不存在，请确认参数！`, and `data=null`. The current reviewed response rule classifies this exact shape as a supplier-confirmed empty response rather than a transport or API failure.

The migration verifies the observation and object hashes, replays the current rule locally, and changes only the current job result from blocked `api_error` to `empty` / `empty_unverified`. It keeps `coverage_proven=false`, `history_complete=false`, and `pit_verified=false`. The original attempt, raw response artifacts, and original `api_error` assessment remain unchanged and queryable. Each reassessed job receives `supplier_empty_reassessed` capability evidence with `upstream_calls=0`.

## Production migration

- Candidates verified: 105
- Reassessed jobs: 105
- Unchanged candidates: 0
- Upstream calls: 0
- Attempts before and after the transaction: 384,087
- Result-bearing jobs before and after: 380,753
- Source attempt action: unchanged
- Artifact action: verified unchanged
- `PRAGMA quick_check`: `ok`
- Receipt: `supplier-empty-reassessment-v1.c28c9813a8bde43a8dc09768ba2383710022ad63279bb185207e269d7319d07a.json`

The source and deployed migration script both have SHA-256 `c16845275c92972f06efe6209e09b03e5bf1908b711de0d26e63dfeb3d3c44ee`.

## Production publication

- Release: `data-dec7cd8adf3002483b3a801b8abd3abc023d0b9f621fd54b86022a83bd61251c`
- Manifest identity: verified
- Publication upstream calls: 0
- Publication failed stage: none
- `cyq_chips` blocked gaps: 0
- `cyq_chips` empty-unverified gaps: 279, including the 105 reassessed responses
- `supplier_empty_reassessed` capabilities: 105; every record keeps coverage unproven and records zero upstream calls
- Manifest `coverage.blocked`: 1,305, down from 1,410
- Existing contract reassessment datasets retained: 767
- Existing request-contract supersession capabilities retained: 14,745
- Manifest size: 403,065,570 bytes

The publisher held `.archive-worker.lock`, `pipeline.lock`, and `documents.lock`, wrote the immutable release, atomically updated `CURRENT.json`, and verified the release hash. Publication took 185.006 seconds.

## Real acquisition after restore

LaunchAgent `com.quantmind.tushare-archive` resumed with PID 73679. An immediately due planning-only cycle completed first with zero requests. The following complete production acquisition cycle reported:

- Status: `completed_cycle`
- Requests and preserved attempt rows: 275
- Attempt row boundary: 384,088 through 384,362
- `sample_ok`: 128
- `empty_unverified`: 141
- `possibly_truncated`: 6
- Transport, rate-limit, permission, API, and invalid-response errors: 0
- Acquisition failed stage: none
- Document processing: 240, status `ok`
- Elapsed: 100.744 seconds
- Pending after the cycle: 2,968,667
- Blocked after the cycle: 1,305
- Publication remained deferred and pinned to the verified release above

The worker continued into subsequent production cycles. QuantDB was not stopped or modified.

## Validation, retained gaps, and capacity

- Targeted tests: 22 passed, 1 DuckDB-dependent test deselected, and 25 subtests passed
- Ruff, compileall, and `git diff --check`: passed
- The broader system-Python run still cannot execute one DuckDB-dependent test because that interpreter lacks `duckdb`.
- The known pre-existing manifest serialization expectation mismatch remains unchanged.
- Local filesystem: about 3.6 TiB total, 1.3 TiB used, 2.3 TiB available
- Full historical synchronization remains active and incomplete.

The rollout deliberately retains evidence-backed gaps that this response rule cannot close: `dc_member` and `moneyflow_dc` still lack proof of complete historical universes, while `fina_mainbz_vip` remains bounded by its documented terminal period/type request shape and observed row cap. They were not silently marked complete.
