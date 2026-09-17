# Tushare exchange risk-event range acquisition deployed

- UTC evidence time: 2026-09-17T07:36:40Z
- Archive owner: Mac, `/Users/lizeyu/Library/Application Support/QuantMind/tushare`
- Code commit: `b14cc9f7bb040ab069397421e801deb0391876a3`
- Runtime/source contract SHA-256: `4a5f6ffdb4c89b90114dcde4e78ef8b1399c66af8f15b5ead5b27f29e6920477`

## Provider evidence and correction

The official `stk_high_shock` and `stk_alert` documents allow `start_date` and
`end_date`. Live account calls showed that documented exact `trade_date` examples
can return an empty response even though an enclosing legal range returns rows:

- `stk_high_shock`: exact `20260312` returned 0 rows; `20260101..20260331`
  returned 7 rows.
- `stk_alert`: exact `20260311` returned 0 rows; `20260101..20260331`
  returned 19 rows.

The planner now uses one bounded recent range and calendar-month history ranges
for these two APIs. Existing date bisection handles a saturated range. Other risk
event APIs retain their reviewed request shapes. Historical exact-date attempts
and responses remain preserved as provider evidence.

Official sources:

- <https://tushare.pro/document/2?doc_id=452>
- <https://tushare.pro/document/2?doc_id=453>

## Verification and deployment

- `scripts/test_tushare_risk_event_contracts.py`: 7 passed.
- `scripts/test_tushare_risk_event_pipeline.py`: 7 passed.
- `scripts/test_tushare_technical_extra_pipeline.py`: 10 passed.
- Ruff, compileall and `git diff --check` passed for the changed files.
- `master` and `origin/master` were fast-forwarded to `b14cc9f7`.
- The Tushare worker alone was drained at an idle pipeline/document lock point,
  the runtime was installed, and the LaunchAgent restarted. QuantDB was not
  stopped or reconfigured.
- Production `risk_event_apis` now contains `stock_st`, `st`, `stk_shock`,
  `stk_high_shock`, and `stk_alert`; the global historical lower scope remains
  `19900101`.

Real production queue acceptance, one upstream call per task:

| API | Production range | State | Rows | Result |
| --- | --- | --- | ---: | --- |
| `stk_high_shock` | `20260301..20260331` | done | 1 | `sample_ok` |
| `stk_alert` | `20260301..20260331` | done | 7 | `sample_ok` |
| `stk_alert` | `20260911..20260917` | done | 5 | `sample_ok` |

The completed worker cycle made 338 requests in 90.772 seconds, reported no
failed stage, retained about 2.566 TB free, and left the full archive backfill
running. At the evidence point, the entire queue still had 2,944,192 pending
jobs, so historical completeness is not claimed. The new observations are
durable and await the normal immutable release publication cadence.

## Cloud boundary

`scripts/dual-node.sh handoff --align-git mac` passed at `b14cc9f7`. The cloud
repository metadata matches that commit, `tushare-research-cache.timer` is
enabled and scheduled, no cloud Tushare acquisition writer is installed, and
the relocated marker identifies the Mac hostname as owner with `source_paused`
true. The cloud continues to receive only the bounded research cache from a
published Mac release; full acquisition data and credentials remain local.

## Remaining provider gaps

The fixed-release coverage audit still has eleven documented names whose live
provider calls return code `40101` (`请指定正确的接口名`): `bo_cinema`, `bo_daily`,
`bo_monthly`, `bo_weekly`, `film_record`, `fund_sales_ratio`, `fund_sales_vol`,
`stk_account_old`, `teleplay_record`, `tmt_twincome`, and
`tmt_twincomedetail`. These are retained as explicit provider-side gaps while
the other families continue; no undocumented alias was invented.
