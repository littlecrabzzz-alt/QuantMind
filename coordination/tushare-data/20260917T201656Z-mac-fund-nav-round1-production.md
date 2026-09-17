# Mac `fund_nav` empty review round-one production acceptance

- Time: 2026-09-17T20:16:56Z
- Archive owner: Mac
- Runtime commit: `c907737f1eeeaf263eab5973dc2c2e3413139d3f`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`
- Fixed release: `data-02a4b01dd61cf8b30c27efce1e57f79efcd46089eb074b7e1755103d2efd744b`

## Boundary and production result

The review covers 291 `fund_nav` history leaves whose first complete supplier response was empty. Each target was paired with a positive-control request from the fixed release. A valid empty pair records what Tushare returned at the two observation times; it does not mark the leaf or its parent historically complete and does not claim point-in-time completeness.

Two hash-pinned production batches executed after the archive worker stopped at a completed-cycle boundary:

- Manifest `65b7ad459362c9f860153dacb9fc4a75f4cab5b7f60dab16958423cf62d14fef`: 180 targets, task inventory `5da5e823d728c7005c834618f9425b4a63e6da4475af933e608a1e23555e0dc8`, 360 real upstream calls in 50.438 seconds, all 180 `round1_valid_empty`.
- Manifest `288e646e49aa45112d1ad6b4d1ddc7e4d0db866c14818b6a1c3708c6cd499d11`: 111 targets, task inventory `4fa7e50d89c93233913947cdb67dbaf6e196617eb4a0bb527ea3f3b4a7a7443e`, 222 real upstream calls in 31.495 seconds, all 111 `round1_valid_empty`.
- Combined: 291 distinct targets and 582 real Tushare calls. There were no recovered-data, conflict, inconclusive, or manual-hold outcomes.
- The pipeline contains exactly 291 distinct round-one review attempts. A new round-one preparation returns zero eligible targets.
- All 291 request/control observation hashes were rechecked against their immutable files. Completion times range from 2026-09-17T20:04:58.047521Z through 2026-09-17T20:08:18.383717Z.
- Round two is deliberately ineligible until seven days after each target's completion time. Its eligibility window begins 2026-09-24T20:04:58.047521Z and finishes 2026-09-24T20:08:18.383717Z.
- Private receipts: `validation/fund-nav-empty-round1-receipt.65b7ad459362c9f860153dacb9fc4a75f4cab5b7f60dab16958423cf62d14fef.json` and `validation/fund-nav-empty-round1-receipt.288e646e49aa45112d1ad6b4d1ddc7e4d0db866c14818b6a1c3708c6cd499d11.json`.

The preparation and `plan_only` runner modes are offline preflight and post-execution idempotency checks. They do not replace the two production executions above and do not consume upstream quota.

## Verification

- 2 archive installer tests passed.
- 5 preparation tests passed.
- 4 selected runner tests passed: offline plan, valid pair, recovered data, and round-two exhaustion.
- Python compilation and `git diff --check` passed.
- The full runner file still contains one time-sensitive fixture whose synthetic clock precedes the immutable observation captured during the test; it correctly rejects that fixture as not yet due. This is separate from the two production receipts and was not counted as a passing test.

## Worker continuity

LaunchAgent `com.quantmind.tushare-archive` resumed as PID 89214 and did not exit. One scheduled queue-planning cycle reported `planning_only` and zero requests; this is production queue generation, not a simulated acquisition. The following completed production cycle ended at 2026-09-17T20:16:56.654440Z:

- Real Tushare requests: 390.
- Cycle elapsed: 102.104 seconds.
- Completed stages: open, publication check, planning check, archive, acquire, document registration, close.
- Failed stage: none.
- Queue: done 230,072; empty 207,953; pending 2,878,932; blocked 874; permission-blocked 4,694; quality 497; resolved 4,181; split-pending 6,229.
- Documents processed: 207; document status `ok`.
- Worker stderr: empty.

The Mac remains the only full Tushare archive writer. The cloud node remains restricted to the research cache.
