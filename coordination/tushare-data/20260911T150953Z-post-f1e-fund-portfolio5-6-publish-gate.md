# Tushare post-f1e fund_portfolio batches 5/6 publication gate

- After a no-revoke drain, the query-only exporter held the authority lock and rebuilt the exact terminal reference inventory for batches 5 and 6 from live jobs and attempts.
- The two batches contain 480 first-attempt HTTP 200 jobs: 324 done and 156 empty, with 29249 rows. Their task IDs, request signatures and physical references are pairwise disjoint.
- The inventory contains 480 objects, 480 observations and 324 Parquet files: 1284 unique references and 6065292 bytes. Every authority file was read and SHA256 verified. Inventory SHA256 is `68778b1721292e579645435409d7ca9c17d1ecc561d32cfe96ad02096b4fed3a`.
- An independent read-only audit repeated the live jobs/attempts checks and all 1284 file hashes under the authority lock and found no issue.
- Mac remains on fixed release f1e. The persistent exact-release verifier returned the expected exit 2 because all 1284 references are absent from the old manifest; metadata and local physical errors are both zero.
- Worker and Beat are healthy. The next normal publisher is due after 2026-09-11 23:23:47 CST; publication is not bypassed or forced early.

This gate proves cloud retention and the expected pre-publication local absence for these exact batches. It does not prove complete fund holdings, daily PCF, historical intraday `known_at`, revisions, authoritative ETF-industry mapping or PIT completeness. Machine evidence: `docs/tushare-post-f1e-fund-portfolio5-6-publish-gate-20260911.evidence.json`.
