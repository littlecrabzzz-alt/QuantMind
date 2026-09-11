# Fund-price 300-request gray window ready

- `prepare_tushare_fund_price_batch.py` now accepts `--days-per-api` from 1 through 180. Its default remains 180 dates and 360 jobs; 150 dates produce the intended 300-job gray window while the manifest verifier derives and enforces balanced API counts and record totals.
- No account ceiling, ordinary worker scheduling, request timeout or publication behavior changed. Financial preparation already has `--jobs-per-api`, so no duplicate implementation was added.
- Six dedicated Python 3.10 tests passed, including the 150-date/300-job case. Ruff and diff check passed. No authority write, credential read or upstream request was made.

Next: deploy the code through the normal Git handoff. After a read-only cooldown snapshot shows no new transport error, prepare the next fund-price exact manifest with `--days-per-api 150`; keep the 90-second cap and all existing hashes.
