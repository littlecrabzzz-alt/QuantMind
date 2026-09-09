# Derived identifier cache candidate

`TUSHARE_DISCOVERY_CACHE=1` opts the acquisition process into a local derived
`<tushare root>/discovery-cache.sqlite`. The default remains disabled. This file
is not authoritative, is not published or mirrored, and may be discarded without
losing data. Include `tushare_discovery_cache.py` in the installed client module
copy list when integrating this candidate.

Every call still reads the complete existing jobs/attempts result union, stats
all eligible immutable objects, and rebuilds every discovery family. New, revised,
deleted, restored, historical and retired-source memberships therefore take effect
through the existing scan. The key includes the projection version, column set,
API/status/format, object SHA, path and full device/inode/size/mtime/ctime identity.
Request-identity-dependent APIs retain their existing raw-read bypass. Complete
projected rows retain cross-column associations; only duplicate projection rows
are folded inside this derived cache. Source/observation/Parquet data are unchanged.

The SQLite file is capped at 128 MiB with a 256 KiB page cache and disabled mmap.
Entries decode to at most 2 MiB. New admissions spend at most 0.5 seconds per call,
plus the last bounded entry; the scan and any uncached raw reads always continue.
This is gradual warming across Pipeline instances and worker recycling, not an
extra source-request budget. Small individual disposable transactions use an
in-memory rollback journal and synchronous OFF; crashes may invalidate derived
cache state, never authoritative data. Full, busy, damaged, foreign-schema or
symlink cache files cause raw fallback. Stale entries are harmless and count toward
the fixed cap; this first candidate does not add eviction or a maintenance job.

Existing `identifier_timing` keys remain unchanged when disabled. Enabled reports
add `disk_cache` hit/miss/admission/error/size metrics; `body_reads` excludes actual
cache hits. Initialization/metadata enumeration/stat/SQL costs remain. A bad cache
is disabled for that invocation and may continue to fall back until discarded;
this is deliberately not an automatic repair of arbitrary SQLite files.

Validation is offline, temporary metadata databases plus SHA-verified immutable
Mac mirror objects. Run:

```
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_discovery_cache test_tushare_discovery_projection test_tushare_discovery_timing
```

The full fixed-mirror experiment and its performance limits are recorded in the
shared coordination handoff. Mac timings are not production speedup estimates.
No configuration, rate limit, scheduler state, source refresh or production service
is changed by this candidate.
