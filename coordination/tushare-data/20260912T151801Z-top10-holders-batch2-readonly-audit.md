# Tushare top10 holders batch 2 read-only candidate audit

- This audit made no upstream request, read no credential, and did not mutate authority data, configuration, services or Git. It retained no production manifest.
- Rebuilding through the mature selection logic in a stable read-only transaction produced 180 complete sibling pairs and 360 pristine history tasks: 180 `top10_holders` plus 180 `top10_floatholders`, covering `20070101` through `20071231`.
- SH, SZ and BJ each contributed 60 pairs and 120 tasks. Every candidate task was pending with tries zero and no attempts. The eligible pair population was 7,929.
- Against the sole prior batch-1 manifest, task ID, logical key and canonical request overlaps were all zero. Plan-only verified 360 jobs and all five `would_*` fields were false.
- Candidate hashes from the read-only reconstruction were: manifest `db0d648ddeb7848258c3b678b2195a6a33c784eb6513a066296b3cb9375a6ee6`, task IDs `825648b31911dda2742b4da75dc3f0095b0df342e4510c6767dc556b3541bb9a`, logical keys `e3b6bd0a73d395f2d49faf0508d2877bffdb0a5a57e5c052bf20c15e514514cd`, canonical requests `94510d19e71c58b0d9b3062a34731132f8bacbfd76dffdbfa01a9041bf487edd` and pairs `d1ee41c051a22fca61e5a9c649b3731f53a61a7c53f2bfa64464d759aa60fb31`.
- The initial lock command's stdout handle was unavailable. The reconstruction therefore proves candidate content at the stable snapshot but does not constitute a lock-held production admission. The next controlled window must run the formal preparer and compare these hashes before execution.

This candidate does not prove data availability, complete holder history, source revisions, empty-result completeness, known_at/PIT ownership or RRG usability.
