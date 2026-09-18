# NPR recovery final dual-node handoff

- Mac production validation after the exact NPR recovery completed a normal cycle from `2026-09-18T02:43:02Z` to `02:44:44Z`: 758 real requests, 240 document jobs, no failed stage, about 2.883 million pending jobs, `PRAGMA quick_check=ok`, and about 2.3 TiB free.
- The two retained NPR parents were reused without new parent attempts. Their new descendants close every observed organization/time branch except the evidence-backed `org=国务院`, `2008-03-28 08:00:00` 500-row `has_more=true` terminal cap in each observation epoch.
- Controlled worker drains emitted only Python `resource_tracker` semaphore cleanup warnings; the stderr mtime stopped at 10:40:12 CST and the replacement worker completed a real cycle successfully.
- Cloud verification at code record `0fc37eff` found matching pipeline/contract hashes, `ARCHIVE_RELOCATED.json` under `data/tushare`, active and enabled `tushare-research-cache.timer`, and no cloud full-archive writer. The handoff's final local-app precheck reported connection refused because the Mac sandbox backend was not running; source/Git alignment was verified separately.
