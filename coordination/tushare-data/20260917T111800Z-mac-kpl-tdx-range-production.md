# Mac Tushare KPL and TDX history-range production rollout

- UTC evidence time: 2026-09-17T11:18Z
- Archive owner: Mac, `~/Library/Application Support/QuantMind/tushare`
- Code commits: `b6302c30`, `5f0e154c`, `ece310bd`, `1480966a`
- Full historical synchronization remains active and incomplete.

## Provider contracts and queue behavior

The official `kpl_list` and `tdx_member` documents both expose
`start_date`/`end_date`. Closed historical months now enter the queue as legal
date ranges while the rolling seven-day window remains exact daily capture.

- `kpl_list`: <https://tushare.pro/document/2?doc_id=347>
- `tdx_member`: <https://tushare.pro/document/2?doc_id=377>

A saturated KPL range bisects by date before identifier fanout, preserving the
request tag. A TDX member history range also bisects exhaustively by date; a
saturated exact day can then fan out across the observed TDX board set. The
existing unknown historical board-universe and PIT gaps remain explicit. The
planner no longer eagerly multiplies every old month by every currently
observed board.

## KPL production migration

- Planned and inserted range jobs: 2,205
- Covered and superseded pending daily jobs: 57,417
- Uncovered daily jobs: 0
- Candidate attempts: 0
- Attempts preserved: 388,054
- Result-bearing jobs preserved: 384,720
- Upstream calls: 0
- Receipt: `kpl-daily-retirement-v1.5dec70630e578b630774415c5b2d477fe17900a8d6dc8f62dfb7611e86f66670.json`

The post-commit consistent clone passed `PRAGMA quick_check=ok`. It contained
2,205 active KPL history ranges, zero open KPL history daily roots, and no
active partition parent referencing a retired child. The first post-deployment
real cycle made 202 requests with no failed stage and left about 2.915 million
pending jobs before later planning additions.

## TDX member production migration

The fixed-clone rollback validation covered all 211,266 then-open daily jobs
with 441 monthly roots. The production transaction later covered the larger
live queue atomically:

- Planned and inserted range jobs: 441
- Covered and superseded pending daily jobs: 212,618
- Distinct covered dates: 346
- Bulk daily jobs: 345
- Board-specific daily jobs: 212,273
- Uncovered daily jobs: 0
- Candidate attempts: 0
- Attempts preserved: 390,364
- Result-bearing jobs preserved: 387,030
- Upstream calls: 0
- Receipt: `tdx-member-daily-retirement-v1.4a7ae52d62d4f371d9d4462fffa24ac73ddaf6c92f99fd56abf0b91e991c4d41.json`

The post-commit consistent clone passed `PRAGMA quick_check=ok` in 78.101
seconds. It contained 441 active TDX member history ranges, zero open matching
history daily roots, no retained `history:market_members` planning cursor, and
no active partition parent referencing a retired child. The receipt SHA-256
matches its filename. Repository and deployed runtime hashes matched for the
contracts, registry, and migration script.

## Publication and runtime

- Published release: `data-1242d78fb5b7673d24c426f9aa4cd59949e6ed319057590403f82a6abe4851e4`
- Manifest size: 409,083,393 bytes
- Manifest SHA-256 and `CURRENT.json`: matched
- Manifest coverage: pending 2,707,467; superseded 5,642,076; blocked 1,303;
  quality 196
- Publication status: `published`, failed stage `null`, upstream calls 0
- LaunchAgent: `com.quantmind.tushare-archive`, restored after each controlled
  Tushare-only drain
- First complete post-publication acquisition cycle: 180 real requests in
  100.704 seconds, pending 2,707,293, failed stage `null`; document processing
  handled 240 items with status `ok`
- QuantDB, the research cache, and unrelated services were not stopped or
  reconfigured.

The production transaction had an APFS preimage and post-commit clone. The
temporary validation copies can be removed after the release and first normal
acquisition cycle are accepted. The fixed release does not claim complete
history; the worker continues to acquire the remaining queue locally, and the
cloud remains limited to its research subset/cache.
