# Tushare index_weight descendant batch 1

- The dedicated descendant tools landed on `master` in `01a38228`; nine targeted tests and the combined 21-test index suite passed before production use.
- A fresh authority snapshot selected 180 complete sibling pairs / 360 pristine leaves with no historical task, logical or request overlap. The plan and read-only authority inspection made no credential, upstream or write access.
- The exact runner completed 360 HTTP 200 calls in 47.044 seconds: 180 `empty`, 180 `split_pending`, 289,938 rows. The graph grew from 540 tasks / 360 edges to 900 tasks / 720 edges, adding 360 pristine direct grandchildren.
- Independent closure verified 900 object/observation/parquet references and 26,636,330 bytes by size and SHA with zero errors. Six immutable artifacts are under `validation/index-weight-descendant-batch-20260912/batch-1-*`.
- Worker and Beat were restored with the existing containers and are healthy with restart count zero and no OOM. Normal scheduled acquisition resumed. The batch did not publish or switch CURRENT and waits for normal fixed publication plus Mac exact verification together with index daily batch 19.
- The read-only authority preflight took about 557 seconds. This is a non-blocking performance follow-up; profile stage timings before changing any validation semantics. Deeper descendants, empty-result verification, complete history, revisions, `known_at`, PIT semantics and RRG classification remain open.
