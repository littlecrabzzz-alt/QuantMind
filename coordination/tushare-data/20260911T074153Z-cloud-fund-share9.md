# Tushare fund_share exact batch 9 closed

- Node: cloud authority; Mac remains an immutable fixed-release reader.
- The batch froze 360 pristine history leaves, balanced across SH and SZ at 180 each, spanning 2022-07-27 through 2023-01-22. Manifest, task inventory, config, preparer and helper were hash-pinned; plan-only made zero upstream calls or writes.
- Execute completed 360/360 HTTP 200 requests in 46.203 seconds: 246 done, 114 empty and 98699 retained rows. Recomputed SHA256 passed for 360 objects, 360 observations and 246 Parquet files: 966 unique references and 9308267 bytes.
- No uncertain calls occurred, and the batch did not publish or switch `CURRENT`. Worker and Beat were restored healthy. Free disk was 224830201856 bytes, leaving 117456019456 bytes above the 100 GiB reserve. Machine evidence: `docs/tushare-fund-share-batch9-20260911.evidence.json`.

Next: let the normal publisher include this batch with the other post-`5f796b` work, mirror to Mac, and verify exact membership, sizes, hashes and offline reads. Complete share history, revisions, `known_at` and PIT remain open.
