# Tushare index_daily exact batch 8 at 300-request gray tier

- Before the next publication window, the authority was drained through the existing no-revoke workflow. The batch froze 300 pristine `index_daily` history jobs for 300 unique CSI codes covering request ranges from 2026-01-01 through 2026-09-01. Release, eligible inventory, task inventory, config, preparer and helper hashes were pinned; plan-only made zero authority, credential, upstream, write or publish access.
- Execute completed all 300 requests in 41.340 seconds: 266 done, 34 empty, 42624 retained rows, all HTTP 200 and zero uncertain calls. Recomputed SHA256 passed for 300 objects, 300 observations and 266 Parquet files: 866 unique references and 8868340 bytes.
- The rollout remains at 300 requests with the 90-second hard limit. Worker and Beat were restored healthy; free space remains 113975836672 bytes above the 100 GiB reserve.

The 866 references await a normal fixed release and Mac mirror. Complete index history, revisions, `known_at` and PIT remain open. Machine evidence: `docs/tushare-index-daily-batch8-20260911.evidence.json`.
