# Tushare document-index full-stage bounded benchmark

- Recorded at: `2026-09-12T07:13:04Z`.
- Machine/runtime: Mac `Darwin arm64`, Python `3.10.19`; this is not the cloud SSD or production worker runtime.
- Serial source: `5a110c714ae569ebfd1152f064ea4066efd4ae20` in detached worktree `/private/tmp/quantmind-document-index-baseline`.
- Pool2 source: `63499b79da07c8f0db28f2021b5ee74bcb6df309` on `codex/tushare-document-index-pool2` in `/private/tmp/quantmind-document-index-pool2`.
- Benchmark script: `/private/tmp/benchmark_tushare_document_index_stage.py`, 23,605 bytes, SHA256 `80d54a01690622c57a414880a6f7b1993e2b5118597a2676451de73bb898a3c2`.
- Machine report: `/private/tmp/document-index-stage-benchmark-20260912T071238Z.json`, 8,031 bytes, SHA256 `e4c8b5fdab89754d54a4d2fb255d08a581e167924023fd174e6f356fd299c784`, mode `0600`.

## Isolation and fixed fixture

The benchmark read only immutable files from the already verified Mac mirror for release `data-ce43326f62bfc30dccb314a965c8e58533472f6914735e32692cdbec023f60e6`. It did not open or copy a live or authority SQLite database. All SQLite files and generated artifacts were built under an owned `/private/tmp/document-index-stage-benchmark-*` directory and that directory was removed after the four runs. Socket connect and DNS were replaced with failures in measured children, Tushare/token-named environment values were blanked, and no credential config, service, authority path, or upstream endpoint was accessed.

The fixture exercises complete `document_index()` calls, including `_index_setup`, `BEGIN IMMEDIATE`, `_index_original_files`, dirty selection, SQLite reads, result decoding, canonical encoding, `_save` with real per-file fsync and atomic link, cache/dirty updates, descriptor groups, counts, top index, and commit. Its fixed data is:

- 256 of 4,096 state leaves, selected every 16th sorted bucket: 78,153 rows and 32,040,406 encoded source bytes.
- 8 evenly spaced mapping shards with their source rowid buckets preserved: 7,447 rows and 3,184,571 bytes.
- First and last attempt shards with source IDs preserved: 1,958 rows and 1,814,085 bytes.
- 3,000 smallest fixed original files, sorted by bytes/path: 2,428,788 bytes, maximum 988 bytes. Their metadata was preloaded and their real copied files were scanned, matching production's conflict-tolerant existing-file path.

This creates exactly 269 dirty shards: 256 state, 8 mapping, 2 attempt, and 3 file shards, plus 16 state descriptor groups. The template SQLite was 40,456,192 bytes; estimated scratch peak was 117,810,366 bytes against 2,740,552,282,112 free bytes. Controller elapsed time was 6.710 seconds; each child stayed below its 60-second timeout and the total remained far below 10 minutes.

## Full-stage result

Runs alternated `serial, pool2, pool2, serial` to form two opposite-order pairs on the same Mac filesystem.

| Run | Total s | Save critical s | Encode s | Select/fetch s | Original scan s | Cache/control SQL s | Unclassified s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| serial 1 | 0.505676 | 0.124495 | 0.139495 | 0.083563 | 0.031794 | 0.002296 | 0.118311 |
| pool2 1 | 0.497123 | 0.103066 | 0.143757 | 0.089061 | 0.031652 | 0.002110 | 0.121396 |
| pool2 2 | 0.478291 | 0.093528 | 0.144222 | 0.084630 | 0.031470 | 0.001942 | 0.116809 |
| serial 2 | 0.500988 | 0.115423 | 0.143143 | 0.084499 | 0.031147 | 0.002012 | 0.118895 |

The two pair speedups were only `1.017205x` and `1.047455x`. Median serial total was 0.503332 seconds and median pool2 total was 0.487707 seconds: `1.032038x`, or about 3.1% lower wall time. Median save critical time fell from 0.119959 to 0.098297 seconds (`1.220373x`, about 18.1%), but full-stage encoding remained about 28-30%, select/fetch about 17%, original-file scanning about 6%, summary SQL about 1.1%, cache/control SQL below 0.5%, and unclassified Python work about 23-24%. Pool2 made 134 two-save waves and left 18 descriptor/top-index saves on the main thread; it did not change the number of 286 real `_save` calls.

## Equivalence and decision

All four complete calls returned byte-identical results: result metadata was 694,330 bytes with SHA256 `1fa87090082a3db60abec423ba2ea0391063d574b6cb39902652db2876a74ea2`. The complete generated document tree contained 286 immutable JSON objects totaling 37,742,374 bytes; its canonical path/bytes/SHA inventory SHA256 was `3ca0ae27309a93e915e26a649f860e5228527e04875a9a3c5dec1ec06e5d8c8c`. Every run reported 78,153 states, 7,447 mappings, 1,958 attempts, 3,000 original files, 269 rebuilt shards, and 16 rebuilt descriptor shards.

The pool2 candidate does not show a stable material whole-stage gain in this bounded full-path fixture. Keep the serial implementation and do not merge or deploy `63499b79` for performance. This Mac fixture is useful equivalence and component evidence only: it is roughly one tenth of the production changed-state-leaf count, uses small selected original files, and does not reproduce the cloud filesystem, concurrent load, 1.25 million-state database, or the observed 121.373-second production stage. It therefore cannot prove or estimate a cloud deployment benefit.
