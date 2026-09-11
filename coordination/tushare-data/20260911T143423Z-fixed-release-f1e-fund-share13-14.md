# Fixed release f1e closure for fund_share batches 13 and 14

- The first post-due Celery task completed as `SUCCESS` in 187.175 seconds with zero upstream calls. The normal publish-only path atomically created `data-f1e286712d763e8ce95127c79581bc9eb9d2f83d7c369e81babccc5806734cff`; its 344370817-byte manifest contains 115651 datasets and 851048 files, and its computed SHA256 matches the release ID.
- Mac LaunchAgent run 207 downloaded 6113 incremental files, verified all 851048 manifest entries, emitted no stderr and atomically switched the fixed mirror to f1e.
- The persistent verifier positively checked all 1775 references from fund-share batches 13 and 14. All 12225439 bytes are present with matching metadata and physical SHA256; missing, metadata-error and physical-error counts are zero.
- The production image read `fund_share` through the repository's fixed-release store with a read-only mirror, empty Tushare tokens, Docker network disabled and socket/DNS guards. It returned three rows and nine columns with zero upstream calls.
- An independent review verified all ten authority archives, manifest/task/receipt hashes, zero cross-batch task, semantic and market-date overlap, and both throughput calculations. It found no material issue with promoting regular exact windows back to 360 while retaining lower per-API caps and the 90-second deadline.
- A transient read-only SSH close and one locally expanded empty remote release variable were corrected by bounded, literal-path retries. Neither changed authority or mirror data. Worker, Beat and API are healthy; free disk remains 111709761536 bytes above the 100 GiB reserve.

The two batches are now immutable and usable locally without Tushare Pro. Complete fund-share history, revisions, `known_at` and PIT membership remain open. Machine evidence: `docs/tushare-fixed-release-f1e-fund-share13-14-20260911.evidence.json`.
