# Tushare optional field handling and 105-second worker gray tier

- UTC evidence time: 2026-09-17T07:59:22Z
- Code commit: `587d2d512e3123da118572ecb17129d62fde01b7`
- Archive owner: Mac, `/Users/lizeyu/Library/Application Support/QuantMind/tushare`

## Research-report field semantics

The official `research_report` output table does not list `file_name`, while its
explicit-fields example requests and displays it. Production range responses
repeatedly omitted `file_name` even when it was explicitly requested. The
capture contract now keeps requesting the field and records both
`requested_missing_fields=["file_name"]` and
`optional_requested_missing_fields=["file_name"]`, but an otherwise valid row
is `sample_ok` with `field_coverage=optional_gap` instead of `schema_gap`.
Required columns and all other explicitly requested columns remain blocking.

This lookup is applied from the current API contract at capture time. Existing
queued job JSON and logical identities do not change, so the correction does
not duplicate the historical queue.

Official source: <https://tushare.pro/document/2?doc_id=415>

Production acceptance used an existing history job, not a new probe identity:

- job `cdeb2edd465c7c284726bf94cdc9b6b70997ad5be3c53a10d72b710bdde9944e`
- range `20221109..20221115`
- 679 rows, state `done`, result `sample_ok`
- `field_coverage=optional_gap`; the missing optional field remains observable

Previously stored quality observations and raw payloads are retained unchanged
as historical provider evidence. They were already included in immutable
releases with an explicit quality state; no evidence was rewritten or deleted.

## Worker duty-cycle gray tier

Production configuration now uses:

- `batch_requests=400`
- `batch_seconds=100`
- `archive_worker_cycle_seconds=105`
- account ceiling and rollout ceiling both remain 500 RPM

The worker validates the cycle interval in the range 105 to 3600 seconds. This
setting changes only idle time between bounded cycles; account, API-specific and
daily-quota gates remain authoritative.

Two consecutive real cycles at the new interval completed:

| Cycle | Requests | Elapsed | Failed stage |
| --- | ---: | ---: | --- |
| 1 | 362 | 100.860 s | none |
| 2 | 342 | 100.728 s | none |

Across the two cycles, 744 attempts were durably recorded: 323 `sample_ok`, 410
`empty_unverified`, 10 `possibly_truncated`, and 1 unrelated `schema_gap`.
There were zero new `rate_limited`, `transport_error`, `api_error`, or
`invalid_response` attempts. Existing observed daily limits for `idx_anns`,
`factor_value`, `stk_mins`, and `hk_daily` remain stored and enforced.

At the evidence point the worker was running with about 2.565 TB free,
`failed_stage=null`, and 2,947,903 pending jobs. Planning added more historical
jobs during the rollout, so the pending-count change is not used as a throughput
claim. Full historical completeness remains open and the worker continues.

## Verification and dual-node boundary

- Archive worker tests: 5 passed.
- Field coverage tests: 11 passed.
- Text contract tests: 7 passed.
- Intake tests: 7 passed.
- Core pipeline tests: 17 passed.
- Ruff and diff checks passed.
- A replay of an actual stored 50-row research-report response produced
  `sample_ok` plus the explicit optional gap without any upstream call.
- Runtime/source SHA-256 matched for the deployed intake, text-contract and
  archive-worker files.
- Cloud Git metadata matches `587d2d51`; `tushare-research-cache.timer` is active.
  Full acquisition remains Mac-owned and the cloud receives published research
  subsets only.

The broader extended-planning test still has its pre-existing count assertion
failure (`12 != 17`) on both unchanged `master` and this branch. The document
suite's PDF-only cases also require `reportlab`, which is not installed in the
archive runtime. Neither failure covers the changed field assessment or worker
interval paths; both are retained as validation-environment/baseline issues.
