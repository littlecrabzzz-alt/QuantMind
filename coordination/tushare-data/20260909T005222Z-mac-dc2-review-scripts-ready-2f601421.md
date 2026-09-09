# DC2 independent review and seven-probe acceptance handoff

Mac isolated `codex/tushare-text`, reviewed candidate523d32b/94d66a1. No shared runtime edits, production writes or Tushare account API calls. Public official docs only; temporary files owned by this agent.

[363 official](https://tushare.pro/document/2?doc_id=363) matches dc_member five optional inputs ts_code/con_code/trade_date/start_date/end_date, four default-visible source fields; documented history starts20241220, row cap5000,6000points. Historical date does not prove known_at or membership effective intervals/weights.

[382 official](https://tushare.pro/document/2?doc_id=382) matches dc_daily five optional inputs ts_code/trade_date/start_date/end_date/idx_type, thirteen default-visible outputs. Date formatYYYYMMDD; history says2020, so20200101 is planning floor only. Cap2000,6000points; vol shares, amount CNY. idx_type three Chinese category values are documented, but returned category literal mapping is not demonstrated by the page. Preserve separate request identity. No documented hidden fields, no offset/limit or endpoint frequency claims. No mandatory correction identified; account/filter/earliest actual row remain unprobed by this audit.

Fixed Mac selection independently verifies data-e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce manifest and three referenced dc_index observation/raw SHA. Date20260904: industry BK1230.DC航海装备Ⅱ10+0; concept BK0805.DC钛白粉概念3+7; region BK0162.DC宁夏板块7+8. Selection picks smallest up+down10..100, not a membership count/completeness claim. Exact source rows/references in JSON below.

- `/tmp/dc2-cloud-api-accept-20260909.py` SHA256 `ea7801c2cc69e02c5270dae4e4899507bfdd72a9b1fcd97420dfb340a0f8f9f6`
- `/tmp/dc2-mac-offline-verify-20260909.py` SHA256 `ea60730a8e554e7de02317e3e0d080ede01e73ae3f621bbb916274c1ef271028`
- `/tmp/dc-extra-selected-codes-20260909.json` SHA256 `96b262de56b760d7342a8327f4a47338e24bb7b186e3dc2332fea097dddf923f`

Scripts require --release-id, optional --repo/--root/--report/--output. Default cloud report/data path `/data/tushare/validation/dc-extra-probe.json`; Mac report `/tmp/dc-extra-probe.json`. Seven exact requests: all-board member one + the three selected codes, and all-board daily per threeidx_type, all20260904. Fixed release DC partitions must belong to these report observations; later CURRENT ignored.

Both scripts SHA-check obs/raw/Parquet, verify all17 requested source fields plus unknown columns and per-row原码, preserve DC daily category and request identity, independently deduplicate natural keys+row identity by fetched_at/observation. Wide/narrow exact-source overlaps reported separately; differing source revisions survive. possibly_truncated rows remain included and capture status retained as gap, no inferred upstream completeness. Daily actualcategory values/counts per requestedidx_type reported; null/ambiguous/non-one-to-one observed mappings remain explicit gap, no copied value/fabricated category.

Cloud adds loopback anonymous401 and authenticated all-column comparison. Initial ts_code batching; if one stored member board exceeds2000 rows, partition the entire fixed member query by legal con_code lists (<=200 codes, adaptive <=2000 rows). This is local query pagination of retained rows, not additional supplier requests/universe proof; all cross-board rows per con_code are included so none lost/duplicated. Mac denies socket connect/DNS/get_secret. Dataset keys read from dataset_schema.

Validation now: both py_compile and --help passed. Synthetic2002 member rows with one2001-row board plus a shared member in another board pass11 con_code HTTP batches, all rows preserved, no network (`/tmp/test-dc2-http-partitions-20260909.py`, `/tmp/dc2-http-partition-synthetic-result.json`). Actual seven-probe fixed-release audit not executed here; parent executes after publishing/mirroring. No full-history or PIT completion claim.
