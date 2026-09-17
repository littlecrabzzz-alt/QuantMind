# Mac stk_rewards supplier-terminal production acceptance

- Official source: `https://tushare.pro/document/2?doc_id=194`; `ts_code` is required, `end_date` is an optional report-period filter, and the page publishes no offset/limit or row cap.
- Root cause: the local unverified 1,000-row alarm overrode explicit supplier `has_more=false`, leaving six complete single-stock responses in `possibly_truncated`.
- Pre-change evidence: the six retained responses contained 1,018–1,428 rows, HTTP 200 complete JSON, complete requested fields, explicit `has_more=false`, zero duplicate contract keys, and valid object hashes.
- Implementation: commit `43a6f47eb386c08501115e548ae929bb4441938e` enables supplier-terminal evidence for `stk_rewards` only when requested fields, non-null requirements and value checks pass. `has_more=true` and malformed responses remain blocked.
- Validation: 60 related stock-context, reward-period, intake, THS terminal and technical-extra tests passed. Python compilation, Ruff and `git diff --check` passed.
- Reassessment: all object, observation and Parquet checksums passed. Six jobs changed from blocked to done; source attempts and artifacts were unchanged at migration time (`attempts=421316`); upstream calls=0.
- Receipt: `stk-rewards-terminal-reassessment-v1.6da7ddb1b3d5dee06a631ffbc1d1e557dec31761d23d14aef68545449dfea4f6.json` in the private Mac archive. It contains no credential.
- Queue after acceptance: `stk_rewards` blocked=0, supplier-terminal jobs=6. Thirteen separate quality jobs remain visible for their own schema/value issues and were not changed.
- Runtime acceptance: installed/source contract hash `66d962f77dcc348a2894d3656f470bf95fa81ad82200b903b2ddced7283ea03b`; intake hash `8830bbfbba121a2bcd4498de1b2ae45130e399124a02a9ab71abcc1dd45a8ee8`. Restarted worker completed its first production cycle in 101.04 seconds with 326 real requests and no failed stage.
- Cloud: Git/source aligned to `43a6f47eb386c08501115e548ae929bb4441938e`, dual-node source digest `cba31a01247b1c041b30ae90f9234a9659ad4d3a3257e1ecffae5330dd7cc8e5`. Cloud has only the enabled/active research-cache timer; no full Tushare writer unit was installed.
- Coverage boundary: this accepts each supplier-declared terminal single-stock response. It does not claim the stock universe or supplier history floor is complete; unbounded code discovery and observed report-period supplements continue.
- Disk: about 2.3 TiB free; archive worker and research-cache service remain running.
