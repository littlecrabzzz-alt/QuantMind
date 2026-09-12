# Tushare publisher document-index read-only audit

- Audit time: `2026-09-12T06:48:32Z`; Mac and cloud source hashes match for `tushare_documents.py`, `tushare_pipeline.py`, and both document-index test modules. No live SQLite scan, service action, upstream call, credential access, code edit, or profile was performed.
- Production receipt: publisher task `23d8b20d-27ef-4abd-8a51-1dbb981096b2` completed `SUCCESS`/`publish_only`, `requests=0`, in 338.184 seconds. Its measured publish body was 330.656 seconds; `document_index` was 121.373 seconds, `coverage_and_closure` 92.925 seconds, and manifest serialization 39.935 seconds. Release `data-ce43326f62bfc30dccb314a965c8e58533472f6914735e32692cdbec023f60e6` has a 421,257,077-byte manifest.

## Fixed-release evidence

The previous `85ff` document index contains 1,245,569 states, 1,622,596 mappings, 50,633 attempts, and 46,893 original files. The `ce43` index contains 1,249,609 states, 1,629,447 mappings, 51,958 attempts, and 48,177 original files. Both are immutable schema-3 indexes.

An exact descriptor comparison between those two fixed indexes found:

- 4,040 added states caused 2,592 of 4,096 state leaves (63.28%) and all 16 descriptor groups to change.
- The changed leaves contain 793,259 current rows and 327,052,445 encoded bytes: 196.35 rewritten rows and about 80,954 encoded bytes per added state.
- Only 8 mapping, 2 attempt, and 3 file shards changed, totaling 5,859,025 encoded bytes. The new compact top index is 414,323 bytes.
- `_index_original_files` still walks 48,177 attachment/extracted entries and attempts conflict-tolerant registration, so it merits a separate sub-timing. It cannot explain the observed 327 MB state rewrite and thousands of durable shard saves by itself.

The call chain is `Pipeline.publish()` -> measured `document_index` -> `tushare_documents.document_index()`. Each dirty leaf is selected and encoded in sorted order, then `_save()` creates a temporary file, writes it, calls `fsync`, and atomically links the content-addressed result before the cache row is updated and the dirty marker is deleted. The observed stage averages 46.83 ms per changed state leaf, including selection/JSON/cache work. That is consistent with thousands of serialized durable saves, but it is not a per-substage profile.

Existing history is retained: the `ce43` manifest still contains the previous `85ff` document index at `documents/9586ebbc3772a320abdf6fdad3d69e9babf2df6516d75d8ea0762eb9904c0e78.json` with its exact 411,958 bytes and SHA. Archive recovery is `complete`, has 0 open gaps, 65,830 files, and 393 release mappings, including the exact `85ff` archived manifest. A layout change must therefore preserve old readers and immutable paths rather than rewrite history.

## Smallest optimization candidate

Keep schema 3, the 3-hex state leaves, canonical JSON, per-file `fsync`, atomic create-only links, SQLite transaction, and manifest format unchanged. Reuse the module's existing `ThreadPoolExecutor` and save dirty state leaves in bounded waves of two. The main thread must continue to perform every SQLite query/cache update/dirty deletion in the current sorted order; worker threads receive immutable `(payload, metadata)` values and call only `_save()`. Resolve each two-item wave in input order before updating SQLite and before starting the next wave.

This candidate targets the evidenced 2,592 durable saves while avoiding a schema migration, larger reader shards, new dependencies, unbounded memory, or weaker crash durability. Two workers match the module's existing bounded concurrency practice. Its benefit is not yet proven: if finite sampling shows no material wall-time reduction, do not merge it. Do not combine it initially with `_index_original_files` caching, prefix changes, cadence changes, or deferred document visibility.

## Required equivalence and failure checks

1. Against the current serial implementation on the same synthetic database, require byte-identical leaf payloads, descriptor blocks, top index, `files` metadata, full manifest, release ID, counts, ordering, and old/new API pages for a distributed append plus state updates.
2. Assert SQLite is accessed only by the main thread and cache/dirty rows are changed only after both saves in a wave have completed and fsynced.
3. Inject failure in each worker position. The document transaction must roll back, `CURRENT` must not advance, dirty rows must remain, `.document-*` temporaries must be absent, and retry must produce the same bytes/release. Content-addressed orphan outputs remain acceptable under the existing recovery contract.
4. Preserve existing no-op behavior: zero dirty shards submits no worker job, creates no files, and reuses the index path. Keep current symlink/conflict/corrupt-cache, bounded rewrite, interruption, legacy schema, publish timing, and publish equivalence tests green.
5. Add explicit timing counters for `original_file_scan`, state `select_encode`, state `save_wait`, cache SQL, dirty leaf count/rows/bytes, and maximum in-flight payload bytes. These counters are observational and must not enter release content.

If a new measurement is needed before implementation, use 256 representative immutable state-leaf payloads from `ce43`, copying only their bytes into separate empty temporary roots on the same SSD outside authority. Alternate serial and two-worker `_save` runs three times, cap each run at 60 seconds and total copied data below 256 MiB, and report median/p95 save wall time plus bytes. Keep network disabled and tokens empty. Do not open `documents.sqlite`; proceed to a copied-database benchmark only if this bounded save sample is inconclusive.

## Bounded `_save` profile result

The proposed finite sample was run at `2026-09-12T06:50Z` through the deployed `_save()` implementation, with a network namespace, empty Token variables, no SQLite opens, and temporary roots on the same device outside authority. The sample selected every 16th bucket from the sorted `ce43` leaf descriptors: 256 fixed payloads totaling 32,040,406 bytes. Six fresh-root writes totaled 192,242,436 bytes, below the 256 MiB cap. Every run completed in under 1.02 seconds, well inside its independent 60-second child-process deadline.

The alternating order was serial/pool2, pool2/serial, serial/pool2. Serial elapsed times were 1.0109, 0.9839, and 0.9407 seconds; pool2 times were 0.6026, 0.5752, and 0.5078 seconds. The paired serial-over-pool2 ratios were 1.677, 1.711, and 1.853; median speedup was 1.711. Pool2 was faster in every pair and passed the predeclared stable-gain rule of at least 1.20 median speedup.

All six runs made exactly 256 real `fsync` calls. Serial used one fsync thread and pool2 used two; summed fsync wait was 0.806–0.953 seconds while pool2 wall time was 0.508–0.603 seconds, directly showing overlap without removing durability calls. All 256 output bytes and SHA256 values passed every run, returned metadata had one common SHA256 (`58c68847798973680d32255c949eb03c10659f67fb623890ec3a01e1db2c1645`), and temporary residue was zero.

The create-only report is `validation/source-semantics-20260912/document-index-save-benchmark.json`, 78,185 bytes, SHA256 `0e4fef75d219ad2c6746a3d349075270ad5071df4a3e84dd616fb25dbbfedf4c`. The owned benchmark directories were removed, `CURRENT` remained `ce43`, and the deployed source SHA remained `a11c43147b7e684af82d600b83ef4bed776aa8400f32dfe6d3112fb4d91554ed`.

Decision: the bounded result supports implementing the two-item `_save` wave candidate and running the equivalence/failure suite above. It does not identify the main cause of the 121-second stage: the isolated serial result is about 4 ms per sampled leaf, while production `document_index` averaged 46.83 ms per changed state leaf and also includes SQLite selection, JSON encoding, cache updates, and original-file scanning. The candidate therefore optimizes only the measured `_save` substage. Retain serial production behavior until the candidate passes byte-identical full-publish tests and a separately authorized gray release with whole-stage timing.
