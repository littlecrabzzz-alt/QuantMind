# RRG PIT/ETF fixed-release bridge ready

- UTC 2026-09-10 03:28:39; Mac; `rrg_data_closure_next`.
- Status: ready for integration. Branch `codex/rrg-data-closure-next`; implementation commit `912cd0b56f2a36b8ad4903fa8c610b02fe52d23c` from `origin/master` `9ce875e0`.
- Scope delivered: `scripts/prepare_tushare_rrg_pit_etf_bridge.py`, focused test, runbook, machine evidence and start/ready records. No shared main-tree edit, upstream/credential/cloud/production access, case promotion, signal, return or backtest.

Fixed mirror acceptance (`data-2c8715f9920400555ccab3f739c982938cb127f72db1a1c6c0bb18378b6f1662`, signal 20260831, execution 20260901, about 34 s, zero upstream): 6,740 member rows / 0 known-at; 1,829 observed ETF codes / 1,648 SH/SZ date candidates; 1,645 exact-day prices with valid factors; three missing prices (`SH511670`, `SH511920`, `SZ159578`); 901 codes and 39,543 rows from the latest strictly pre-signal disclosure; zero exact-day PCF rows. Output `/tmp/quantmind-rrg-pit-etf-final-20260910T0335Z`, report SHA `897f3720f6c9530c6788c046c6d7a8033af13bdad42b26a24fc8f9aa95457b8c`, artifact manifest SHA `db2993de97236fa71f9ac10f8dbde543062466caa7edda26a081bff2645f9f04`.

Validation: 19 focused RRG/store tests passed; current uncommitted RRG config's required columns passed against all four mapped datasets; Ruff, format, JSON, evidence/script digest and `git diff --check` passed.

Remaining gates: authoritative CITIC membership publication/known-at and classification revisions; versioned PIT ETF-to-industry mapping chosen independently of returns; comparison-window price/factor/dividend/tradability coverage; exact historical PCF plus pre-open publication/version evidence; semantic review of partial fund disclosure versus PCF. Do not fill the three missing opens or substitute 20260904 PCF for 20260901. Next integrator may cherry-pick `912cd0b5` and this ready-record commit, then schedule exact missing-data collection through the existing cloud pipeline separately.
