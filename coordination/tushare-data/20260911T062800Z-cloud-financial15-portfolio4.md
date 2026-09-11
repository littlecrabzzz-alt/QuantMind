# Tushare financial batch 15 and fund portfolio batch 4

- recorded_at: 2026-09-11T06:28:00Z
- node: cloud authority; Mac remains a fixed-release reader
- branch/head: master at `9ab7be72a209ba2237641de88e2d74f36b8e0046`
- release_at_prepare: `data-e7aca25eb25f6b0618925124fb73c084380859148d6cb0dc647687b33485943e`

Read-only queue, capacity and batch audits ran in parallel and closed their SQLite and SSH processes before the write window. Production writes remained serial because the authority database has one writer and all API families share the 500 rpm account window. The safe drain stopped Beat first, let the active regular task finish naturally, confirmed active and reserved empty twice, then stopped the dedicated Tushare worker without revoke or kill.

Financial batch 15 continued the oldest `20260909` epoch with 120 exact requests for each of `income_vip`, `balancesheet_vip` and `cashflow_vip`. The 360 HTTP 200 calls completed in 49.599 seconds as 351 done and 9 empty, with 705 rows. All 360 objects, 360 observations and 351 Parquet files passed physical SHA256 verification; closure `validation/financial-pit-batch-20260911/batch-15-closure.json` has SHA256 `f36b2910188f5ed6487341e2dbfdfae68fe8565f4c7c667b9f166c28f4e6c69c`.

Fund portfolio batch 4 pinned 240 current-v2, pristine history signatures from 13862 eligible signatures at preparation. All 240 HTTP 200 calls completed in 62.301 seconds as 150 done and 90 empty, with 11763 rows. All 240 objects, 240 observations and 150 Parquet files passed physical SHA256 verification; closure `validation/fund-portfolio-batch-20260911/batch-4-closure.json` has SHA256 `51eeb202862cb4a9729b731a7d5b743534ab8d00022b271774f0173027577827`.

The two batches made 600 certain upstream calls, retained 12468 rows and produced 1701 unique physical references totalling 16688120 bytes. They did not publish or switch `CURRENT`. The worker and Beat were restored healthy. Free disk after closure was 225743339520 bytes, leaving 118369157120 bytes above the 100 GiB reserve. The document worker remains stopped until actual expansion and peak-headroom validation; this does not block structured acquisition.

Next: let the normal publish-only cycle include these artifacts, mirror the new fixed release to Mac, prove all 1701 references by manifest membership, size and SHA256, and rerun offline no-token reads. Continue the oldest financial epoch and remaining pristine fund portfolio signatures in later bounded windows; prepare `index_daily` next. Machine evidence: `docs/tushare-financial-portfolio-batches15-4-20260911.evidence.json`.

## Fixed release closure

- Normal publish-only created `data-5f796b5046adfec0d3cb98bff41b00c098a87b090b9df7a1aeeb40202b0d2019`: 106454 datasets, 799038 files, 312082232-byte manifest, retained observations included.
- The standard Mac LaunchAgent downloaded 6933 physical files, verified all 799038 manifest entries, exited 0, and atomically switched local `CURRENT` to the same release.
- All 1701 references from financial batch 15 and fund portfolio batch 4 were independently checked against manifest metadata and local size/SHA256: 600 objects, 600 observations, 501 Parquet files, 16688120 bytes, zero errors.
- A production-image container with no network, empty Token variables, and read-only mirror mount read three rows each from `fund_portfolio`, `income_vip`, `balancesheet_vip`, and `cashflow_vip`; upstream calls remained zero.
- Machine evidence: `docs/tushare-fixed-release-5f796b-financial-portfolio-20260911.evidence.json`.
