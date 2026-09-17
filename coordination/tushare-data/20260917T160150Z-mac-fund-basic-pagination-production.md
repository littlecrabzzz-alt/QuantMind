# Mac fund_basic pagination production acceptance

- Authority: Mac local archive at `~/Library/Application Support/QuantMind/tushare`.
- Source: Tushare `fund_basic`, official document `https://tushare.pro/document/2?doc_id=19`.
- Published contract: `market`, `status`, exact `ts_code`; single-call maximum 15,000 rows. The public input table does not list pagination parameters.
- Live probe: provider accepted `limit` and `offset`; repeated 100-row page digests were stable; offset 15,000 returned a finite tail with `has_more=false`; offset 30,000 returned zero rows.
- Implementation: commit `e503a3bb0eeba138b615122313c7d353e0b47403` adds a live-verified 15,000-row pagination contract and terminal marker for a short page.
- Tests: 34 relevant offline tests passed across market contracts, the new fund pagination check, existing pagination behavior, credit/fund discovery, fund NAV batching and discovery projection. Python compilation, Ruff and `git diff --check` passed. One unrelated pre-existing bounded-planning assertion in the whole extended file fails identically on the previous master and was not changed.
- Cloud alignment: cloud head is `e503a3bb0eeba138b615122313c7d353e0b47403`; `dual_node_check.py --node cloud` passed with source digest `f557107d8cb0c54f8199f78ec7ee67abbd54a8800b49e2893f92763a19c95596`. `tushare-research-cache.timer` remains enabled and active. No cloud full-archive writer was enabled and no QuantDB service was stopped.
- Runtime: deployed source hashes match master (`tushare_market_contracts.py` `368b93752103652ccfc33819e1e0ae8601555b32e772d5d1d38f02aa1cec17d8`; `tushare_pipeline.py` `6e4276a9d4287e18e6dbc4215c690c3eb529b8ac3cc860f82fb94c88f2871cdb`).
- Migration: at a natural worker boundary, 10 retained 15,000-row blocked parents across epochs 20260909/10/11/13/17 were reused and 10 offset-15,000 jobs were enqueued atomically. Migration made zero upstream calls and preserved original jobs, attempts, observations, objects and Parquet artifacts.
- Production result: all 10 tail jobs completed in one request each with `sample_ok`, `supplier_has_more=false`, `pagination_end=true`, no pagination error, and verified object/Parquet hashes. Five unfiltered `market=O` tails each returned 14,872 rows; five `market=O,status=L` tails each returned 10,042 rows.
- Current-epoch coverage: retained page zero plus the tail has 29,872 unique `market=O` codes and 25,042 unique `market=O,status=L` codes; both current pairs had zero cross-page overlap. Older parent/tail pairs are retained as observations collected at different times and are not represented as point-in-time snapshots.
- Queue state after acceptance: `fund_basic` blocked=0, quality=0. The native worker was restored as the sole full writer; production acquisition continues.
- Disk: about 2.3 TiB free; NAS warning remains false.
