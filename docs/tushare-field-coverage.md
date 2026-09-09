# Explicit request field coverage

`capture_sample` records `field_coverage`, `requested_missing_fields` and
`unexpected_returned_fields` in both its returned result and immutable observation
assessment. This compares the explicit comma-separated request against a validated
successful response schema; it does not infer all undocumented supplier fields.

- `complete_for_explicit_request`: every named field is present, even if nullable
  values are null. It proves neither historical completeness nor PIT availability.
- `gap`: named fields are absent. An otherwise `sample_ok` nonempty response becomes
  existing `schema_gap`; required-field `missing_fields` remains a separate check.
- `unverified_default_or_invalid`: default/invalid field selection, invalid response,
  permission/HTTP/transport failure. Difference lists are null, not falsely empty.

Empty, capped, invalid-value and permission/error statuses keep their existing
meaning. Valid empty/capped responses still record simultaneous field gaps.
Unexpected returned fields are recorded and preserved. No rows are discarded, no
absent columns are filled, and no existing observation is rewritten. Existing
pipeline handling retains quality rows/raw objects and publishes a `schema_gap`;
the exact missing names remain in the referenced immutable assessment. No new
queue, automatic retry or pipeline state is introduced.

## 2026-09-09 bounded evidence

The read-only audit compared real enqueue schemas with 18 current official pages:
all nine paid text APIs, six financial VIP APIs, report_rc, disclosure_date and
stk_surv. None omitted a known output-table field. Known hidden fields are covered
by the current catalog/required/extra union. This is a bounded result, not proof
that the full catalog or undocumented fields are complete.

MockTransport capture→normalization reproduced unchecked optional-field omission:
[income VIP](https://tushare.pro/document/2?doc_id=33) default-only fields omitted
10 requested hidden columns; [balance sheet VIP](https://tushare.pro/document/2?doc_id=36)
6; [financial indicators VIP](https://tushare.pro/document/2?doc_id=79) 59; and
[express VIP](https://tushare.pro/document/2?doc_id=46) 19. Previously these were
`sample_ok` with `missing_fields=[]`. These are synthetic failures, not observed
production losses. The fix catches that shared condition.

[research_report](https://tushare.pro/document/2?doc_id=415) requests `file_name`
from its official example although it is absent from the output table; omission
now stays visible rather than silently passing. Whether a current vendor response
supports it remains a supplier-schema question. [major_news](https://tushare.pro/document/2?doc_id=195)
output `src` conflicts with example `src_site`; the existing required check already
flags absence of `src`. Neither ambiguity justifies guessing aliases or deleting
requested source fields.

Fixed local authority probe reports `/tmp/tushare-extra13-probe.json` and
`/tmp/tushare-extra13-probe-spec.json` matched 15 requests by API and parameters.
All 13 nonempty returned schemas include all requested fields, including
`disclosure_date.modify_date`, `report_rc.imp_dg/create_time`, and `stk_surv.content`.
The two empty report entries omit returned field lists and remain unverified.
This uses retained reports, not a new API capture or independent raw-body hash
verification. `/tmp/tushare-global-vip-probe.json` was unavailable; the VIP concern
therefore remains mock-confirmed only.

Full local audit schemas, official HTML hashes, seven pre-fix reproductions and
fixed-sample comparison are under `/tmp/quantmind-known-fields-audit-20260909/`.
Offline regression: new field-coverage tests, intake tests, HTTP evidence tests,
and pipeline acceptance (38 tests total). Production activation completed in f2cd52e; the integrated 364-test suite passed before release.

## Production observation

The enabled guard observed research_report response b0750473814b4996bca4a7572f591e43.json: 1000 rows, possibly_truncated and field_coverage=gap with file_name absent. The raw response SHA256 is 44652b0754efb081055d85a3d3e6ee5d13a31e14f18b13919f3fee37ae1c0ecc. Saturation and field coverage remain separate findings. The raw response is retained; official output-table/example inconsistency remains under review and no field is silently removed. New trading/listing samples returned all 91 requested columns, including nullable hm_detail.tag.
