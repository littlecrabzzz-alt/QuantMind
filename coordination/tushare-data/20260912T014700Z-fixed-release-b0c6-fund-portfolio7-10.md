# Tushare fixed release b0c6 and fund_portfolio batches 7-10

- The normal publisher completed with Celery SUCCESS and zero upstream calls, atomically producing `data-b0c60c5371a3daa77c3f0108c84f3cdef2f7ddca78650fd0a3d49ce92f784adb`: 117,238 datasets and 860,189 files in a 349,679,239-byte manifest.
- Mac LaunchAgent run 217 downloaded 3,632 incremental files, verified the full release, exited 0 with empty stderr, and atomically switched CURRENT.
- A no-revoke drain let the current acquisition finish before a query-only exporter rebuilt batches 7-10 from live jobs and attempts. The inventory has 960 jobs (734 done, 225 empty, one blocked), 2,655 unique references and 13,907,170 bytes; all authority and Mac SHA256 checks passed.
- The one blocked `possibly_truncated` response contains 2,001 rows and remains excluded from complete coverage. Earlier evidence prose saying 2,000 is corrected from the authority result; it was never replayed.
- The production image read `fund_portfolio` from the Mac fixed release with Docker networking disabled, socket and DNS guards, both token variables empty, and the mirror read-only. It returned three rows and 15 columns with zero upstream calls.
- Worker and Beat were restored healthy, the normal acquisition queue resumed, and API, general worker and research worker remain healthy. Cloud free space is 519,452,131,328 bytes, leaving 412,077,948,928 bytes above the 100 GiB hard reserve.

This makes batches 7-10 available locally without Tushare. Complete fund holdings, daily PCF, historical intraday availability, revisions, PIT membership and an authoritative ETF-industry mapping remain open. Machine evidence: `docs/tushare-fixed-release-b0c6-fund-portfolio7-10-20260912.evidence.json`.
