# `anns_d` saturation maintenance production acceptance

- Owner node: Mac Tushare archive authority.
- Source commit: `0087756ab3e53bd0957a3f3e4dee063a8a850eb8` on `master`.
- Scope: retain every announcement response while removing duplicate blocker states once the same logical day has a durable historical identifier fanout; recover exact date-bisection parents stranded by parent normalization timeouts.

## Evidence before mutation

The 20 blocked non-history roots for `20260915..20260915` and the canonical history parent each contained the same ordered 2,208 natural keys. Their raw objects and normalized observations were distinct immutable captures, so they were retained. The canonical history parent already owned 5,915 stock-code children and remained `split_pending` with `universe_unverified`; this change does not claim that the supplier exposes an independently exhaustive announcement-security universe.

The remaining blocked history parent for `20200416..20200423` already owned the two exact, exhaustive date children `20200416..20200419` and `20200420..20200423`. Its raw response was durable, and only parent Parquet normalization had timed out. Both children were still pending.

The production selection used the existing state and partition indexes. It found exactly 20 recent-cap retirement candidates and one recoverable date parent in 0.011 seconds and required no supplier request.

## Implemented behavior

- A non-history capped `anns_d` root is superseded only when an active history root with the same logical request owns a nonempty identifier fanout.
- The response, tries count, attempt rows, raw object, observation and Parquet references remain byte-identical.
- A blocked date-bisection parent is restored only when its result records the same two legal date children, the saved partition proves exhaustive date coverage, every child relationship matches the parent API and epoch, and the original raw object and observation remain present.
- New date-bisection parents remain `split_pending` if parent normalization fails after their children are durably created, so future work cannot strand the child queue.
- The maintenance runs inside the existing planning/queue-compaction phase and is idempotent. It records zero upstream calls and a capability receipt.

## Verification

- Focused and adjacent suite: 98 tests passed.
- `ruff check`, Python compilation and `git diff --check`: passed.
- A production-data isolated copy retained 8,840 real jobs, 1,323 splits and 8,559 child edges; it produced the exact 20/1 transition, preserved all 2,368 copied attempts, and passed `PRAGMA quick_check`.
- The separate broad legacy planning test still has its pre-existing `12 != 17` expectation; it is unrelated to the files and behavior changed here and was not represented as passing.
- Installed runtime SHA-256 matched the repository for both changed runtime modules.

## Production result

The writer reached a natural disabled boundary before installation; QuantDB and cloud services were not stopped. The live transaction changed 20 roots from `blocked` to `superseded` and one parent from `blocked` to `split_pending`. It preserved 21 result bodies, 21 selected attempt histories, 62 referenced artifacts and 13,418,821 verified bytes. `anns_d` now has zero blocked jobs and the database passed `PRAGMA quick_check`.

Local immutable receipt:

`validation/announcement-saturation-maintenance-v1.b915587d685fada1b72a66112c1958c7be3fc4033a3951b62724ef8a3b0f77b7.json`

The restored worker started as PID 54273. Its first post-deployment cycle made 382 real supplier requests in 100.712 seconds with no failed stage and no transport, rate-limit, permission, API or invalid-response result among those attempts. The cycle produced 219 `sample_ok`, 153 `empty_unverified`, three `schema_gap` and seven retained `possibly_truncated` responses. Worker stderr remained empty and the archive filesystem retained about 2.3 TiB free.

The complete local Tushare archive is still running. Announcement history still carries the explicit unverified-universe gap until every retained fanout child finishes and an independent completeness proof exists; superseding duplicate recent blockers does not weaken that boundary.

