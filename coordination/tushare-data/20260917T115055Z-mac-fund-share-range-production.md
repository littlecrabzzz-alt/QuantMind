# Tushare fund-share history range production rollout

- Owner: Mac full archive
- Date: 2026-09-17
- Master implementation: `ad910851`
- Scope: `fund_share` history planning and open exact-day queue migration
- Unchanged: recent requests remain exact-day; full archive ownership and cloud research-cache boundaries remain unchanged

## Source contract

- Official interface: `https://tushare.pro/document/2?doc_id=207`
- Legal filters: `start_date`, `end_date`, `market`
- Reviewed limit: 2,000 rows per request
- History starts with closed calendar-month roots for `SH` and `SZ`. A response at the reviewed limit follows the existing lossless date-bisection path.

## Validation before production

- Related planner, append, migration and regression tests: 56 passed.
- Ruff, compileall and `git diff --check`: passed.
- Consistent 12 GB authority snapshot: `PRAGMA quick_check=ok`.
- Snapshot rollback validation covered all 19,962 then-open exact-day jobs with 882 month roots.
- Attempts preserved: 392,505.
- Result-bearing jobs preserved: 389,171.
- Upstream calls: 0.

## Production migration

- The Tushare LaunchAgent was drained immediately after a completed 227-request real cycle. Archive and pipeline locks were verified free. QuantDB was not stopped or reconfigured.
- A copy-on-write preimage was retained through post-deployment acceptance.
- Production advanced during validation, so the atomic apply retired the 19,960 exact-day jobs still open and inserted 882 month roots.
- Candidate attempts: 0.
- Attempts preserved: 392,814.
- Result-bearing jobs preserved: 389,480.
- Upstream calls: 0.
- Content-addressed receipt: `low-volume-daily-retirement-v1.71d95368b5d3a8c887cd9960a07ff808e283be9260dcbb3a358e53ac922eb0a7.json`.

## Post-production acceptance

- Post-commit consistent copy: `PRAGMA quick_check=ok`.
- Pending `fund_share` history days: 0.
- Active `fund_share` history ranges: 882.
- Active parent references to retired children: 0.
- Parent and append history planning states reset: 2.
- First post-migration real cycle:
  - requests: 170
  - elapsed: 131.642 seconds, including the reset planning pass
  - documents: `ok`
  - `failed_stage=null`
- Queue after acceptance:
  - pending: 2,682,418
  - done: 196,626
  - empty: 181,629
  - superseded: 5,671,721
- Fixed-release publication remains on the existing hourly cadence; the authority database already contains the durable migration and new real responses.
