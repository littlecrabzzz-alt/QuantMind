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
Entries decode to at most 2 MiB and 8192 projected row objects. SQL rejects an
oversized compressed BLOB before materializing it in Python. Admission rejects
oversized strings, nested values, huge integers and excess unique rows before
extra serialization; original source rows are still returned in full. Projection
version v2 invalidates old entries; stale bytes still count toward the fixed cap.
New admissions spend at most 0.5 seconds per call,
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

## Current full-discovery replay (2026-09-09)

**Hold; do not enable this cache in production based on this review.** The smaller
planning-cadence candidate is independent. On current eed2c88 semantics, default
cache admission did not improve initial repeated discovery. Full warming improves
this isolated fixture, but requires a separate costly preparation not authorized
for production and not supplied by this implementation.

Input fixed release:
`data-8015e6889e3aa1976a9c64047c993569fabd866982f7935dcfe79ebfcbb985b2`.
All 103725 observation hashes were checked; 32790 observations belonging to every
current discovery API selected, with 30909 unique eligible raw objects totaling
1151118880 bytes verified. This is a fixed-release observation union, including
old probes, not a live DB export. The fixture retains ineligible result metadata,
whose raw bodies discovery deliberately does not read. No source calls, credentials,
production database/config writes or restarts occurred.

The test ran locally under Docker Desktop, Linux amd64 emulation on Apple Silicon,
network disabled, `memory=1g`, `memory-swap=1g`, `cpus=.75`. A separate synthetic
176MiB parent was touched in memory. Both metadata and raw files were copied into
isolated container scratch space; no authority/mirror DB was opened for writing.

| Replay mode | Held v1 seconds | Bounded v2 seconds |
| --- | ---: | ---: |
| Exact current baseline | 33.641 | 34.398 |
| Default cold | 35.678 | 35.798 |
| Default warm1/2/3 | 35.171 / 35.293 / 35.612 | not repeated |
| Offline priming (120s admission allowance) | 67.053 | 70.911 |
| Fully primed read | 22.010 | 23.065 |
| Exact baseline after replay | 34.516 | 33.882 |

All 13 rounds return the same identifier JSON SHA-256:
`6a6bcdff88677d71b22895763c73c7f3bd230cd960afc73208dc95f04ab7b546`.
Held warm3 only hit99/25469 cacheable bodies, while primed hit25469; bounded v2
hit25454, keeping15 oversized/high-row-count entries on raw fallback. The warmed
files were58368000 and56807424 bytes, below128MiB. Default0.5s admission remains
unchanged; the120s priming experiment is not a production feature or enable step.

Whole-child cumulative RSS high-water stayed201412608 bytes (v1) and201629696
bytes (v2) across each experiment. Maximum sampled anonymous cgroup memory,
including synthetic parent, was374472704/374689792 bytes. These figures **do not
prove production memory headroom**: both runs reached the1GiB cgroup boundary
(memory.peak1073745920), max events40825/26311, OOM0. Fixture extraction and
reclaimable file cache count toward that peak. The actual Celery lifecycle,
2.3million pending jobs, prior publication allocations and live service conditions
are not simulated. Per-phase sampled memory attribution may lag buffered event
output; only whole-run high-water/global sampled anonymous totals support this
report. Do not interpret no OOM or this synthetic parent as a safe production peak.

The bounded v2 hardening additionally fixes admission serializing arbitrary source
values before checking size, oversized corrupt BLOB materialization, and deeply
nested corrupt JSON fallback. Four new tests fail against the held implementation
(5 subtest failures,1 error) and pass with the guard. All54 relevant tests pass on
Python3.10 (1.216s), including membership additions/revisions/deletions/restores,
stat/version invalidation, request-aware bypass, source failure preservation,
capacity/full/locked/corrupt-cache fallback, and full discovery projection tests.
The frozen v2 replay source predates the final RecursionError catch only; that
fault-path delta is covered by isolated tests and does not change valid-fixture
admission/read behavior. Ruff and diff checks pass.

Evidence directory `/tmp/tushare-discovery-current-review/`; summary `report.json`
SHA-256 `c645287a05aef29fa0e939d0ca9fff62f50f7d95d90c8cd13546c8cb3f1cbd23`.
It includes input, replay/helper and resource-report hashes and exact limitations.
The fixture tar hash is
`0c0c7967ea6a9a2f7315d3dc6cca7d7e57142e040521e17107c9b80a577a4bde`.
`replay.py`/`supervise.py` reproduce held semantics; their `-hardening.py` variants
use frozen v2 source. Replays require a fresh isolated scratch DB each run; do not
point them at the live authority or a Mac service DB. `summarize.py` only reads the
completed outputs. Remaining blocker: no demonstrated safe cold/startup gain and
no measured production RSS margin. This review supplies a safe fallback boundary,
not approval to raise admission or deploy the cache.
