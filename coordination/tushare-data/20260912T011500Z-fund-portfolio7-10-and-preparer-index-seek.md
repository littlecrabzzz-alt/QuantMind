# Tushare fund_portfolio batches 7-10 and preparer seek

- Owner: Mac integration on `master`; cloud authority `/root/data/disk/quantmind/project`.
- Code: `cee03761` replaces the preparer full jobs JSON scan with per-epoch API seeks through the existing `jobs_partition_lookup` index. Mac and production-container tests are 9/9; no schema or new index was added.
- Production timing: the old read-only prepare was still running after 194 seconds with no manifest and was terminated; fixed prepares took 20, 10, 11 and 9 seconds.
- Exact execution: four 240-call `fund_portfolio` batches completed in 62.333, 64.586, 69.555 and 66.968 seconds. Totals are 960 HTTP 200, 734 done, 225 empty, one conservative saturation block, 68,680 rows, zero uncertain calls.
- Physical closure: 2,655 unique object/observation/Parquet references, 13,907,170 bytes, all SHA256 verified; task and request-signature overlap across consecutive batches is zero.
- Services: Tushare worker and Beat were drained without revoke, restored healthy with restart 0 and no OOM. Exact work did not publish or switch CURRENT.
- Next: allow the normal publisher to create the next fixed release, run the Mac mirror, verify all 2,655 references, and retain the one 2,000-row saturation response as `blocked` pending a legal split strategy.
