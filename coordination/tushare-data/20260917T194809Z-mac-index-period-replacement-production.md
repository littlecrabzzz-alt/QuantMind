# Mac `index_weekly` legacy period replacement production acceptance

- Time: 2026-09-17T19:48:09Z
- Archive owner: Mac
- Implementation commits: `5da6e0de24d53a593072681ac400fdfeb358e490`, `1e00999faed3e18dd65327218b37496b097a9d2d`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and boundary

One migrated `index_weekly` parent for `trade_date=20260903` remained `split_pending` with `legacy_relationship_unverified`. Its retained result reported a 1,000-row saturated response and an old 9,643-member fanout, but the v3 migration correctly refused to invent missing parent-child edges. It had zero durable children, so it could never close through reconciliation.

The current `stable_decade_partitions_v5` planner independently created 9,673 exact `ts_code` roots in epoch `period-20260906`, each spanning 2026-09-03 under the same request contract. The maintenance helper requires the exact legacy job shape, zero-child marker, matching contract, unique identifiers, reviewed replacement count, usable states, and independent-root relationship. It performs no upstream calls and keeps `coverage_proven=false`; the replacement queue remains responsible for acquiring the data.

## Tests and production transaction

- 18 related offline tests passed: the new helper, existing stock-range replacement, and partition closure suites.
- 2 archive installer tests passed; the helper is included in the installed native runtime.
- Python compilation and `git diff --check` passed.
- Dry-run: `planned_rollback`, 9,673 replacement jobs and 9,673 unique codes, zero upstream calls.
- Apply: 1,022 replacements were `done`, 1,106 `empty`, and 7,545 `pending` at the transaction boundary.
- Changed only the legacy parent state from `split_pending` to `blocked` and its split marker to `replaced_by_index_period_plan_v1`.
- Preserved the original result, `tries=1`, one attempt, raw observation/object references, and Parquet reference.
- The split remains `coverage_proven=0`; the receipt reports `replacement_data_complete=false`.
- No `split_pending` parent now remains with `legacy_relationship_unverified`.
- Private receipt: `index-period-replacement-v1.08db38e1758f1187c31af747666d5b819e6ad37d5cff739ad7239192f0a096da.json`.

## Runtime and real acquisition acceptance

The archive worker drained at a completed-cycle boundary, the runtime was refreshed, the offline dry-run and apply completed, and LaunchAgent `com.quantmind.tushare-archive` resumed as PID 81591. Source/runtime hashes match for both the pipeline and maintenance helper.

The first complete post-restart production cycle ended at 2026-09-17T19:48:09.961308Z:

- Real Tushare requests: 402.
- Cycle elapsed: 100.629 seconds.
- Completed stages: open, publication check, planning check, archive, acquire, document registration, close.
- Failed stage: none.
- Queue: done 227,384; empty 206,258; pending 2,874,911; blocked 874; permission-blocked 4,694; quality 456; resolved 4,156; split-pending 6,130.
- Documents processed: 240; document status `ok`.
- Worker stderr: empty.

This was a real production acquisition cycle. The earlier `planning_only` event was a one-time configuration validation and is not the worker's current operating mode.

## Authority boundary

The Mac remains the only full Tushare archive writer. The cloud node remains restricted to the research cache and must not acquire or retain the full archive.
