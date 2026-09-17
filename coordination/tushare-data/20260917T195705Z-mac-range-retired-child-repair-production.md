# Mac range replacement retired-child repair production acceptance

- Time: 2026-09-17T19:57:05Z
- Archive owner: Mac
- Code commit: `c38e888fb3d3c1497fcc5b4ef3d776bff6a6eb14`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Problem and reviewed proof

One blocked `dc_member` parent for `trade_date=20260908` still referenced 1,043 children after the stock-range queue migration. Every child was already `superseded`; the parent retained its saturated 8,000-row result and one attempt but reconciliation could only report `parent_not_split_pending`.

The existing history range plan has exactly 5,914 unique `con_code` roots spanning that date under the same request contract. At the production boundary, 37 were `done`, 12 `empty`, and 5,865 `pending`. The repair accepts a parent only when every remaining child is superseded, the reviewed replacement count and identifiers are exact, the range contracts match, and the replacements are independent roots.

## Validation and production transaction

- 17 focused and adjacent tests passed: range replacement and partition closure.
- Ruff, Python compilation, and `git diff --check` passed.
- Dry-run: exactly 763 replacement parents, 1,043 retired child edges, 5,914 replacement jobs/codes, zero upstream calls.
- Apply: restored one missing `replaced_by_stock_range_plan_v1` marker and removed 1,043 stale edges.
- Preserved 763 parent results and 763 attempts; the original parent result, `tries=1`, observation/object references, and Parquet reference were unchanged.
- Child jobs remain `superseded`; only obsolete relationship edges were removed.
- Second identical run: `no_action`, with the 1,043 retired-edge count recovered from durable evidence.
- `coverage_proven=0` remains unchanged; the 5,865 pending replacement jobs are not reported as complete.
- Active `parent_not_split_pending`: 0.
- Active zero-child `split_pending`: 0.
- Private receipt: `validation/range-retired-child-repair-v1.d64d47db75861d631a3733eda373d60e2117e929ec74af2cd955e280186b3773.json`.

## Runtime and real acquisition acceptance

The archive worker drained after a completed cycle, the installed helper hash matched the repository, and LaunchAgent `com.quantmind.tushare-archive` resumed as PID 85287.

The first complete post-restart production cycle ended at 2026-09-17T19:57:05.099558Z:

- Real Tushare requests: 259.
- Cycle elapsed: 108.385 seconds.
- Failed stage: none.
- Queue: done 228,446; empty 206,884; pending 2,873,239; blocked 874; permission-blocked 4,694; quality 481; resolved 4,164; split-pending 6,163.
- Documents processed: 235; document status `ok`.
- Worker stderr: empty.

The Mac remains the only full Tushare archive writer. The cloud node remains restricted to the research cache.
