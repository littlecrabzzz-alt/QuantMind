# Mac Tushare 权限重验证生产验收

- 时间、所有权：2026-09-18T06:09:00Z；Mac 仍是完整 Tushare 归档唯一写入者，云端仅保留研究缓存。
- 代码：`1a3b00b19e8555e4617dc9e9f0b8aabaa135bf39` 已合入并推送 `master`。实现为每次规划最多选择 4 个超过 7 天未验证的 `permission_denied` 范围，各恢复一条代表任务；原 `result`、`tries` 和 `attempts` 不变。真实成功才精确恢复同一 `api_name + src` 范围，再次拒绝则刷新权限证据。
- 离线验证：相关调度、周期和精确恢复测试 21 项通过；账户历史与两融历史存储测试 16 项在生产客户端依赖环境通过；此前组合测试 44 项通过；Ruff、语法编译和 `git diff --check` 通过。完整 extended 文件中的既有规划数量断言在未修改的 `a3b2ef39` 同样失败，未纳入本次改动。
- 部署：等待 PID 68745 已开始的采集周期自然完成，移走 `ENABLED` 后观察到 `disabled`，再卸载 LaunchAgent、更新运行代码和原子恢复完全相同的 marker。`pipeline-config.json` 保持 0600，只新增 `permission_reprobe_interval_seconds=604800` 与 `permission_reprobe_max_scopes=4`；配置 SHA-256 从 `e2b4a31b57822dfd315b24770c12e5c85fd96c219628ff561acaeb9ec45645fa` 变为 `7b86c87f30918d77f3234f1b0b475af74905121821b8d9ecd7814616ca6306bd`。Token 文件未读取、未修改、未进入 Git 或报告。
- 规划验收：配置指纹变化触发真实 `planning_only` 周期，生产库写入 4 个持久化 `permission_reprobe` 检查点。代表范围为 `cb_price_chg:`、`hk_adjfactor:`、`hk_daily_adj:`、`us_daily:`；检查点时间为 1789711294。该周期不访问供应商，后续采集轮才执行代表请求。
- 真实权限结果：`cb_price_chg:`、`hk_adjfactor:`、`hk_daily_adj:` 均再次返回 `permission_denied`，其余任务保持 `permission_blocked`，`checked_at` 刷新为本轮真实时间。`us_daily:` 返回 8,000 行并触发既有分页拆分，capability 从 `permission_denied` 变为 `available`；该范围当时没有其他冻结兄弟任务，因此 `requeued_jobs=0`，代表任务自身继续按分页合同处理。
- 吞吐验收：恢复轮在 2026-09-18T06:04:26Z 至 06:06:10Z 完成，100.023 秒内发出 630 个请求，整轮 103.567 秒，`failed_stage=null`。对应最近 630 个 attempt 为 341 `sample_ok`、275 `empty_unverified`、11 `possibly_truncated`、3 `permission_denied`，没有 `rate_limited`、传输错误或无效响应；并行文档阶段处理 319 项并报告 `ok`。结构化队列仍有 2,868,874 个 pending，完整历史同步尚未完成并继续后台运行。
- 诊断插曲：首个真实轮期间曾执行一条未索引的生产任务统计查询，较长只读锁使写进程等待 10 秒后以 `OperationalError` 结束。该失败轮没有覆盖已提交规划或 attempt，LaunchAgent 自动重试后完整通过。后续验收只读取原子状态文件及 capability/scheduler 小表；生产运行期间禁止再扫描 jobs 大表。
- 云端边界：`/root/code/QuantMind` 已用 `handoff --align-git mac` 仅快进 Git 元数据到同一提交，目标 5 个文件干净，其他研究修改保留。完整归档目录没有 `ENABLED`，没有完整 Tushare writer，`ARCHIVE_RELOCATED.json` 仍存在；`tushare-research-cache.timer` 为 enabled，下一次计划运行可见。云端 `dual_node_check.py --node cloud` 通过，Syncthing idle、0 errors、peer 100%；云端 `origin/master` 已 fetch 到同一提交。Mac 双端入口最后仅因本地 127.0.0.1:8000 开发 API 未运行而结束为 connection refused，不影响 Git 对齐、Mac 归档或云端研究缓存。

结论：权限变化后的自动发现缺口已经在真实账号上闭环，复查频率和范围有硬上限，供应商拒绝不会扩散解冻；本地完整归档继续采集，云端继续只消费研究子集。
