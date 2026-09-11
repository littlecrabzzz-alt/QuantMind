# fina_mainbz_vip exact quarterly batch ready

- Owner: `/root/fina_mainbz_exact_runner`
- Scope: runtime contract/catalog/rate evidence plus `prepare_tushare_fina_mainbz_vip_batch.py`, `run_tushare_fina_mainbz_vip_batch.py`, and focused tests.
- Semantics: immutable `{period,type}` quarter requests; P/D/I retained; output `end_date` is report period; company `ts_code` retained from source. Official earliest history, announcement time, known-at, PIT and full-history coverage remain unverified.
- Saturation: documented 100-row cap; no documented offset/page/limit. A saturated exact quarter/type request blocks as a terminal completeness gap and is not split.
- Safety: runner defaults to plan-only. Execute remains behind authority/ENABLED/schema/shared lock/100 GiB/rate/hash/deadline gates, and does not publish or switch `CURRENT.json`.
- Validation: 40 focused and adjacent tests passed with isolated SQLite and Mock HTTP. No production API or production SQLite was accessed. `ruff` is unavailable on this Mac.
