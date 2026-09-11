# Tushare fixed release 76b0 local closure

- Normal publisher task `99f8cde8-d7cd-4089-964c-6efcb1dba34e` completed with Celery SUCCESS in 251.607 seconds as publish-only with requests 0. The publication window contained no HTTP, API or timeout log entries.
- Release `data-76b031903c08e660d869cb8ef8218dab6cca8bd23cc8811adcf55adbdd8d0898` has a 382,645,369-byte hash-matching manifest, 119,381 datasets, 875,779 files and retained observations.
- A live terminal inventory covers 960 jobs, 144,889 rows and 2,665 unique references totaling 25,527,089 bytes across fund_portfolio batch 15, index_daily batch 10 and fund_share batch 15.
- Old a447 omitted all 2,665 references as expected. New 76b0 contains all references with zero metadata or physical checksum errors in the cloud and Mac mirrors.
- The standard mirror command used by the installed LaunchAgent downloaded 6,584 files, verified all 875,779 files and switched Mac CURRENT at 05:01:22 CST. LaunchAgent run 229 returned already_running while that command held the mirror lock.
- Empty tokens plus socket and DNS guards still allowed three-row fixed-release reads from all three APIs with zero upstream calls.

The release makes these exact retained batches locally usable. It does not establish complete history, revisions, intraday `known_at`, PIT semantics or authoritative ETF-industry mapping. Machine evidence: `docs/tushare-fixed-release-76b0-round-20260912.evidence.json`.
