# Tushare fina_mainbz_vip production milestone

- Cloud remained the only formal writer. Source, GitHub and cloud master were aligned at `813fef4f`; the production config enabled `fina_mainbz_vip` from `19900101` without committing credentials.
- The dedicated planner produced 438 pristine tasks: 146 quarter ends from 1990Q1 through 2026Q2, each with `P`, `D` and `I`. A repeat planner pass inserted zero tasks.
- Four exact batches completed all 438 requests in 133.206 runner seconds. Every request returned HTTP 200; no 429 occurred. They retained 1,520,320 rows, 438 raw objects, 438 observations and 299 non-empty Parquet files.
- All referenced files passed independent SHA-256 and size checks. Verified bytes across those references total 287,123,009. Final authority states are 239 blocked terminal completeness gaps, 60 done and 139 empty; no pristine VIP task remains.
- The 239 blocked tasks returned `has_more` or exceeded the operational saturation threshold. The official VIP input contract documents `period` and `type`, not offset/page/limit, so no undocumented pagination was invented. Raw replies remain available for a later supplier-confirmed continuation path.
- Batch 3's first closure validator incorrectly required Parquet for `empty_unverified` responses. The immutable failure file is retained; corrected `batch-3-closure-v2.json` has zero errors and verifies 180 objects, 180 observations and 165 non-empty Parquet files.
- The safe drain stopped Beat, cancelled only the exact Tushare consumer, waited for two stable empty active/reserved inspections, and then stopped the worker without revoke. After the batches, API, Tushare worker and Beat were healthy with restart 0 and OOM false; normal acquisition resumed.
- The current fixed release and Mac mirror are both `data-3eec661f…`; Mac LaunchAgent run 161 exited 0. These VIP batches remain authority-only until the normal fixed publication due at 10:26:06 CST and the following one-way mirror.
- Cloud free space was 229,843,632,128 bytes after the batches, above the 100 GiB hard reserve. The whole-project snapshot timer remains disabled until disk expansion and headroom validation.
- Machine evidence: `docs/tushare-fina-mainbz-vip-production-20260911.evidence.json`. Authority immutable evidence is under `validation/fina-mainbz-vip-batch-20260911/`.
