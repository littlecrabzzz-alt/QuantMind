# Tushare index_daily exact batch 5 closed

- Node: cloud authority; Mac remains an immutable fixed-release reader.
- Gray rollout promoted from batch 4's conservative 240 calls to 360 after the prior four batches had 1320 HTTP 200 responses, zero 429, zero uncertain calls and 476.66 mean rpm, while the account and API gates were clear. Release, config, preparer, helper, eligible inventory and all task IDs were hash-pinned; plan-only made zero upstream calls or writes.
- Execute completed 360/360 HTTP 200 requests in 44.409 seconds: 335 done, 25 empty and 53687 retained rows across 360 `.CSI` index codes. Recomputed SHA256 passed for 360 objects, 360 observations and 335 Parquet files: 1055 unique references and 12238140 bytes.
- The batch did not publish or switch `CURRENT`. Worker and Beat were restored healthy. Free disk was 224854880256 bytes, leaving 117480697856 bytes above the 100 GiB reserve. Machine evidence: `docs/tushare-index-daily-batch5-20260911.evidence.json`.

Next: normal publish-only and Mac mirror must include and verify these 1055 references together with the other post-`5f796b` batches. Complete history, revisions, `known_at` and PIT remain open.
