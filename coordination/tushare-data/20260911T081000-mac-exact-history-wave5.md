# Tushare exact history wave 5

- Owner: Mac controls the bounded run; the cloud authority remains the only formal writer.
- Safe drain: Beat stopped first and the exact Tushare consumer stopped accepting new work. Task `b2bd0a1d…` completed naturally in 186.708 seconds; active and reserved work were empty before the worker stopped. No task was revoked.
- Frozen input: four immutable manifests reference fixed release `data-bdb8d5c76f676b5595a8af871cbc563e3705ff25713c4a5514c61b9aca9e6b68`, configuration `da45afae…`, and pinned task, preparation, and runner hashes.
- Plan-only: all authority, credential, network, write, and publish access flags were false for every batch.
- Result: 904 upstream calls, 904 HTTP 200, 0 HTTP 429, and 1,281,772 rows. Physical SHA verification passed for 904 raw objects, 904 observations, and 903 Parquet files. The missing Parquet corresponds to one verified empty NPR result. Authority closure SHA-256 is `f6d735723ca2204af5fbba28ebb85b1e05572ab09b321ecd1a3d9e400f7b4c6d`.
- Fund price batch 6: 360/360 done in 43.795 seconds, 221,980 rows across `fund_daily` and `fund_adj`, covering 2016-04-26 through 2017-01-17.
- Dividend batch 5: 360/360 done in 51.828 seconds, 22,381 rows, selected evenly from Shanghai and Shenzhen.
- NPR history leaf batch 3: four new leaves completed in 1.904 seconds; one done, one empty, and two split again, returning 1,007 rows.
- Announcement batch 4: the manifest froze 360 tasks and the execution cap remained 180 calls. It completed 180 HTTP 200 calls in 66.745 seconds, yielding six done, 174 split-pending, 180 untouched pending tasks, and 1,036,404 rows.
- Restore: API, dedicated worker, and Beat are healthy with zero restarts and no OOM. Cloud free space is 232,011,051,008 bytes, above the 100 GiB reserve.
- Publication boundary: `CURRENT.json` remains `data-bdb8d5c7…`; waves 4 and 5 plus the NPR residual chain remain authority-only until the hourly publisher runs after 08:17 CST and the Mac mirror verifies the new fixed version.
- Backlog snapshot: history had 2,205,669 pending and 3,570 split-pending tasks at 08:05 CST before wave 5 finished. The largest families without dedicated exact runners are `dc_member`, holder concentration, `fina_mainbz`, `index_daily`, factor library, TDX membership, chip distribution, ETF baskets, and fund portfolios.
- Next development priority: add exact runners for `index_daily` and `fina_mainbz`, then member and ETF basket families. Any member runner must preserve PIT version, `known_at`, and source evidence; `cyq_perf` must retain its daily quota.
- Boundaries: `history_complete=false`, historical revisions and PIT remain incomplete, RRG remains `blocked_data`, and the whole-project snapshot timer remains disabled pending disk expansion.
- Machine evidence: `docs/tushare-exact-history-wave5-20260911.evidence.json`.
