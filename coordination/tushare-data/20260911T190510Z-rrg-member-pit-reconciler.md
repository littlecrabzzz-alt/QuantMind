# Tushare RRG member PIT reconciliation gate

- Squash commit `f439102f` adds an offline, fixed-release-only reconciler for claimed CITIC L1 membership evidence. It writes a new portable evidence bundle atomically and requires a caller-pinned root manifest SHA256 for verification.
- Verification covers every bundled file, the report, Parquet metadata, and row-level authority/history flags. Two independently found promotion paths were fixed before merge; independent replay rejected 2/2 row promotions and 18/18 report-boundary promotions after inventory updates and root re-signing.
- Sixteen focused tests, Ruff formatting/checks, compilation and diff checks passed.
- The real Mac fixed release `data-a21e55cc…` negative control read 6,740 `ci_index_member` rows with zero upstream calls. With no claimed authoritative announcement bundle, it reconciled 0 rows, verified 0 historical `known_at` rows, found 11 overlapping source intervals and returned `blocked_data`; `rrg_ready=false`.
- The run did not access credentials, change QuantDB, or change the RRG case. Current `in_date`, `out_date`, and observation timestamps remain insufficient to prove historical publication-time availability.

Machine evidence: `docs/tushare-rrg-member-pit-reconciler-20260912.evidence.json`.
