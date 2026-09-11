# Tushare fund price exact batch 15 at the 300-request gray tier

- After the standard no-revoke drain, the current fixed release, SSE calendar, authority config, preparer, runner and 300 pristine task identities were hash pinned. The manifest selects 150 dates per API from 2009-12-10 through 2011-01-18; four pristine tails from batch 14 enter normally, while its prior ReadTimeout task is tainted and excluded.
- Plan-only verified 300 jobs with zero authority, credential, upstream, write or publication access. Execution completed 150 `fund_daily` and 150 `fund_adj` requests in 65.917 seconds: 300 HTTP 200, 300 done, 27850 rows and zero uncertain calls.
- The closure independently verified 300 objects, 300 observations and 300 Parquet files: 900 unique references and 5424741 bytes, with no SHA256 error. It did not publish or switch CURRENT.
- Tushare Worker and Beat were restored healthy. Free disk is 221376466944 bytes, leaving 114002284544 bytes above the 100 GiB reserve. The regular exact cap remains 300 requests per 90-second window.

Machine evidence: `docs/tushare-fund-price-batch15-20260911.evidence.json`. The new references await normal fixed publication and Mac mirroring; lifecycle, revision, tradability, `known_at` and PIT gaps remain open.
