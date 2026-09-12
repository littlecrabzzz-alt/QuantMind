# Tushare portfolio read closeout review

- Owner: `/root/financial_next_batch`
- Base: `21c49a2d842101f50646f79bd853b530a956f6b6`
- Candidate before review: `92cf388ab9db3bd867697bba5ca623826e7d9663`
- Candidate after review: `b8120486` on `codex/tushare-portfolio-read-contracts`
- Worktree: `/private/tmp/quantmind-portfolio-read-contracts`
- Production/upstream effects: none; no credentials, authority database, service, deployment, or provider access.

## Reproducible baseline comparison

Using the same `/tmp/quantmind-calendar-factor-test310/bin/python` (Python 3.10) on detached base and candidate, these exact tests fail identically:

- `scripts.test_tushare_general_rate_refinement.GeneralRateRefinementTests.test_exact_frozen_partition_no_omission_or_new_scope`: actual rate API set contains the pre-existing `fina_mainbz_vip` missing from the fixture expectation.
- `scripts.test_tushare_scope_gaps.ScopeAuditTests.test_real_cli_and_frozen_evidence_recompute`: actual `registered_outside_named_scope` is `['fina_mainbz_vip']`, fixture expected `[]`.

This is unchanged baseline debt, not introduced by the portfolio candidate.

## Review findings and fixes

- Fixed privacy defect: existing authenticated generic `/api/v1/tushare-data` catalog/schema/query routes could enumerate and read account-private `p_list`/`p_get`; QuantBot reuses these functions. The router now filters dataset and coverage enumeration and returns the same generic 404 for both private schemas and queries. Local fixed-release `tushare_store.read_dataset` remains available for explicit account-local use.
- No second Tushare fixed-store HTTP, GraphQL, or tool reader was found. The API gateway only proxies this engine route. Document readers do not map these non-document portfolio APIs.
- Fixed snapshot selection: `portfolio_read_identifier` now receives the validated configured epoch and uses `jobs_partition_lookup(epoch,json api)` rather than choosing the newest terminal `p_list` across epochs. It still requires the same Pipeline authority/root, `portfolio_read` group, unfiltered `p_list`, and terminal `done|empty` state; `_observed_names` retains status/shape/epoch validation.
- Temporary-schema `EXPLAIN QUERY PLAN` confirms `jobs_partition_lookup` is selected.

## Validation

- Focused portfolio/router/QuantBot suite: 25 passed.
- Adjacent portfolio/router/QuantBot/legacy/offcatalog/store/rate suite: 50 passed.
- Full `test_tushare*.py`: 1169 run, 2 failures above, 5 skipped; no candidate-specific failure.
- Ruff, Python compile, and `git diff --check`: passed.
