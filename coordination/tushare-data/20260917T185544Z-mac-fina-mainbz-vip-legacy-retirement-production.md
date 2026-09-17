# `fina_mainbz_vip` legacy contract retirement production acceptance

- Owner node: Mac Tushare archive authority.
- Source commit: `fd3189c914f4fa781445fd67730b3303507045dd` on `master`.
- Scope: retire old no-pagination VIP blocker states only after the same period/type has a complete live-verified `limit=10000`/`offset` chain.

## Coverage gate

The production queue contained 655 modern pages across 438 roots. The compactor proved 299 period/type chains complete, left 139 empty/open roots unproved, found zero invalid pages and one field schema, and identified 61 complete year/type groups. All 239 old blocked period/type tasks matched a complete modern chain. None was referenced by an active partition parent.

Eligibility also required the exact legacy request shape (`period,type`), old row cap 100, matching field schema, a retained `possibly_truncated` response with more than 100 rows, and valid raw object, observation and Parquet references. Incomplete modern chains, recent jobs and unrelated states were unchanged.

## Verification

- Focused and adjacent suite: 71 tests passed.
- `ruff check`, Python compilation and `git diff --check`: passed.
- A production-data isolated copy retained 1,093 real VIP jobs and 1,095 attempts. It produced the exact 239-job retirement, preserved every result and attempt, and passed `PRAGMA quick_check`.
- Installed runtime SHA-256 matched the repository pipeline module.

## Production result

The writer reached a natural disabled boundary before installation; QuantDB and cloud services were not stopped. The live transaction changed all 239 eligible legacy jobs from `blocked` to `superseded`, preserved 239 selected attempts, and made zero supplier requests. It verified 717 referenced artifacts and 286,081,446 bytes before and after the transaction. Result JSON, tries, attempt counts and file bytes remained unchanged. The database passed `PRAGMA quick_check`; total blocked jobs fell from 1,149 to 910.

Local immutable receipt:

`validation/fina-mainbz-vip-legacy-retirement-v1.5102a42f730264e1edf4a1a844e08a991f9cb63db03a5337cf9ebfc91aac5453.json`

The restored worker started as PID 57754. Its first post-deployment cycle made 373 real Tushare requests in 100.654 seconds with no failed stage. The latest attempts contained 207 `sample_ok`, 157 `empty_unverified`, eight retained `possibly_truncated` and one `schema_gap` result, with no transport, rate-limit, permission, API or invalid-response error. Worker stderr remained empty and about 2.3 TiB remained free.

The 139 empty/open modern roots remain explicit and are not coverage evidence. This retirement preserves every old supplier response while assigning the active completeness obligation to the verified pagination chain; it does not claim that all remaining local Tushare history is complete.

