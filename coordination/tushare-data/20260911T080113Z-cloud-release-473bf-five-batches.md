# Tushare post-5f796b five-batch fixed-release closure

- Normal task `2aa9e7c8-9edb-4752-a364-2a7149f2708b` completed publish-only in 172.032 seconds and atomically created `data-473bf47cb69cb6848bb90e8361572e116ac9db7d29bf2e347af0b88469ad6bf7`. Its 316391184-byte manifest contains 108110 datasets and 807538 files with retained observations included.
- The standard Mac LaunchAgent downloaded 8499 physical files, verified all 807538 manifest entries, exited 0, and atomically switched local `CURRENT` to the same release.
- The five exact batches after `5f796b` contain 1680 tasks and 4854 unique references: 1680 objects, 1680 observations and 1494 Parquet files totaling 57970481 bytes. Authority hashes, manifest metadata, Mac sizes and Mac SHA256 all passed with zero errors.
- A production-image container with no network, empty Token variables and read-only mirror mount read three rows each from `index_daily`, `fund_daily`, `fund_adj`, `fund_share`, `income_vip`, `balancesheet_vip` and `cashflow_vip`; upstream calls remained zero.
- Services are healthy. Cloud free disk is 224113618944 bytes, leaving 116739436544 bytes above the 100 GiB reserve. Machine evidence: `docs/tushare-fixed-release-473bf-five-batches-20260911.evidence.json`.

This closes local availability for `index_daily` batches 4-5, fund price batch 11, financial batch 16 and fund share batch 9. Complete history, revisions, `known_at`, PIT membership, RRG tradability and PCF remain open.
