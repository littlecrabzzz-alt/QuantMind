# Tushare low-volume history range production rollout

- Owner: Mac full archive
- Date: 2026-09-17
- Master implementation: `2750657b`
- Scope: `daily_info` and `dc_daily` history planning only
- Unchanged: recent seven-day requests remain exact-day; `suspend_d` remains exact-day because its official page does not publish a numeric row limit

## Source contract

- `daily_info`: official `start_date`/`end_date`, 4,000 rows per request, source `https://tushare.pro/document/2?doc_id=215`
- `dc_daily`: official `start_date`/`end_date`, 2,000 rows per request, source `https://tushare.pro/document/2?doc_id=382`
- Month roots use the existing lossless date-bisection path whenever the provider reports or reaches the reviewed cap.

## Validation before production

- Related offline tests: 30 passed.
- Planning, installation and market-sentiment regression tests: 33 passed.
- Ruff, compileall and `git diff --check`: passed.
- Consistent 12 GB authority snapshot: `PRAGMA quick_check=ok`.
- Snapshot rollback validation covered all 9,724 then-open exact-day jobs with 673 month roots:
  - `daily_info`: 6,944 days -> 430 ranges
  - `dc_daily`: 2,780 days -> 243 ranges
  - attempts preserved: 390,924
  - result-bearing jobs preserved: 387,590
  - upstream calls: 0

## Production migration

- The Tushare LaunchAgent was drained immediately after a completed real cycle; both archive and pipeline locks were verified free. QuantDB was not stopped or reconfigured.
- A copy-on-write preimage was retained through post-deployment acceptance.
- Production state had advanced during validation, so the atomic apply retired the 9,685 exact-day jobs still open:
  - `daily_info`: 6,918
  - `dc_daily`: 2,767
  - planned/inserted range roots: 673 (`430 + 243`)
  - candidate attempts: 0
  - attempts preserved: 391,710
  - result-bearing jobs preserved: 388,376
  - upstream calls: 0
- Content-addressed receipt: `low-volume-daily-retirement-v1.cdeba48cfcaa41de8ab38841f695e27ce09db750696f8ebee718956587c8cd44.json`
- Post-commit consistent copy: `PRAGMA quick_check=ok`.
- Post-commit queue proof:
  - target pending history days: 0
  - active history ranges: `daily_info=430`, `dc_daily=243`
  - active parent references to retired children: 0
  - target history planning states reset: 2

## Real traffic acceptance

- First post-migration cycle: 194 real requests, 101.066 seconds, documents `ok`, `failed_stage=null`.
- Second post-migration cycle: 156 real requests, 100.575 seconds, documents `ok`, `failed_stage=null`.
- Queue after the second cycle:
  - pending: 2,699,598
  - done: 196,205
  - empty: 181,154
  - superseded: 5,651,761
- Fixed-release publication remains on the existing hourly cadence. The queue migration and real responses are durable in the authority database; the next due publication will advance `CURRENT.json` without changing acquisition ownership.
