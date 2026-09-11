# Tushare index_daily exact batch 7 at 300-request gray tier

- Before the next publication window, the authority was drained through the existing no-revoke workflow. The batch froze 300 pristine `index_daily` history jobs for 300 unique CSI codes covering request ranges from 2026-01-01 through 2026-09-01. Release, eligible inventory, task inventory, config, preparer and helper hashes were pinned; plan-only made zero authority, credential, upstream, write or publish access.
- Execute completed all 300 requests in 40.970 seconds: 285 done, 15 empty, 45760 retained rows, all HTTP 200 and zero uncertain calls. Recomputed SHA256 passed for 300 objects, 300 observations and 285 Parquet files: 885 unique references and 10440580 bytes.
- Together with clean fund-share batch 12, this confirms the 300-request recovery tier on two regular interfaces. The rollout remains at 300 rather than returning to 360 in the same publication cycle. Worker and Beat are healthy; free space remains 114905575424 bytes above the 100 GiB reserve.

The 885 references await a normal fixed release and Mac mirror. Complete index history, revisions, `known_at` and PIT remain open. Machine evidence: `docs/tushare-index-daily-batch7-20260911.evidence.json`.
