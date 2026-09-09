# Acquisition discovery timeout review — complete, read-only

Owner: structured_contracts. Reviewed deployed a199571; no shared runtime edits, upstream requests, queue/config/DB writes, restart, resource or timeout changes. Main AGENTS current dual-node/local-cache boundaries followed.

Two actual statuses 15:12:14Z /15:18:54Z fail in **acquire**, after completed planning63.570/66.204s (identifiers56.733/59.706s). Acquisition89.803/86.896s reaches160.116/160.008s total. This corrects the initial shorthand “planning timeout.” 0 duplicate-body hits. Complete bounded read-only metadata+stat scan30,914 results2.082s; no raw body read. Each scan references1,055,655,091 bytes;808,277,402 bytes eligible for held cache and247,377,689 bytes request-aware bypass. Byte fractions are not measured speedup.

1GiB cgroup peak reaches limit with oom0/oom_kill0, .75CPU quota and observed cumulative throttling; not evidence of an OOM kill. Repeated full JSON decoding/projection is the first target; more acquisition consumers cannot bypass240/min shared account allowance.

Held b78953f+08a54f6 remains **not recommended for automatic enable yet**: exact-output/offline safety tests pass, but prior older full-Mac fixture cold adds0.906s and early warming does not demonstrate improvement;12-warm result19.9% is only adjacent Mac comparison, not Linux production proof. Current memory peak and unbounded one-row admission encode mean whole-process bound is unproved. No second speculative runtime implementation added. Minimum next gate is isolated current-source/full-discovery cold/warm replay under1GiB/.75CPU plus membership/revision/deletion/bypass/fallback equality, followed only by parent-reviewed integration. Preserve source/history/policy signatures.

Python3.10 held candidate50 tests pass; deployed-source36 tests pass. Initial two guessed module names were absent; corrected complete commands/logs are in report.

Report: `/tmp/tushare-acquire-timeout-diagnosis-20260909.json` SHA256 `986b2a3004aa252317047f17358ee6ba7e3a894fc31aca36ff1f3879aa7d5af3`. It contains exact safe snapshots, metadata API totals, code locations, commands, evidence hashes, limitations. Helpers `/tmp/tushare-acquire-timeout-readonly.py` and `/tmp/tushare-discovery-metadata-readonly.py`; metadata helper query_only+mode=ro and6s deadline, raw_reads0. No tokens/config secrets returned. Current task complete, no runtime ownership held.
