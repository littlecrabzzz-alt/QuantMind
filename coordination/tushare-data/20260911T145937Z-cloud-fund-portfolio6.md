# Tushare fund_portfolio exact batch 6

- The no-revoke drain stopped Beat first, waited for the active ordinary task to finish, confirmed two stable idle inspections and stopped the Tushare Worker without revocation or process killing.
- Preparation took 40.91 seconds across the multi-million-row inventory. It froze 240 current-v2, pristine, leaf-only and cross-epoch unique requests for 240 different funds. Their period-only availability bounds cover 2019-12-31 through 2024-12-31; 13290 eligible signatures remained at preparation time.
- The manifest pins fixed release f1e, its manifest hash, the authority config, preparer, combined runner, task inventory and semantic signatures. It has zero task or request-signature overlap with batch 5. Plan-only made zero authority, credential, upstream, write and publish access.
- All 240 requests returned HTTP 200 in 63.334 seconds: 190 done and 50 empty, with 26043 retained rows and zero uncertain calls. The observed request interval is 227.37 rpm, or 186.26 rpm including container wall time, below the conservative 240 rpm interface gate.
- SHA256 verification passed for 240 objects, 240 observations and 190 Parquet files: 670 unique references and 4656304 bytes. Worker and Beat are healthy; the cloud volume remains 111660396544 bytes above the 100 GiB reserve. `CURRENT` stays f1e and no fixed release was published.
- A read-only performance review traced preparation time to a full jobs-table scan that parses JSON for millions of records. The existing `(epoch, api_name)` expression index can support a later semantics-preserving query rewrite, so no new production index is proposed yet.

This expands periodic disclosed holdings that may support an ETF-industry exposure candidate for RRG. It does not establish complete holdings, daily PCF, historical intraday `known_at`, revisions, authoritative ETF-industry mapping or PIT completeness. Machine evidence: `docs/tushare-fund-portfolio-batch6-20260911.evidence.json`.
