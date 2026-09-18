# Mac retained-null contract reassessment production acceptance

- Commit: `846ae6e2` (`fix(tushare): accept retained source nulls`).
- Scope: `cctv_news`, `major_news`, `news`, `stk_holdernumber`, `stk_rewards`, `fund_portfolio`, `fut_weekly_detail`, `fina_audit`, and the already-reviewed current `etf_basic` nullable contract.
- Contract rule: only source-observed nullable values were accepted. Stable identifiers and remaining date/period evidence stay required. Nulls are retained as null; no field is filled, shifted, inferred, or dropped.
- Legacy rule: a pre-transport-metadata response is eligible only when object and observation checksums pass and the retained observation matches API, parameters, and fields while the raw payload has `code=0` and `has_more=false`. Missing HTTP status is recorded as `not_recorded`, never manufactured as 200.

## Validation and production result

- 56 contract/reassessment tests and 43 pipeline/runtime tests passed; Ruff and `git diff --check` passed.
- Read-only production projection verified every referenced object, observation, and Parquet artifact. It selected 552 jobs, including 16 legacy-response jobs, and predicted 552 promotions with zero unchanged failures.
- Production dry-run repeated the same result while preserving all 542093 attempts and performing zero upstream calls.
- Transactional apply promoted all 552 jobs from `quality/schema_gap` to `done/sample_ok`. The immutable receipt is `contract-reassessment-v1.5ed57e242938d98f69e35f24749c40bc551b116ff9b8d53ff3ed9dea1fc50b37.json`; its content SHA-256 is the same suffix.
- Post-apply `PRAGMA quick_check` returned `ok`; the attempt count remained 542093 at the apply boundary. The nine target APIs had zero remaining quality jobs.
- Global quality count fell from 564 to 12. The remaining 12 are `possibly_truncated` parent responses and were deliberately not promoted as complete.
- The first restarted cycle was the scheduled local `planning_only` pass. The next production cycle completed 731 real Tushare requests and 240 document tasks in 101.12 seconds. Quality remained 12 and no target schema gap returned.
- Archive free space after acceptance was 2483543388160 bytes. The 288-byte stderr file is unchanged from the earlier controlled process bootout semaphore-cleanup warning; this deployment added no stderr.

The Mac archive worker continues full-history acquisition. This reassessment changes job classification only after immutable-artifact verification; it does not claim supplier history, revisions, or point-in-time coverage complete.
