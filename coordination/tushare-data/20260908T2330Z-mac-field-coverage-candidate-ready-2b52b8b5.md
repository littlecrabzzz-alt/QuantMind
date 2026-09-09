# Explicit field coverage candidate ready — text_contracts / Mac

Commit f306b53 (isolated codex/tushare-text). Only backend/shared/tushare_intake.py (+27 lines), new scripts/test_tushare_field_coverage.py, docs/tushare-field-coverage.md. Runtime ownership released to parent. No pipeline/schema3/registry/router changes; no production calls/config/deploy.

Persists requested_missing_fields/unexpected_returned_fields/field_coverage in immutable observation and result. Nonempty otherwise sample_ok plus missing explicit field becomes existing schema_gap; all source rows/unknown fields/raw remain. Default/invalid/error unverified (difference lists null); empty/capped original status retained with independent coverage. Optional null values count as present. No old observations rewritten.

Validation: 21 new-field/intake/HTTP evidence tests +17 pipeline acceptance=38 pass; Ruff/diff checks pass. Tests MockTransport/temp-only. Bounded fixed report audit: extra13 15 API+params matched requests,13 nonempty schemas all requested columns present,2 empty without returned_fields unverified. Missing local global-VIP report means no claim of production VIP omission. Full exact results /tmp/quantmind-known-fields-audit-20260909/fixed-sample-review.json and prior report/reproduction/audit.md; short durable summary in commit doc. Parent can cherry-pick independent delta.
