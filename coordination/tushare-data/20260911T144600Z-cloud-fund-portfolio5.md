# Tushare fund_portfolio exact batch 5

- The no-revoke drain waited for a 346.724-second ordinary planning-only task to finish, confirmed two stable idle inspections, and stopped the Tushare Worker and Beat without revoking or killing work.
- Preparation took 45.53 seconds across the multi-million-row inventory. It froze 240 current-v2, pristine, leaf-only and cross-epoch unique requests for 240 different funds. Their period-only availability bounds cover 2024-12-31 through 2025-03-31; 13530 eligible signatures remain.
- The manifest pins fixed release f1e, its manifest hash, the authority config, preparer, combined runner, task inventory and semantic signatures. Plan-only made zero authority, credential, upstream, write and publish access. Execution repeated the release, task, leaf and semantic-peer checks inside the exclusive lock before credential access.
- All 240 requests returned HTTP 200 in 64.245 seconds: 134 done and 106 empty, with 3206 retained rows and zero uncertain calls. The configured per-API gate stayed at a conservative 240 rpm with `rate_review_required=true`; the regular 360-request promotion was not applied to this interface.
- SHA256 verification passed for 240 objects, 240 observations and 134 Parquet files: 614 unique references and 1408988 bytes. Worker and Beat are healthy; the cloud volume remains 111690616832 bytes above the 100 GiB reserve. `CURRENT` stays f1e and no fixed release was published.

This expands periodic disclosed holdings that may support an ETF-industry exposure candidate for RRG. It does not establish complete holdings, daily PCF, historical intraday `known_at`, revisions, authoritative ETF-industry mapping or PIT completeness. Machine evidence: `docs/tushare-fund-portfolio-batch5-20260911.evidence.json`.
