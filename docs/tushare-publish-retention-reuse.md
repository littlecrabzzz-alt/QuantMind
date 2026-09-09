# Reuse the verified predecessor during publication

A publisher already reads and SHA-verifies its fixed predecessor with
`manifest_at`, then inherits the predecessor's complete file inventory. Retaining
that same release previously allocated its whole raw manifest, decoded another
full document, and returned another full inherited-file mapping for the publisher
to merge again.

`Pipeline.publish` now passes its unchanged, same-call predecessor document through
a private `retain_release(..., _verified_predecessor=...)` path. This parameter is
not an external ingestion interface: callers must never provide arbitrary or
mutated documents. Only `data-*` uses the path. Every inherited file's path,
SHA/filename and size metadata is still validated and compared against the
publisher's current inherited inventory. Missing entries, metadata changes or a
changed stat-derived object length retain the old conflict failure rather than
silently publishing a changed expectation. The existing safe
`link_manifest_alias` independently streams and verifies the actual predecessor
and archive bytes with the expected release SHA, pinned directories, O_NOFOLLOW,
stat checks, and the original hardlink/copy behavior. The archive lock and durable
mapping remain in place. No referenced data object is newly claimed verified.

The fast call returns archive additions rather than a second inventory of files
already inherited by the publisher. Prior files, mappings, observations, attempts,
Parquet and document histories are retained; archive conflicts fail closed. The
normal two-argument `retain_release` call, legacy probe handling and recovery
callers retain their original full read/parse/return behavior. The publisher also
releases the temporary returned container before serializing the next manifest.
Manifest schemas, content bytes and release identity are unchanged.

`publish_timing.retention` reports nonnegative stage durations and completed/failed
stages for predecessor stat/reuse or normal read/parse, expected-file validation,
archive-lock wait, archive DB open, record/alias verification, and known mappings.
These diagnostics enter the existing status report only, never immutable content.
They distinguish lock waiting from validation and avoid attributing a whole slow
retention stage to JSON parsing. Existing alias safety code is unchanged.

Validation is limited to offline temporary fixtures and existing tests, including
byte-exact old/new publication, no-op and three generations; latest-only mirror
history; old API/probe compatibility; malformed metadata, symlinks and actual byte
tampering; interruption after alias creation; genuine lock waiting; and temporary
object lifetime before serialization. The large experiment compares separate
processes on 200,000 reference entries without copying any production database.
Its synthetic reference bodies are not asserted to exist: it tests publication
metadata equivalence and resource use, while actual small immutable-file closure
is covered by the normal regression fixtures.

```
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_retain_reuse test_tushare_archive test_tushare_publish_equivalence test_tushare_publish_timing test_tushare_manifest_aliases test_tushare_publish_interval
```

Production deployment is separate. Full expected-file validation, coverage,
partition closure, source inventory scans and final JSON serialization remain.
Mac fixture timing/RSS does not establish cloud cgroup headroom or sustained
publication throughput; the existing producer/worker resource limits are unchanged.
