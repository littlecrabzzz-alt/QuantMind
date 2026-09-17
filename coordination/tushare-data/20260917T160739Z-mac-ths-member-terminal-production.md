# Mac ths_member supplier-terminal production acceptance

- Official source: `https://tushare.pro/document/2?doc_id=261`; latest members only, 6000 points, 200 calls/minute, no published row cap.
- Root cause: an unverified local 5,000-row alarm overrode explicit supplier `has_more=false`, leaving 23 complete current-snapshot responses in `possibly_truncated`.
- Implementation: commit `3fb991aaf6287112d45a922c94ef07150acadc4e` accepts supplier-terminal evidence for `ths_member` only when missing-field, disallowed-null and positive-value checks all pass. `has_more=true` and malformed responses remain blocked.
- Tests: 32 related contract, pipeline, intake and field-coverage tests passed. Python compilation, Ruff and `git diff --check` passed.
- Cloud: head aligned to `3fb991aaf6287112d45a922c94ef07150acadc4e`; dual-node source digest `c9bcbf4d0a45142644ff24b28671a7c3168388d296055712e3f4585b2432516c`. Cloud full writer remains disabled; the research-cache timer was not changed.
- Evidence before reassessment: 23 HTTP 200 complete JSON responses, 5,099-5,565 rows, explicit `has_more=false`, complete requested-field coverage, zero duplicate `con_code` values inside each response, and `is_new=Y` for every retained row.
- Reassessment: every object, observation and Parquet checksum passed. All 23 jobs were promoted from blocked to done with `supplier_terminal_evidence=has_more_false_over_unverified_local_alarm`; source attempts and artifacts were unchanged; upstream calls=0.
- Receipt: `ths-member-terminal-reassessment-v1.20031a7e615e287070fadaaf81e9504a1c5e7857fae9798deb6ba79b371a63d8.json` in the private Mac archive. It contains no credential.
- Queue after acceptance: `ths_member` blocked=0, quality=0, terminal-evidence jobs=23. Runtime/source hashes match and native writer PID 99070 is running.
- Coverage boundary: this accepts each supplier-declared terminal latest-members snapshot. It does not prove a closed THS index universe and does not invent unavailable historical membership, weight, in-date or out-date data.
- Disk: about 2.3 TiB free; no NAS warning.
