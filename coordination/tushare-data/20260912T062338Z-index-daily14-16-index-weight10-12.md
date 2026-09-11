# Tushare index exact window 2026-09-12 06:23 CST

- The ordinary task `12907753-c902-4645-9355-808d787501ba` completed naturally before the worker exited; no task was revoked or killed.
- Six pristine, zero-overlap exact batches ran serially against fixed release `data-eb6bf9a06e48821b8dccf7765846c2f87593aa3560c60ebbdef57a0529d9e1bd`: `index_daily` batches 14-16 and `index_weight` batches 10-12.
- The window made 2,160 upstream calls in 274.699 seconds (471.789 observed RPM). All attempts returned HTTP 200, complete responses and `supplier_has_more=false`.
- Retained results contain 601,159 rows and 6,343 unique files totaling 90,141,292 bytes. Every file size/SHA and observation-to-object link passed independent read-only closure checks.
- States are 1,919 `sample_ok`, 137 `empty_unverified` and 104 `possibly_truncated`. The saturated index-weight parents produced 208 pristine pending child tasks; they remain continuation obligations.
- Exact batches did not publish or switch CURRENT. Worker and Beat were restored with their existing containers and were healthy, with worker restart count zero and OOMKilled false.
- Complete pins and per-batch receipts are recorded in `docs/tushare-index-window-14-16-weight10-12-20260912.evidence.json`. Fixed release publication and Mac offline acceptance are separate next gates.
