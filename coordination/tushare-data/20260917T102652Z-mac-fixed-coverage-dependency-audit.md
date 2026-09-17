# Tushare fixed-release dependency audit accepted

- Code commit `fa9a0294` updates the offline fixed-release coverage audit. It keeps registered, planned, published and blocked states separate and now recognizes a narrowly reviewed parent-empty dependency.
- Fixed release `data-85972a7c6a0b6c6c14496da44be578d6281e9fa48be38bb2a278af96b95fe4b2` contains 246 registered APIs, 245 planned APIs and 196 APIs with published datasets.
- The only registered API outside the release scope is `p_get`. It requires a `name` observed from the same-epoch `p_list` response. The accepted production snapshot made one real `p_list` request and returned HTTP 200 with no rows, so zero legal `p_get` requests existed. The audit now reports this as `dependency_observed_empty`; actionable unplanned APIs are zero.
- This classification applies only to the fixed release observation. It does not prove historical or future absence, parent-list completeness, or atomic list/member timing. No portfolio name was guessed or copied into the report.
- The 49 planned APIs without a published dataset remain explicit: 37 `permission_denied`, 11 `api_error`, and one `available_empty_only`. These are retained supplier outcomes rather than hidden omissions.
- Validation passed: seven offline unit tests, Python compilation, Ruff, `git diff --check`, and a real audit against the immutable release. The audit did not mutate the archive or make an upstream request.
- The production collector remained active during the audit. The cycle ending `2026-09-17T10:25:35Z` completed with 164 upstream requests, no failed stage, 2,969,587 pending jobs, 193,567 done, 178,579 empty, 1,303 blocked, 5,714 split-pending and document processing healthy.
- No runtime restart is needed because this change only affects the read-only audit command. Full Mac-local historical acquisition continues under `com.quantmind.tushare-archive`.
