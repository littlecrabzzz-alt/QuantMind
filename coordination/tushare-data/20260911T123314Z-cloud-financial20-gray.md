# Tushare financial exact batch 20 at 300-request gray tier

- After fixed release 266b closed, the standard no-revoke drain stopped Beat, cancelled new queue consumption, let the active acquisition finish naturally, confirmed two stable idle inspections and stopped the Tushare Worker.
- The preparer froze 100 pristine jobs for each of `income_vip`, `balancesheet_vip` and `cashflow_vip`. All 300 had pending state, tries 0 and no attempt; all target period 2026-06-30 and report type 1, share 100 code keys, and have zero task-ID overlap with batch 19 or its recovery manifests. Plan-only in the one-off production container made zero authority, credential, upstream, write or publish access.
- Execute completed 300 HTTP 200 requests in 75.148 seconds: each API produced 98 done and 2 empty jobs, totaling 294 done, 6 empty, 545 retained rows and zero uncertain calls. Recomputed SHA256 passed for 300 objects, 300 observations and 294 Parquet files: 894 unique references and 11815432 bytes.
- The first host-Python execute preflight used the host path instead of the configured container authority root and was rejected before locking, credential access, upstream access or writes. The corrected production compose execution used `/data/tushare` and all pinned hashes.
- Worker and Beat were restored healthy. Free disk remains 113359052800 bytes above the 100 GiB reserve; `CURRENT` remains fixed release 266b.

The 894 references await the next normal fixed release and Mac mirror. Complete financial history, revisions, `known_at` and PIT remain open. Machine evidence: `docs/tushare-financial-pit-batch20-20260911.evidence.json`.
