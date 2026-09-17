# Mac opt_basic supplier-terminal production acceptance

- Time: 2026-09-17T17:05:51Z
- Archive owner: Mac
- Contract commit: `877dca9ce3fd0eca5962daa65c82435c9f667d46`
- Reassessment commit: `31b33f9640baff7d4e35d7755dd12c53f190b42d`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and implementation

The official `opt_basic` page documents the `ts_code`, `exchange`, `list_date`, `opt_code` and `call_put` filters but no numerical response cap or pagination parameters. The local 6,000-row threshold is therefore an operational saturation alarm rather than a supplier maximum. Live responses include an explicit `data.has_more` continuation flag.

The contract now accepts `has_more=false` over the unverified local alarm only after the normal missing-field, disallowed-null and positive-value checks pass. `has_more=true` remains `possibly_truncated` and continues through the reviewed exchange, call/put and observed standard-contract partitions.

The retained-contract reassessment utility now also supports an explicit API-filtered scan of blocked `possibly_truncated` responses. It verifies raw-object, observation and Parquet hashes, recomputes the result under the current contract, preserves the source attempt ledger and promotes only a current `sample_ok` result.

## Validation and production reassessment

- Related runtime tests: 29 passed: contract reassessment 4, other contracts 7, other pipeline 11, intake 7.
- Python compilation, Ruff and `git diff --check`: passed.
- Candidate retained `opt_basic` jobs: 10 blocked jobs.
- Supplier-terminal promotions: 2, both explicit `has_more=false`.
- Promoted snapshots: SZSE 8,046 rows; CFFEX 10,248 rows.
- Remaining candidates: 8 explicit `has_more=true`; unchanged as `possibly_truncated` for further legal partitioning.
- Every candidate raw object, observation and Parquet size/hash: verified unchanged.
- Original attempts and tries: preserved; attempt rows remained 426,639 across the transaction.
- Upstream calls during reassessment: 0.
- `PRAGMA quick_check`: `ok`.
- Private receipt: `contract-reassessment-v1.c3480b19faa776f5117aebfce3aa7add5b062da60b20f54c47f8731a518acd5c.json`.

After reassessment, `opt_basic` states included done 686, empty 2,441, pending 18,149, quality 1, split-pending 64, superseded 4,301 and blocked 8. Every remaining blocked result has supplier `has_more=true`.

## Runtime and continuing acquisition

The worker drained at a natural cycle boundary, the installed runtime was refreshed, the offline transaction completed, and LaunchAgent `com.quantmind.tushare-archive` resumed with PID 20761.

The first complete post-restart production cycle ended at 2026-09-17T17:07:18.215010Z:

- Real Tushare requests: 342.
- Acquisition elapsed: 100.406 seconds.
- Failed stage: none.
- Queue: done 214,130; pending 2,826,912; blocked 1,185; quality 311; split-pending 5,774.
- Document processing: 240.
- The same cycle also recovered one retained `has_more=true` SHFE parent into two call/put children with zero additional discovery calls, then continued normal acquisition.
- Runtime/source hashes match: other contract `53c67e7c2a4f156ee50d3f09eba6aa6d5de2af00da02df68b4cd2acd3ba64e87`; reassessment utility `dd998287e27a392e12da9de2fedf88daf17edd6811490882d2c00ef8ddd42147`.
- Worker stderr: empty.

## Dual-node boundary

After the implementation and evidence commit was pushed, dual-node Git alignment passed at `a6e1f766fd2f2f92220c3e7183ee6545f51051b5` with source digest `db11e835a55dd5fd64ca339d9acbd8b896ff091ac494acec92c29af4f249c8dc`. The cloud research-cache timer is enabled and active, no cloud full-archive writer unit is loaded, and `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json` remains present. The cloud `quantmind` and `quantmind-db` containers are healthy.

Mac remains the only full Tushare archive writer. The cloud keeps the research cache only.

Full local historical synchronization remains active and incomplete.
