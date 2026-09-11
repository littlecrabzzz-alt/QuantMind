# Tushare financial, fund portfolio and RRG progress

- recorded_at: 2026-09-11T13:35:00+08:00
- node: Mac development checkout; cloud remains the only data authority
- branch: master
- head: ee850c894b656a8c90789045819a99ae7beebf60
- fixed_release_verified_on_mac: data-476b325b6cf6eb83994abdfdb2249a4d40645b24ec1bcc8bfd1789f052a849a7
- fixed_release_files: 785065
- fixed_release_datasets: 104497
- offline_reader_acceptance: passed for index_weight, fund_daily, fund_adj, irm_qa_sh, irm_qa_sz, income_vip, balancesheet_vip and cashflow_vip with network disabled, empty tokens and a read-only mirror

## Production results waiting for the next fixed release

- Financial batch 14: epoch 20260909, 360 exact calls, 345 done, 15 empty, 733 rows, 360 objects, 360 observations and 345 Parquet files verified. Closure SHA256: `35ccda7f1b47d008cd1bde2cf65bd53fc999271136992d9be2811350b91befda`.
- Fund portfolio batch 2 plus exact tail: 320 unique request signatures, 320 exact calls, 227 done, 93 empty, 33749 rows, 320 objects, 320 observations and 227 Parquet files verified. Closure SHA256: `01d7bc10d5b828d348d717324030405d15d35bbe19dd4df9e86e7014e1af6e29`.
- Worker and Beat were restored after each exclusive write window. No exact batch published or switched `CURRENT`.

## Durable blockers and next actions

- Production financial history is stored in date epochs 20260909, 20260910 and 20260911; there are no literal `history` financial jobs. Continue from the oldest date epoch and preserve cross-epoch attempt/terminal dedup.
- Fund portfolio has 15994 never-attempted request signatures remaining after this batch. Its 7 quality and 6 blocked signatures need cached-object recovery or explicit review; do not replay them upstream.
- The 240 rpm fund portfolio limit shares an account-level rolling window with regular acquisition. Use a smaller budget or a fresh rate window; never assume 360 requests fit in 90 seconds.
- RRG forward-only vintages remain `blocked_data` for the 20260831 signal. Historical release requires authoritative Citic change archives with publication/known-at, revision and withdrawal evidence.
- Await normal publish-only, verify new release membership and hashes, mirror it to Mac, and repeat the offline read acceptance including `fund_portfolio` and the new financial rows.

## Evidence

- `docs/tushare-financial-pit-batch14-20260911.evidence.json`
- `docs/tushare-fund-portfolio-production-20260911.evidence.json`
- `docs/tushare-release-476b-offline-20260911.evidence.json`
