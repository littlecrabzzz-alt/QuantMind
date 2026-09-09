# Calendar/factor5 fixed cloud/Mac audit and bounded value follow-up

Author: text_contracts. Read-only audit; no source request, config/queue mutation, publish, mirror invocation or strategy run.

Both readers verified exactly `data-cf01c59247127378fed86d0f5c26d2d9dbe4b5cbe77906e145d540dfaef9f2fb`, including the Mac historical manifest after its latest advanced to33a0. Approved verifier SHA `136982f4dc21dc723d184002d99c458ff55f19b7d75a8a87a3205ba1fd1b2524`. Probe SHA `96bf1487aa2110919534163037a93a87e6751f1ca09ff0cf260a10330a5d9f82`.

- Cloud original report `/tmp/calendar-factor5-cloud-preenable.json`,16754bytes,SHA `c9501d73898e7ee3455b843729bde934676efa9599da04f69863eeb3d13cfb63`; original bytes copied to Mac and verified.
- Mac `/tmp/calendar-factor5-mac-verified.json`,SHA `65bad9525cf0b0df587bcadc564e6d009e1bd4f7549f2abfac86fb71a7f1d44d`.
- `/tmp/calendar-factor5-cloud-mac-common-verified.json`: release/probeSHA/probe_samples/dataset_checks/date_axis_overlap/gaps all equal. Whole report differs only elapsed_seconds (cloud19.896,Mac5.985); this is not a throughput benchmark.
-12samples,36referenced files verified,0upstream,12gaps. Contracts total26columns; nonempty datasets have no known missing columns. Empty/denied APIs do not prove their columns acquired.

## Per API evidence

|API|Actual evidence|Current audited eligibility|
|---|---|---|
|cn_schedule|4sample_ok,33raw→31distinct;202609/202610 each actual title filter nonempty and all-column equal; legal month requests, publish_date local reader|Eligible sample verification; this audit does not itself enable|
|eco_cal|20260904 date/range50 each equal;20260910 date/range100 each equal but both saturated|Blocked unresolved saturation; equality of capped responses is not completeness|
|idx_anns|1empty_unverified; no dataset/nonempty comparison|Blocked; empty is not permission denial|
|factor_list|1permission_denied|Blocked independent catalog permission|
|factor_value|2sample_ok via verified stockcode000001.SZ,20260904 and same-day range195 each;390raw→195distinct, all source columns and canonical code reader SZ000001 equal|Actual values accessible; current helper blocks factor_catalog_asset_mapping_unverified, not value permission|

Detailed criteria and exact comparisons: `/tmp/calendar-factor5-cloud-review-summary.json`. Parent pure assess evaluated only; main was not called. Do not remove saturation/filter/missing-known-field gates merely because some rows are usable.

## Proposed bounded factor_value supplement (not executed)

Keep the12sample probe and both fixed audits immutable. A separate supplemental report should reference their SHA, fixed release, and the exact195row factor_value observation/object SHA. Verify both source files before selecting a sorted maximum2 real nonempty string factor_name values. Preserve source spelling, source code000001.SZ, and date20260904; no guessed name/asset_type/factor_id/formula.

For each selected name use only documented parameters: factor_name+ts_code+trade_date, then factor_name+ts_code+start_date+end_date for the same day. Maximum4 additional requests, a distinct supplemental epoch/report, existing authority/pipeline.lock/account/API gates,120second common budget and same-epoch terminal reuse. No rerun of old12 requests, no retry of list denial. Freeze selected names plus source provenance on first supplement so rerun cannot expand scope.

Compare each returned response as a full-column multiset against the selected-name subset of the existing complete195row code-only baseline; also compare the new day/range pair. Require nonempty, unsaturated, exact name/code/date, all known fields present even nullable, unknown fields/raw scalar types retained. Historical revisions may make equality fail; retain both versions and an explicit comparison gap instead of overwriting or clipping rows.

If passed, name/source-code filtering may be recorded observed_verified for this slice. Catalog completeness, asset_type mapping, formula/units, historical availability and PIT remain unknown metadata. Existing factor_catalog_asset_mapping_unverified must not be blindly deleted from old audits: a new assessed scope can permit acquisition of proven values while retaining those non-completeness gaps. Current name-driven runtime discovery depends on factor_list/STK; automatic broader planning therefore needs a separately reviewed minimal observed-name provenance path (or existing legal code-only planning), not a fabricated STK catalog row. No runtime/config change proposed by this audit is already applied.

RRG latest status supplied by parent is36done/4pending; this task did not repeat that query or claim full RRG readiness.
