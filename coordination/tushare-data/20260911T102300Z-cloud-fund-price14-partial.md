# Tushare fund price exact batch 14 partial closure

- Cloud authority froze 180 common SSE dates from 2010-07-19 through 2011-04-18 for both `fund_daily` and `fund_adj`: 360 pristine jobs, fixed release/config/calendar/preparer/helper/task inventory hashes, and a plan-only pass with zero authority, credential, upstream, write or publish access.
- The 90-second hard cap stopped at 337 attempts. It retained 336 HTTP 200 results and 41652 rows; 336 objects, 336 observations and 336 Parquet files form 1008 unique references and 7380294 bytes, all SHA256 verified. Twenty-three jobs were never attempted and remain pending. One `fund_daily` request ended in `ReadTimeout`, `response_complete=false`; it remains pending and is counted as one uncertain upstream call.
- Reusing the original manifest passed plan-only but the execution pristine guard rejected it before a new upstream call because some manifest jobs were already completed or attempted. This is the expected replay protection; no override was used.
- The account ceiling stays 500 RPM and the 90-second cap stays fixed. The next fund-price exact window will use at most 300 requests until a clean batch supports raising it again. QuantMind, Worker and Beat are healthy. Free disk remains 114999058432 bytes above the 100 GiB reserve.

The completed 1008 references await a later normal fixed release and Mac mirror. The 24 pending leaves remain ordinary backlog; no completeness claim is made. Machine evidence: `docs/tushare-fund-price-batch14-20260911.evidence.json`.
