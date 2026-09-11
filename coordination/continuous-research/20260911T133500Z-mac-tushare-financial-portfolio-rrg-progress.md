# Tushare financial, fund portfolio and RRG progress

- recorded_at: 2026-09-11T13:35:00+08:00
- updated_at: 2026-09-11T14:04:02+08:00
- node: Mac development checkout; cloud remains the only data authority
- branch: master
- head_before_this_evidence_update: 58fea35b871adbf1fe5611c6cb673e4e3683f5bb
- fixed_release_verified_on_mac: data-e7aca25eb25f6b0618925124fb73c084380859148d6cb0dc647687b33485943e
- fixed_release_files: 792104
- fixed_release_datasets: 105523
- offline_reader_acceptance: passed for fund_portfolio, income_vip, balancesheet_vip and cashflow_vip with network disabled, empty tokens and a read-only mirror

## Production results published and mirrored

- Financial batch 14: epoch 20260909, 360 exact calls, 345 done, 15 empty, 733 rows, 360 objects, 360 observations and 345 Parquet files verified. Closure SHA256: `35ccda7f1b47d008cd1bde2cf65bd53fc999271136992d9be2811350b91befda`.
- Fund portfolio batch 2 plus exact tail: 320 unique request signatures, 320 exact calls, 227 done, 93 empty, 33749 rows, 320 objects, 320 observations and 227 Parquet files verified. Closure SHA256: `01d7bc10d5b828d348d717324030405d15d35bbe19dd4df9e86e7014e1af6e29`.
- The normal publish-only cycle produced `data-e7aca25eb25f6b0618925124fb73c084380859148d6cb0dc647687b33485943e`; the Mac LaunchAgent downloaded 7038 files and verified all 792104 fixed-release references before switching local `CURRENT`.
- The 680 objects, 680 observations and 572 Parquet files referenced by the two exact batches are all present in the fixed-release manifest and Mac mirror. All 1932 manifest entries, physical sizes and SHA256 values match; the included batch payload is 19945691 bytes.
- Worker and Beat were restored after each exclusive write window and were healthy after the membership export.

## Durable blockers and next actions

- Production financial history is stored in date epochs 20260909, 20260910 and 20260911; there are no literal `history` financial jobs. Continue from the oldest date epoch and preserve cross-epoch attempt/terminal dedup.
- Fund portfolio has 15674 never-attempted request signatures remaining after this batch. Its 7 quality signatures already retain complete responses and Parquet with null-value quality flags; keep that state until consumers explicitly handle it. Its 6 blocked signatures retain saturated responses of at least 2000 rows and need a provable partition plan. Do not replay the original requests.
- The 240 rpm fund portfolio limit shares an account-level rolling window with regular acquisition. Use a smaller budget or a fresh rate window; never assume 360 requests fit in 90 seconds.
- RRG forward-only vintages remain `blocked_data` for the 20260831 signal. Historical release requires authoritative Citic change archives with publication/known-at, revision and withdrawal evidence.
- Continue bounded financial history and never-attempted fund portfolio batches from their persisted queues. Publish only through the normal cycle, then prove exact membership in each newly mirrored fixed release.

## Evidence

- `docs/tushare-financial-pit-batch14-20260911.evidence.json`
- `docs/tushare-fund-portfolio-production-20260911.evidence.json`
- `docs/tushare-release-476b-offline-20260911.evidence.json`
- `docs/tushare-fixed-release-e7aca-financial-portfolio-20260911.evidence.json`
