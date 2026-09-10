# Tushare continuation start

- owner: mac root
- status: active
- branch: `master`
- starting head: `9f4b05f63ba49fb66d633fb0164b17a5070d4aee`
- source digest: `89d303bf5e84b192ab230fa50749faaa560b3908788af4b6fbdc6fc8d9ccc908`
- cloud data authority: `/root/data/disk/quantmind/project/data/tushare`
- Mac mirror: read-only, one-way from cloud fixed releases

## Current fixed point

- Cloud and Mac `CURRENT.json`: `data-6c9f0b0b777f5edfbb3654809006b01ea22770dd23fce20839be1a9be0d20ab1`.
- Dedicated acquisition and document workers are healthy.
- Cloud available bytes at start: `158752280576`; stop threshold remains `107374182400`.
- Unrelated RRG/research working-tree edits are outside this task and must remain untouched.

## Parallel continuation lanes

1. Audit the remaining catalog/runtime boundary and select the next useful read-only Tushare data batch.
2. Recompute current RRG blockers and identify the next bounded acquisition action from authority state.
3. Reassess document backlog, failure states and worker timing without long live-database read transactions.
4. Root coordinates the production queue, performs only bounded existing-entrypoint actions, records non-blocking gaps and publishes/mirrors accepted data.

No credential or token may be written to Git, logs, reports or coordination records.

## 16:48 CST checkpoint

- `master` and GitHub advanced to `892cd8fdd8685c1942ab5d2a43f14819ba6b5b43`; Mac/cloud handoff passed with 6,013 source files and digest `0fa2fbdbf202e4832788dc93d2f4c66aa63750c0d777e90c254f1eb10a826856`.
- Publication now coordinates with the document worker through the existing nonblocking lock. A due tick deferred without changing `CURRENT` while documents were active; non-publication acquisition and document tasks continue to overlap.
- The old 160 second Celery envelope remained too close to the measured 155 second publication stage. The dedicated acquisition task now uses a 300 second soft and 330 second hard envelope while its configured upstream request and run budgets remain unchanged. The cloud worker is healthy and has loaded these exact values.
- A recovered automatic publication produced `data-ce636524ac1e6a46a571b32ae9b99a44cef28f0616b7530edb47477d682d9763`; the standard Mac mirror verified all 580,006 files and atomically switched to the same release with zero downloaded files.
- RRG fixed-release audit now resolves the `FUND:<source_ts_code>` namespace and derives `fund_div` empty receipts from the immutable manifest. The pinned `data-d42bf11...` audit observes 107,293 target `etf_limit` code-days and 1,648 monthly execution points; `fund_div` still lacks terminal evidence for 1,386 of 1,718 ETF codes, so `blocked_data` remains.
- Catalog closure remains 249 named / 243 runtime / 6 nonruntime. No registered public reader is missing; `ggt_monthly` remains contract-blocked, private portfolio reads require an owner-bound namespace, writes stay excluded, and `pro_bar` remains an SDK-derived compatibility layer.
- Next production evidence: one automatic fixed publication under the new 300 second soft limit, no new document database lock failure in that acceptance window, then another exact 360-call RRG batch when the shared acquisition lock is available.
