# Tushare financial PIT batch 19 partial closure

- Cloud authority froze 120 pristine jobs for each of `income_vip`, `balancesheet_vip` and `cashflow_vip`. Manifest, task inventory, config, preparer and runner hashes were pinned. A first local orchestration command imported the preparer hash from the wrong module and failed before plan-only or upstream access; the corrected command reused the same frozen manifest and passed zero-access plan-only.
- The 90-second hard cap stopped at 142 attempts. It retained 141 HTTP 200 results and 256 rows; 141 objects, 141 observations and 141 Parquet files form 423 unique references and 5659515 bytes, all SHA256 verified. Another 218 jobs were never attempted and remain pending. One `cashflow_vip` request ended in `ReadTimeout`, `response_complete=false`; it remains pending and is counted as one uncertain upstream call.
- This is the second consecutive exact window with one cross-API `ReadTimeout`. New exact windows are paused until a later read-only gate snapshot after cooldown shows no new transport error. The ordinary Tushare worker and Beat have been restored healthy, so unrelated backlog continues.
- Cloud free disk is 222353924096 bytes, leaving 114979741696 bytes above the 100 GiB reserve. The 423 completed references await a later fixed release and Mac mirror. Complete financial history, revisions, `known_at` and PIT remain open.

Machine evidence: `docs/tushare-financial-pit-batch19-20260911.evidence.json`.
