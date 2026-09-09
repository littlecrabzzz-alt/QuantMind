# Compact discovery cache bounded prototype ready

- Owner remaining_markets; only /tmp prototype/report, no runtime/config/production writes. Follow-up to 20260909T055452Z discovery audit.
- Fixed Mac release data-d4f1d067a8c6f55d0b94783b213471b4905324ba23eeace648ba9b2a377e2e6d; 3000 observation metadata bound, 72 raw samples /38API /9957731 bytes, nonrandom <=3/API. Source SHA verified,55 cacheable+17 request-aware bypass.
- Python3.10 actual identifiers SHA equal in baseline/unique/zlib. Cold ms95.78/247.03/197.64; warm medians95.05/49.07/58.77. Python unique retained23.78MB vs compressed0.608MB; these are sample microbenchmarks, not production throughput.
- Both compact modes passed original9 mutation/restore oracle scenarios. Additional factor pair, tiny budget fallback, cache loss/corruption, request bypass and fresh Pipeline transfer assertions pass; compact.py Ruff passes.
- Worth a bounded compressed-cache candidate, NOT direct rollout: full working-set distribution and real1GiB worker RSS unknown, cold cost increases, process recycle and capped admission affect payoff. Full metadata membership rebuild retained; no rowid frontier/new schema/service.
- Files/reproduce/limits: /tmp/tushare-compact-discovery/report.md and sha256.json. Prototype compact.py SHA 88649ccae9a66ec953d633a1e5f425ff479bf39c00a5f8f87bd224d9fe54be0c; report SHA 660dcb4dbb52cb8f2d520d19c9f385d4e03fa4173048fce182314d3c8602484e. Parent owns all runtime decisions.
