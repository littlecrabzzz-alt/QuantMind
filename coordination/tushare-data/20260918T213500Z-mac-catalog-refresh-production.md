# Tushare official catalogue delta in production

- Owner: Mac local archive task.
- Code: master `2a70e2dab6374e019f231b221996eb0845dcb227`; runtime contract SHA matches source.
- Scope: six observed-available APIs enabled locally; `etf_auction` excluded after observed denial.
- Runtime: `com.quantmind.tushare-archive` running, first load, never exited; real planning, requests, and durable results observed.
- Validation: full Tushare suite 1379 passed, 5 skipped; evidence `docs/tushare-catalog-delta-production-20260919.json`.
- Boundaries: no token or raw business rows in Git; full history, revisions, universe, known_at and PIT remain open. Cloud remains research cache only.
- Catalogue watch: master `693bbb29`; daily public identity check is live, first result 270 current and zero changes. Drift never auto-enables unknown APIs and failures do not block acquisition.
- Next: keep local backfill running and align cloud Git without enabling a cloud full writer.
