# Discovery caching bounded diagnosis ready

- Owner: remaining_markets. Read-only source/saved timing plus isolated `/tmp` fixtures; no runtime, authoritative data, provider call, queue, CURRENT or deployment changes. No new implementation commit; parent may retain this unique coordination note.
- Saved production sample 2026-09-09 04:25:47Z, task d7ac29bf: 184 requests, tick 137.667s, planning 28.007s, identifiers 23.226s; 15003 result records, 13934 raw body reads, 2058 request-aware bypasses, zero same-call duplicate hits. Discovery was 16.87% of this tick, not a guaranteed throughput gain. These are saved observations, not a new live measurement or controlled before/after comparison.
- Hot path: full jobs.result UNION attempts.result, parse metadata/stat, raw read_bytes/json.loads then field projection and per-row set merge. Local seen dies each invocation; Pipeline is recreated each tick. Timing does not yet separate SQL/stat/decode/merge.
- Normal capture uses SHA objects and exclusive observation creation; normal attempts append but jobs.result mutates. SQL schema does not prohibit update/delete/restore, and legacy jobs may lack attempts. CURRENT rollback differs from live DB rollback. A count/max-rowid cursor can miss replacement; fixture proves it. Never freeze a monotonically growing aggregate after DB/source removal.
- Minimum next candidate: keep complete current source metadata membership scan, memoize unchanged body projection/contribution, rebuild IDs from current membership. Namespace/version/stat keys and conservative request-identity bypass; retain factor name+asset row correlation. Prefer compact distinct contributions, not full raw rows. A bounded process memo must first fit the 1 GiB worker budget; sequential scans can defeat undersized LRU. Persistent sidecar/new schema/service is not yet warranted.
- Python 3.10 isolated actual identifiers oracle: 24 bodies, 400 rows x 80 columns, 5488287 bytes. Cold 24 reads, warm 0; append and legacy job add only 1 read each. Revision/removal/file replacement/extractor version/DB restore all produced identical identifier SHA to baseline. Request-aware bypass and max-rowid counterexample passed. This is a mechanism proof, not production benchmarking; no persistence/eviction protocol is implemented.

Artifacts: `/tmp/tushare-discovery-cache-audit/{recommendation.md,production-evidence.json,fixture.py,fixture-report.json,sha256.json}`.

Reproduce:
```
/tmp/quantmind-calendar-factor-test310/bin/python -B /tmp/tushare-discovery-cache-audit/fixture.py --repo /Users/lizeyu/.codex/worktrees/quantmind-tushare-calendar-factor-runtime --output /tmp/tushare-discovery-cache-audit/fixture-report-repeat.json
```
Fixed runtime source dcb2c3e / pipeline SHA 887278da7e2ab1725e5f36ace4e883aaa55a99fe49b3cb356222ac15e9e27d5d. Fixture SHA 063a0c889e6ccfcc021843b19a93678c1eca98b1cef06339a3d7a8835399e898. Original report SHA c9ee382cee1d63c9739b5bd5d29612fed9813c3d0a2d917cf9c53c71abc82cec. Recommendation SHA ddfdd359fca1fa1c2f671786d35a1ac6497de1cf845ab9fa8ce71e2f473c0b8b.

Next acceptance should compare same-source ID SHA, cache size/RSS, hit/miss/eviction, SQL/stat/decode/merge and whole-tick timing with unchanged gates/request budget. Preserve all existing source/PIT/coverage gaps and publication SHA checks.
