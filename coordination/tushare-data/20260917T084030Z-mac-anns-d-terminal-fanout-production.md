# `anns_d` terminal-day fanout production acceptance

- Owner node: Mac Tushare archive authority
- Code: `f09829a20e74a7de671741e0b54e1a56d9695e1a` on `master`
- Scope: announcement history completeness after a single-day response reaches the supplier cap
- Supplier contract: <https://tushare.pro/document/2?doc_id=176> documents `anns_d`, a maximum of 2000 rows per request, date cycling, and an optional `ts_code` filter.

## Trigger and live evidence

The unfiltered request for `20260915..20260915` returned 2208 rows while the reviewed contract cap is 2000, so `has_more=false` cannot prove completeness. A two-request live diagnostic established that response codes such as `SZ300604` must be converted to the documented request value `300604.SZ`; sending `SZ300604` returned zero rows while `300604.SZ` returned 25 rows.

The production acceptance task `bda8761824b636aed58ee8a1f0a80bfd666d1ee6fc57a90ca05c2da91c99907b` performed one real unfiltered upstream request. It retained the 2208-row object and observation, recorded `possibly_truncated`, and entered `split_pending` with a durable identifier-fanout checkpoint.

## Implemented behavior

- A capped historical single day fans out through the all-status and historically observed A-share stock universe using `ts_code`.
- Supplier prefix-form announcement codes are normalized to valid Tushare suffix-form request codes.
- Fanout creates at most 1000 new child jobs per resume to bound planning work.
- Recent hourly observations do not fan out, preventing duplicate multi-thousand-job trees before a day becomes stable history.
- Coverage remains explicitly unproven because the supplier exposes no independent announcement total or exhaustive listed-company universe for the day.

Production planning created 5915 unique child tasks in six bounded batches. All 5915 codes match `[0-9]{6}.(SH|SZ|BJ)`, the live-verified `300604.SZ` is included, and the recent-window parents have zero child edges. The first normal worker cycle processed nine of these tasks; all nine returned empty observations, leaving 5906 pending.

## Verification

- `scripts/test_tushare_anns_d_saturation.py`: 5 passed
- `scripts/test_tushare_text_contracts.py`: 7 passed
- `scripts/test_tushare_pipeline.py`: 17 passed
- `ruff check` on the changed files: passed
- compile check and `git diff --check`: passed
- `scripts/test_tushare_extended_pipeline.py`: retains the pre-existing `12 != 17` bounded-planning baseline failure; it is unrelated to these files and was not represented as passing.
- Deployed runtime/source SHA-256 values matched for both changed shared modules.
- First post-deployment cycle: 349 upstream requests in 100.695 seconds, `failed_stage=null`; the latest 349 attempts contained no transport, rate-limit, permission, API, or invalid-response status.
- Archive worker restored under LaunchAgent PID 50219. QuantDB and other services were not stopped.
- Current pipeline state after the cycle: 2,956,021 pending; archive filesystem reports about 2.3 TiB available.

The complete Tushare archive is still in progress. This change closes the executable terminal-day recovery path for announcements, but it does not claim an independent proof that every supplier announcement exists in the returned universe.
