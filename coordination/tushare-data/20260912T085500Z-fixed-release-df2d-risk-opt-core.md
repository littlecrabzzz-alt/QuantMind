# Tushare fixed release df2d risk2, opt daily and core-market closure

- The normal production task `31769420-ae03-472c-8d1b-3599136c413b` completed as `publish_only` with zero upstream calls in 421.159 seconds and atomically published `data-df2dceada681d30b2d4c24c7df5877452c5d27f2479557b493378d7f4ec3f7ff`.
- The release manifest is 445,090,761 bytes with 969,815 files and 134,789 datasets. All 996 reviewed references and 279,629,009 bytes from risk2, opt_daily and core-market batch 2 passed cloud manifest, metadata and physical SHA-256 verification.
- The standard Mac LaunchAgent started automatically, downloaded 15,905 incremental files, verified the full 969,815-file release, exited zero with an empty error log and switched local `CURRENT` to the same release. The same 996 references passed a second local verification.
- With the Mac mirror mounted read-only, both Tushare token variables empty, Docker networking disabled and socket/DNS calls blocked, `daily`, `daily_basic`, `adj_factor`, `stk_limit`, `suspend_d`, `moneyflow` and `opt_daily` each returned three rows with zero upstream calls.
- Publisher completion left the main service, normal Tushare worker, document worker and Beat healthy with restart count zero and no OOM. Beat was then intentionally stopped so the current normal Tushare job can drain before the account-private portfolio maintenance window. QuantDB was not touched.
- Machine evidence: `docs/tushare-fixed-release-df2d-risk-opt-core-20260912.evidence.json`; create-only authority archive: `validation/fixed-release-20260912/df2d-risk2-opt-core2/`.

This closes only the retained reviewed references. Complete history, revisions, intraday `known_at`, PIT semantics, empty-result completeness, the one blocked `daily_basic` normalization and any strategy or RRG claim remain open.
