# 全局规划 signature 回退机制：只读确认
- remaining_markets / Mac；当前 master fef5233；完成。增补 `20260908T220033Z-mac-fullscope-readonly-ready-10d84775.md`；不编辑 text 正占用的 plan_extended 或运行文件。
- 云端证据仍仅业务容器 `python3 -S`、SQLite `mode=ro`/query_only 和已发布 manifest 白名单读取；无 Pipeline 实例/生产 API/密钥。

**确认机制存在，建议列为下一轮吞吐优先修复。** `backend/shared/tushare_pipeline.py:872` 只算一个 signature，包含跨全部 family 的配置白名单、完整 identifiers 及完整 EXTENDED_CONTRACTS。`:945` 比较不同时所有启用且未 validation_blocked 的 family，recent/history 游标均写回 offset=0、done=0、anchor=today。global periods 的特殊保留也依赖同一基础 signature，因此基础 hash 改变不保留旧游标。

精确边界：不是任意 config 键都触发，只有代码列出的全家族 config 子集；单纯 enable flag 或 budget 变化不在此 hash 中。identifiers 是去重/排序后的发现集合，单纯响应重排不触发，但任一市场新增代码（包括 opt_daily/sge_daily/fx_daily 发现）会触发无关家族重置。EXTENDED_CONTRACTS 即使新增未启用 API、改变说明等合同值，也进入共同 hash；还没注册的纯合同模块不会触发。

已发布清单均通过 release ID = SHA256(manifest bytes) 验证：
- 20:59:25Z：history global/market/other/structured/supplement/text offset=9500，共同基础 hash `a1672020771b…`。
- 21:29:16Z：上述 history offset=3000，基础 hash `8671507c410a…`；新 futures/research 也为3000。
- 21:50:46Z：9个 history 均 offset=1500，基础 hash `6ed439a8cd8a…`。
- 22:00:30Z：同 `6ed…` 才到4000；随后 live planning_state 9个 history 仍共享该hash、offset=4000、done=0。这是实际全家族游标回退证据；现有快照不足以逐次区分由配置、合同或发现集合哪个变化引发，也没有测量重放的总耗时。

影响：`:966` 重新构建完整 planner + `islice(offset)`，无数据库 seek 式继续；重置后从头枚举既有任务。`:314` enqueue 的 INSERT OR IGNORE 保持任务键幂等，旧 done/empty 不会因此变回 pending，也不自动重复 API 请求；但每家族每轮当前500个枚举预算被旧任务重放占用。`:973-979` count/offset 计生成器消耗量而非新增 INSERT 数，stats.planned 也不代表新增工作。不断发现新代码或频繁加合同可使长尾历史反复等待；无重置时 islice 同样需重走前缀，CPU成本随offset增加。

最小后续方向：在不遗漏新代码/新接口历史义务、不迁移/清空现有队列的前提下，按 family 的真实依赖裁剪 signature（text 不依赖全市场证券集合），无关变更保持游标；有相关新标的时需明确追加/重扫策略，不能仅把 identifiers 从签名删除。分别验证无关家族变更不重置、相关变更仍覆盖历史、合同变更安全重扫、旧成功任务幂等。先报告新增 job 数与重放量再评价吞吐。此轮仅提出边界与证据，不做代码改动。

详细证据 `/tmp/quantmind-fullscope-planning-signatures-20260909.json`，保存完整hash、各family游标、4个发布release及mtime。此前全量快照仍是21:57口径，不用这几个signature快照外推队列增长或ETA。
