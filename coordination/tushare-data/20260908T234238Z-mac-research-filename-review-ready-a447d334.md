# research_report file_name real-response review complete

text_contracts / Mac / read-only, no runtime changes, upstream/account requests or credentials. Parent has already attached known_field_gaps to ledger415 without deleting the requested field. Challenge candidate5246705 remains separate.

## Exact evidence and conclusion

Observed request to research_report: params={"start_date":"20221001","end_date":"20221031"}; fields="abstr,author,file_name,ind_name,inst_csname,name,report_type,title,trade_date,ts_code,url". Recorded 2026-09-08T23:37:47.839029+00:00 at runtimef2cd52e. Observation b0750473814b4996bca4a7572f591e43.json; object44652b0754efb081055d85a3d3e6ee5d13a31e14f18b13919f3fee37ae1c0ecc.

Parent extracted only request/assessment/raw schema to /tmp/quantmind-research-report-field-review.json and verified original objectSHA. Reviewer independently checked this export's hash554d1181db1fe523c8138c7e7c58d7ef08b8b7ea21c9a312fa6a47fb95f8f616 and field-set differences; reviewer did not receive/read1000 source rows or independently rehash the full object. Export records verified_sha256=true, code0, HTTP200, response_redacted=false.

Actual data.fields equals the10 official output-table columns, with no unexpected columns. file_name has no column index: it was requested but absent from the supplier response schema, not merely null in some rows. This is a real source-response field gap, unlike the earlier mock-only reproduction. The raw schema establishes that normalization did not cause this missing column. Existing required10 fields all present (missing_fields=[]); new requested-field guard correctly persists field_coverage=gap/requested_missing_fields=[file_name].

There is also independent row truncation:1000rows and supplier_has_more=true. possibly_truncated must stay the primary status and normal authorized split/follow-up logic must continue. Repairing/relaxing field coverage would not resolve the row-limit gap.

## Official contract ambiguity

Source https://tushare.pro/document/2?doc_id=415 ; saved /tmp/quantmind-known-fields-audit-20260909/415.html SHA25653ff6e0121bddbad90899cb7f97676adbd4861e139c489c08aaf059d985d71c4.

The official output table lists trade_date,abstr,title,report_type,author,name,ts_code,inst_csname,ind_name,url (all defaultY), exactly the observed schema. The same page's SDK example explicitly selects trade_date,file_name,author,inst_csname for trade_date20260121, and its sample table contains PDF-looking file_name values. Current contract extra_fields=[file_name] intentionally follows this example; it was not an invented provider field or accidentally derived normalization column. Existing contract notes already record this example-only discrepancy.

The evidence establishes inconsistency between the documented example and this real range request. It cannot distinguish a stale/incorrect example, conditional/historical schema availability, date-vs-range behavior, or an unsupported field on this current endpoint. The observed data range is October2022 whereas the example is January2026; do not claim universal unsupported status from one range, or infer a missing independent permission from a successful response with one absent column. No extra HTTP/SDK probe was performed.

## Minimal follow-up

1. Keepfile_name requested, retain the newknown_field_gap with observation/hash/date-range/source-doc provenance, and keep existing successful10-column raw/Parquet and url attachment work available. Do not fill file_name from title, the URL basename or Content-Disposition: those are separate source concepts and any future derived filename would need an explicit derived label/provenance.
2. Separately track field availability and row coverage: the1000/has_more partition needs its regular completion path. A future below-cap response still omittingfile_name correctly remains schema_gap rather than an all-fields success; do not weaken the common guard or erase the requested field to manufacture completeness.
3. Next smallest validation is to inspect a few already-retained recent/single-date research_report schemas, if present, or observe the same field on the normal scheduled capture stream. No new bulk requests are needed. If it remains absent, send the supplier an authorized support question with the exact request schema and the415example discrepancy (no token/1000report bodies). Ask whether file_name is valid and period/filter-dependent. A new controlled account probe or API rename/removal requires a subsequent explicit decision.
4. Only a confirmed vendor contract correction should change the static source field status/request policy. Historical observations stay immutable; newly confirmed semantics must not retroactively assert that the original11-field request was complete.

No production changes or runtime file ownership; review complete.
