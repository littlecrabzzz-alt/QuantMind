# Tushare index_daily 10 and fund_share 15 closures

- `index_daily` batch 10: 360 HTTP 200 calls in 44.385 seconds; 355 done, 5 empty, 77,598 rows. Independent audit verified 1,075 physical references and 17,723,680 bytes by SHA256. Task and upstream-request overlap with batches 1, 2 and 4 through 9 was zero.
- `fund_share` batch 15: 360 HTTP 200 calls in 44.875 seconds; 253 done, 107 empty, 65,479 rows and zero uncertain calls. Independent audit verified 973 physical references and 6,563,496 bytes by SHA256. Task and request overlap with batches 1 through 7 and 9 through 14 was zero.
- Both exact executions used the a447 fixed release evidence, stayed within their 90-second hard windows, and did not publish or switch CURRENT.
- Worker and Beat were restored with exact container starts and remained healthy with restart count 0 and OOM false.

These batches add retained history only. They do not prove complete history, revisions, intraday `known_at`, PIT semantics, RRG industry classification, fixed-release inclusion or Mac availability. Machine evidence: `docs/tushare-index-daily-batch10-20260912.evidence.json` and `docs/tushare-fund-share-batch15-20260912.evidence.json`.
