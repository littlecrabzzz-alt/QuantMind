# Tushare index exact window 2026-09-12 05:32 CST

- Beat was stopped first. The active ordinary acquire task `d9977078-3b52-46ce-aad0-45c47d56f12e` completed naturally in 233.915 seconds before the worker exited cleanly; no task was revoked or killed.
- Six pristine, zero-overlap exact batches ran serially against fixed release `data-76b031903c08e660d869cb8ef8218dab6cca8bd23cc8811adcf55adbdd8d0898`: `index_daily` batches 11-13 and `index_weight` batches 7-9.
- The window made 2,160 upstream calls in 266.873 seconds (485.624 observed RPM). All 2,160 attempts returned HTTP 200, complete responses and `supplier_has_more=false`.
- Retained results contain 590,235 rows and 6,267 unique files totaling 91,464,651 bytes. Every file size/SHA and observation-to-object link passed independent read-only closure checks.
- Results are 1,842 `sample_ok`, 213 `empty_unverified` and 105 `possibly_truncated`. The 105 saturated index-weight parents produced 210 pristine pending child tasks; they remain continuation obligations.
- Exact batches did not publish or switch CURRENT. Worker and Beat were restored with `docker start`; the single expired periodic message was naturally discarded before a fresh ordinary task started.
- Complete pins and per-batch receipts are recorded in `docs/tushare-index-window-11-13-weight7-9-20260912.evidence.json`. Fixed release publication and Mac offline acceptance are separate next gates.
