# Mac ths_member supplier-terminal reassessment start

- Node: Mac archive authority.
- Official source: `https://tushare.pro/document/2?doc_id=261`; latest-members snapshot, 6000 points, 200 calls/minute, inputs `ts_code`/`con_code`, no published row cap.
- Production evidence: 23 retained HTTP 200 JSON responses contain 5,099-5,565 rows, explicit `has_more=false`, complete requested field coverage, unique `con_code` values and `is_new=Y` throughout.
- Root cause: local unverified 5,000-row alarm overrides the supplier terminal flag and creates false `possibly_truncated` blockers.
- Change: for `ths_member` only, accept explicit `has_more=false` over the unverified local alarm when schema/null/value checks pass. Preserve snapshot/history/discovery gaps and never treat this as historical membership coverage.
- Rollout: isolated tests, master merge, cloud code alignment, natural Mac worker boundary, artifact-verified zero-upstream reassessment of the 23 retained jobs, production acceptance.
