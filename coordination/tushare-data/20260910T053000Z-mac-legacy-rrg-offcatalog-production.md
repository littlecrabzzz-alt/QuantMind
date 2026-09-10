# Tushare legacy Connect, RRG backfill, and catalog production handoff

- Node: Mac coordinator; cloud remains the only formal writer at `/root/data/disk/quantmind/project/data/tushare`.
- Source baseline before this record: `5cd67a1a0197853d1c353981eec61c9e2227119c`, aligned on Mac, GitHub master, and `/root/code/QuantMind`.
- Tests: Python 3.10 `test_tushare*.py`, 922 passed and 5 skipped.

Production facts:

1. The bounded four-call legacy probe succeeded for `moneyflow_hsgt`, two `ggt_daily` request shapes, and `ggt_top10`. Probe report SHA256: `198c728ab4ccdc189c758c1be22d2d447ef375ae0c1740408551acaee12fc380`.
2. `legacy_connect` is enabled for those three APIs from `20141117`, with 12,948 stable daily jobs. The publisher identity defect was repaired without upstream calls; repair receipt SHA256: `a6c622c0075a3bc72c8d915b6473039abec9d65c6c832e438ba66712e9922a42`.
3. The RRG acquisition batch contains 1,718 `fund_div` and 49 `etf_limit` jobs in eight verified shards. Batch manifest SHA256: `3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81`. At the 2026-09-10 13:24 Asia/Shanghai snapshot, one imported `fund_div` job was `empty`; 1,766 imported jobs remained pending.
4. The document worker returned the new download-wave timing fields in two successful real tasks. The refill prototype was rejected because its legal benchmark was 11.908% slower.
5. Eight public catalog APIs and 73 fields are integrated but default off pending bounded live probes. Six public contract gaps, two private reads, two mutations, and one SDK wrapper remain outside runtime registration.
6. A normal production acquisition task completed 360 upstream requests in 86.354 seconds. The latest read-only sample of 1,000 attempts was all HTTP 200 with zero 429 and zero stored errors.
7. Fixed release `data-fa83b240278814d12c3762bae8800bdba976df0879b9db6faf272279e619ed92` is verified on Mac with 551,631 manifest files. It contains the legacy probe closure; normalized rows acquired afterward require the next fixed release and Mac mirror pass.

Do next without waiting for unrelated full-history or document completion:

- verify the next automatic fixed release contains normalized legacy rows and any completed imported RRG task, then run the standard Mac mirror and offline fixed-reader check;
- keep observing `legacy_connect` and imported RRG task-state deltas plus HTTP 429/frequency errors;
- bounded-probe the eight default-off public catalog APIs, preserving permission, saturation, field, and filter gaps before any enablement;
- implement or explicitly classify the six remaining public contract gaps;
- retain RRG `blocked_data` until authoritative industry membership known-at/revisions, ETF mapping, price/limit/dividend closure, and tradeability evidence pass independently.

Do not put the Tushare token, purchase records, order data, or raw secret-bearing environment files into Git or reports.
