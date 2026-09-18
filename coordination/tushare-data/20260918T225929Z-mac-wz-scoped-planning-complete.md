# Tushare WZ scoped planning correction completed

- Code is on `master` at `6c3c913f54e78578a1baad29ac9ac0f391a86c21` and pushed to `origin/master`.
- With the production `history_start=19900101`, `wz_index` and `gz_index` now use bounded ranges and no longer enqueue the redundant unfiltered request.
- The zero-network migration verified 180 immutable artifacts and continuous terminal coverage through `20260919` before changing one truncated `wz_index` job from `blocked` to `superseded`.
- The supplier result and its one attempt were preserved; history earlier than the configured start remains explicitly unproven.
- The deployed contract SHA matches the repository, and the first restored production cycle completed 771 requests plus 1760 document tasks.
- Production evidence: `docs/tushare-wz-scoped-planning-production-20260919.json`.
