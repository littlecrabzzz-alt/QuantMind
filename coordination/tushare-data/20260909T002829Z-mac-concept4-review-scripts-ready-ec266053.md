# concept4 contract review and fixed-release acceptance handoff

- Node: Mac isolated worktree `codex/tushare-text`; read-only review `e1041f2`, integration `03d8d74` / `55848e1`. No repository runtime edits, account requests or production execution.
- Scope: official docs [259](https://tushare.pro/document/2?doc_id=259), [260](https://tushare.pro/document/2?doc_id=260), [261](https://tushare.pro/document/2?doc_id=261), [362](https://tushare.pro/document/2?doc_id=362), independently opened current official pages. Existing catalog body hashes are historical captures, not fresh HTML SHA claims.
- No mandatory contract correction identified: source fields total 6+14+7+13=40. THS daily hidden total_mv/float_mv and member hidden weight/in_date/out_date/is_new all explicitly retained. Latest members have no date/is_new input; first three hidden member fields documented unavailable. Unknown history/cap/discovery gaps remain.
- DC idx_type input required and output default Y; literal values 行业板块/概念板块/地域板块. The example omits required idx_type, a documentation conflict already represented. Do not remove the request/output column or infer entitlement from 6000-point text alone.
- THS reference is one unfiltered snapshot per official instructions; retain all observed exchange/type values, including A/HK/US and the seven documented input types. No market/type loop, no current master as complete historic universe certificate. THS market values CNY versus DC ten-thousand CNY remain unchanged.
- Bounded parent probe: ths_index {}; ths_daily trade_date=20260904; one actual ths_index source code per observed A/HK/US market for ths_member (at most three); dc_index same date per each of three explicit idx_type literals. No fabricated foreign code if absent; absence is unresolved coverage. All 40 reviewed fields explicitly requested.

## Prepared executable scripts

- `/tmp/concept4-cloud-api-accept-20260909.py` SHA256 `86a607df24547571ddc62e17f93a8505788369249b0bbd8d68542532176ff3c8`
- `/tmp/concept4-mac-offline-verify-20260909.py` SHA256 `119ba97a6efa22ebf239961bf8fea5e06329d036fe91c2717c69391c720ca548`

Both require `--release-id data-<sha>`. Cloud defaults `/app`, `/data/tushare`, `/data/tushare/validation/concept-extra-probe.json`; Mac defaults shared code and credential-free mirror, report `/tmp/concept-extra-probe.json`. Override `--report` explicitly if copied elsewhere.

- Both hash selected report/manifest-referenced observation/raw/Parquet files, compare every returned source scalar and unknown source column, preserve source THS/DC/member identifiers, verify raw+request DC identity, independently deduplicate by actual contract keys+row identity and verify read_dataset all columns.
- `dataset_schema` supplies keys and request identity metadata (not assumed Arrow metadata keys). Daily datasets use exact 20260904; snapshots have no date filter, master whole table and members exact requested ts_code set. Fixed concept datasets must match report observations; later CURRENT is never read.
- Explicit missing requested fields must match persisted assessment. Missing optional/hidden fields and non-success capture statuses are recorded in `gaps`, not fabricated as null or used to drop nonempty source rows. DC returned category mismatch or data loss remains a failing integrity assertion.
- Cloud compares authenticated loopback HTTP by code batches (max200 codes/max2000 rows, split batches conservatively); anonymous401 required. Single-code payload above2000 is explicit acceptance bound failure, not success/truncation. No response body/secret printed.
- Mac denies socket connect/DNS and pipeline get_secret. No Tushare account API calls in either script. Global/history/member PIT completeness stays false.
- Validation performed now: Python compilation and both --help passed. No production or mirrored data acceptance executed by this agent. Parent executes against the fixed probe release and retains actual result separately.
