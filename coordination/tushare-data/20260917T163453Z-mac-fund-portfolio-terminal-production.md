# Mac fund_portfolio supplier-terminal production acceptance

- Time: 2026-09-17T16:34:53Z
- Archive owner: Mac
- Code commit: `69486d535bddf81b386f2106a5f3e7fc94bb9957`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and implementation

The retained archive had 13 exact `ts_code + period` `fund_portfolio` responses blocked only because they reached the inherited local 2,000-row alarm. The supplier returned explicit `has_more=false` for all 13 responses. The official interface documents the required exact-fund/report-period request shape and no pagination or supplier maximum; the local 2,000 threshold remains an unverified operational alarm.

The contract now accepts explicit supplier-terminal evidence for `fund_portfolio` only after normal missing-field, disallowed-null and positive-value checks pass. `has_more=true` remains `possibly_truncated`. This does not convert unresolved history or PIT coverage into a completeness claim.

## Validation and production reassessment

- Related runtime tests: 38 passed: RRG contracts 6, intake 7, fund-portfolio batching 9, RRG PIT bridge 10, extended store 6.
- Python compilation, Ruff and `git diff --check`: passed.
- Candidate jobs: 13.
- Retained rows: 26,173.
- Every raw object, observation and Parquet size/hash: verified unchanged.
- Duplicate contract keys `(ts_code, ann_date, end_date, symbol)`: 0.
- Original attempts and tries: preserved; attempt rows remained 422,588 across the transaction.
- Upstream calls during reassessment: 0.
- `PRAGMA quick_check`: `ok`.
- Result: all 13 jobs moved from blocked to done with `supplier_terminal_evidence=has_more_false_over_unverified_local_alarm`; `fund_portfolio blocked=0`.
- Private receipt: `fund-portfolio-terminal-reassessment-v1.3d6a9c2ddede70422aa043abbe308663d4f8cf3d138182cfbd020f0bf2ea3ba5.json`.

The nine separate `fund_portfolio` quality jobs were not changed and remain explicit quality gaps.

## Runtime and real acquisition acceptance

The worker drained at a natural cycle boundary, the installed runtime was refreshed, the offline transaction completed, and LaunchAgent `com.quantmind.tushare-archive` resumed with PID 9019.

The first complete post-restart production cycle ended at 2026-09-17T16:34:02.293585Z:

- Real Tushare requests: 339.
- Acquisition elapsed: 100.030 seconds.
- Failed stage: none.
- Queue: done 212,107; pending 2,814,985; blocked 1,203; quality 297; split-pending 5,721.
- Document processing: 240.
- Planner: deferred because the 900-second production planning interval was not due; this was a real acquisition cycle, not a rehearsal.
- Worker stderr: empty.
- Runtime/source hashes match: RRG contract `1c1bc718735b47dc6f278e941e6b0618d172e6c65de2415f45f2c1ebb64894d3`; intake `8830bbfbba121a2bcd4498de1b2ae45130e399124a02a9ab71abcc1dd45a8ee8`.

## Dual-node boundary

Mac, origin and cloud code were aligned to the implementation commit before this record. Dual-node verification passed with source digest `c5e133ae73356e5183bb9476f8707457b3539e2ccd86edadaa2bb5279e699d8d`. The cloud research-cache timer remains enabled and active, no cloud full-writer unit is loaded, and the relocation marker remains at `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json`.

The Mac filesystem has about 2.3 TiB free. Full local historical synchronization remains active and incomplete.
