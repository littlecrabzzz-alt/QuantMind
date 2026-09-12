# Tushare document-index pool2 candidate handoff

- Recorded at: `2026-09-12T06:59:40Z`.
- Base: `5a110c714ae569ebfd1152f064ea4066efd4ae20`.
- Branch: `codex/tushare-document-index-pool2`.
- Worktree: `/private/tmp/quantmind-document-index-pool2`.
- Candidate commit: `63499b79da07c8f0db28f2021b5ee74bcb6df309` (`perf(tushare): bound document index shard saves`).
- Candidate source SHA256: `backend/shared/tushare_documents.py` = `04885b85434a527ef27b8fe1431e3c4dc280108954084723ab9b9ba578cb54eb`.
- Candidate test SHA256: `scripts/test_tushare_document_buckets.py` = `e7f60aec093b6ec9c527e382aa483ef2c0d73adfdc153e92e1cf828a78bab62c`.

## Scope and preserved semantics

The candidate retains schema 3, the existing sort order and canonical JSON, content-addressed paths, per-file flush/fsync, atomic hard-link publication, cache descriptors, dirty markers, and the enclosing SQLite transaction. It reuses the module's existing `ThreadPoolExecutor` with exactly two workers. Only immutable `(root, kind, bucket, count, payload)` save inputs leave the main thread. SQLite reads, JSON preparation, cache updates, and dirty-row deletes stay on the main thread and in the original order.

Dirty leaves are processed in bounded waves of two. Both nonempty `_save` calls complete before either leaf's cache or dirty state is changed. Zero dirty work and waves with fewer than two nonempty saves do not create a pool. Pool creation is lazy and no configuration, dependency, schema, manifest field, or reader behavior was added.

## Verification

- Python 3.10 focused module: 10 tests passed.
- Python 3.10 related publication/document suite: 142 tests passed in 5.259 seconds.
- Ruff check and format check passed for both changed files.
- `py_compile` and `git diff --check` passed.
- The added tests prove pool2 and serial full publication produce the same release ID, exact manifest bytes, and API response bytes; SQLite calls remain on the main thread; no-op starts no pool; failure in either wave position preserves `CURRENT`, cache, and dirty state, leaves no temporary file, and succeeds on retry with serial-equivalent release/manifest output.

## Performance boundary and handoff

The earlier fixed-leaf microbenchmark measured about 4 ms per leaf in serial `_save` and a 1.711 median pool2 speedup. Production `document_index` averaged 46.83 ms per changed state leaf across its full 121.373-second stage. The microbenchmark excluded SQLite selection, JSON encoding, cache SQL, original-file scanning, and other stage work, so it neither explains the main production cost nor establishes a whole-stage speedup.

This is a code-review candidate for the next integration round. It has not been merged, deployed, run against authority, or used to change services. A separately authorized gray release should compare whole `document_index` timing and release bytes before production adoption; if the full stage has no stable material improvement, keep the serial implementation.
