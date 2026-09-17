# Mac announcement cadence and NPR filter production validation

- Time: 2026-09-17T17:53:21Z
- Archive owner: Mac
- Announcement commit: `c00c8dbb559f4d668defb4b5b9e4a4861b41bab9`
- Final NPR contract commit: `dbf604d90354e4ba029b3cb97cbe800ee38846f3`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Announcement generation cadence

Recent `anns_d` jobs previously used the configured hourly text epoch. The same exact calendar dates were therefore planned again every hour even though their source contract is date based. This produced repeated capped jobs without increasing historical coverage.

The text contract now marks `anns_d` with a daily recent epoch. The planner derives the Shanghai calendar day for this API while retaining the configured cadence for other text APIs. Existing raw snapshots and pre-change jobs remain immutable.

- Related tests: 33 passed: text contracts 8, announcement saturation 5, deferred split 15 and announcement batch 5.
- Python compilation, Ruff and `git diff --check`: passed.
- The production planning cycle at 2026-09-17T17:35:31Z used zero supplier requests and created the real daily queue: 196 planned references, 65 new jobs and 131 existing jobs.
- Current daily epoch `20260918`: six done jobs and one blocked exact-day 2,208-row cap.
- Pre-change hourly epochs `2026091800` and `2026091801` remain as retained evidence. No `2026091802` or later hourly `anns_d` epoch was generated after installation.
- The first post-install acquisition cycle made 350 real Tushare calls. Later cycles continued normal acquisition.

The zero-request planning cycle was production queue generation, not a dry run or rehearsal.

## NPR supplier-filter validation

The retained `npr` historical parent `5a62ec9faf1a73d352de51e6c397ff113a7749ef5d27b4660ba2b4985505fbbc` returned 500 rows with explicit `has_more=true`. Its response contained observed `ptype` values, and the documented supplier input accepts `ptype`, so a bounded production implementation first tested whether those values could legally close the capped window.

Commits `dedbda0460cbab658a26c126a55c0688a2963d39` and `b4b49c18` implemented and normalized that candidate path. Real supplier validation disproved it:

- 38 calls using documented and observed `ptype` shapes all returned explicit empty results.
- Tested shapes included exact-second, calendar-day and unbounded windows; leaf, returned group path, forward-slash path and group values; and organization plus leaf.
- One organization-only daily probe returned 500 rows with `has_more=true`, so organization partitioning also failed to close the capped window.
- The 39 supplier calls and their responses remain in the immutable attempt ledger.

The invalid implementation was fully reverted by `82c7d871` and `650c9307`. The final contract records the live gap and does not advertise an NPR saturation axis or legacy observed recovery.

## Production rollback and database integrity

- Invalid partition children found: 159.
- Uncalled open children retired as superseded: 150.
- Active NPR partition edges after rollback: 0.
- Active NPR partition split records after rollback: 0.
- The historical capped parent and the capped organization probe are both `blocked`.
- Capability `contract:npr:ptype_filter`: `supplier_filter_unusable`; coverage remains unproven.
- Attempts preserved at rollback: 432,257.
- `PRAGMA quick_check`: `ok` both during rollback and post-restart verification.
- Rollback made zero additional supplier calls.
- Private rollback receipt: `npr-ptype-filter-rollback-v1.f510cff3cf6f54db967a0b290e75b73eb7f2b7a85a2480c8145c95ba34c7fcb2.json`.

Post-revert validation passed 54 related tests: text contracts 8, deferred split 15, observed fanout 7, pipeline 17 and intake 7. Python compilation, Ruff and `git diff --check` also passed.

## Runtime and continuing acquisition

The reverted runtime was installed at a natural worker boundary. LaunchAgent `com.quantmind.tushare-archive` resumed with PID 35101 and an empty stderr log.

The first complete post-rollback production cycle ended at 2026-09-17T17:41:57.466713Z:

- Real Tushare requests: 391.
- Acquisition elapsed: 99.95 seconds.
- Failed stage: none.
- Queue: done 216,916; pending 2,852,991; blocked 1,175; quality 333; split-pending 5,898.
- Document processing: 240.
- Worker status: active and running.

## Dual-node boundary

Cloud Git was aligned to `dbf604d90354e4ba029b3cb97cbe800ee38846f3` for the runtime check. The cloud research-cache timer is enabled and active, no cloud full-archive writer container is running, and `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json` remains present. The cloud `quantmind` and `quantmind-db` containers are healthy.

Mac remains the only full Tushare archive writer. The cloud keeps the research cache only. Full local historical synchronization remains active and incomplete.
