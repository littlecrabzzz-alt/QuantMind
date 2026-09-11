# Tushare fund_share exact batch 12 at 300-request gray tier

- A read-only cooldown audit observed no new transport error, HTTP 429, rate-limited or uncertain attempts after the two cross-API ReadTimeouts, and a later `income_vip` attempt returned HTTP 200. Account and relevant API gates were ready. The ordinary active task was allowed to finish before a two-round stable drain.
- The batch froze 300 pristine `fund_share` history jobs, SH and SZ 150 each, spanning 2021-03-03 through 2021-07-31. Manifest, task inventory, config, preparer and helper were hash-pinned; plan-only made zero authority, credential, upstream, write or publish access.
- Execute completed all 300 requests in 61.851 seconds: 205 done, 95 empty, 53225 retained rows, all HTTP 200 and zero uncertain calls. Recomputed SHA256 passed for 300 objects, 300 observations and 205 Parquet files: 805 unique references and 5368151 bytes.
- This clean window validates the 300-request recovery tier, but it was slower than earlier fund-share batches. Keep the cap at 300 rather than raising it. Worker and Beat are healthy; free space remains 114963718144 bytes above the 100 GiB reserve.

The 805 references await a normal fixed release and Mac mirror. Complete share history, revisions, `known_at` and PIT remain open. Machine evidence: `docs/tushare-fund-share-batch12-20260911.evidence.json`.
