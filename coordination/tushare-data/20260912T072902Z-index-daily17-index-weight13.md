# Tushare index daily 17 and index weight 13

- Beat stopped first and the Tushare worker completed its active task before a warm exit. No task was revoked or killed. Redis unacked state and both locks returned idle; two expired queued envelopes were retained and naturally discarded after service restoration.
- The ea64 `index_daily` selection drifted by seven tasks from its pre-publication candidate. A new file retained the old candidate unchanged, then passed current-release, live-pristine and zero-overlap gates. Batch 17 made 360 HTTP-200 calls in 66.574 seconds: 358 done, two empty and 81,308 rows.
- `index_weight` batch 13 passed a same-lock live gate: 360 pristine tasks, zero overlap with 4,320 historical tasks/requests and zero overlap with 802 recursive descendants. It made 360 HTTP-200 calls in 55.345 seconds: 290 done, 37 empty, 33 split pending and 112,316 rows. Its 66 child tasks are unique and pristine.
- Independent closure verified 2,121 object/observation/Parquet files and 27,581,177 bytes by size and SHA, plus every observation-to-object link. The two batches did not publish or switch CURRENT.
- Worker and Beat were restored with the existing containers and are healthy with restart count zero and OOMKilled false. Cloud free space is 347,601,272,832 bytes, 240,227,090,432 bytes above the 100 GiB reserve.
- Fixed release inclusion and Mac offline acceptance are the next gates. Empty responses, descendants, complete history, revisions, `known_at`, PIT semantics and RRG classification remain open.
