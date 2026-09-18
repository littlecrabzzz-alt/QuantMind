# Tushare 归档周期日志精简生产验收

- 时间、节点、任务标识：2026-09-18T18:01:03Z，Mac，`archive-log-compaction`
- 状态：完成
- 分支、worktree、提交：候选 `codex/tushare-archive-log-compaction-20260919` / `/private/tmp/quantmind-tushare-archive-log-compaction` / `c0d83480`；已 cherry-pick 到 `master` 为 `d4e5607a`并 push。
- 接续：`20260918T174459Z-mac-archive-log-compaction-start.md`。

变更仅将 LaunchAgent stdout 从完整周期报告改为运维摘要；`archive-worker-status.json` 仍原子保存全量状态。测试使用 `/tmp/qm-tushare-fulltest310-20260919-1749` 的完整 Python 3.10 隔离环境：1,363 项通过、5 项跳过，日志 `/tmp/qm-tushare-full-suite-log-compaction-v5.log` SHA-256 `f68007d533bc86a55f1d5b3393e748b8d2ec7144eb3652a6bd6296eb8b067a0c`；Ruff、`py_compile`和 `git diff --check` 通过。

部署先原子移开 `ENABLED`，旧 PID 83993 完成在途轮次后于 17:57:56Z 报告 `disabled`，再卸载并恢复原字节/0600 标记。安装副本与 `master` Worker SHA-256 均为 `e9c594ef400807f30d74eb316d415811622f625da0262fb21035e53d07e365a2`。旧 131 MB stdout 保留为 `~/Library/Application Support/QuantMind/logs/tushare-archive.out.pre-compact-20260919T0158.log`，未删除证据。

新 PID 26411 首个生产轮次于 18:00:09Z 完成：774 次真实请求、2,306 个文档阶段、失败阶段为空，结构化 `done=416719`、`pending=2833861`，文档 `parsed=320254`、`pending_download=4811312`。完整状态 126,647 字节且仍含 459 个归档版本条目；stdout 该轮仅 713 字节，约减少 99.4%。进程仍 running、never exited，剩余磁盘约 2.0 TiB。

云端 Git 已对齐 `d4e5607a`；全量 Tushare writer 进程为 0，`tushare-research-cache.timer` enabled/active，当时 service inactive 为定时器间歇正常状态。Mac 本地 API 未启动使 `handoff` 最后的 HTTP 预检仍连接被拒，不影响 Git 已快进、本地原生归档或云端缓存定时器。

下一步：Mac 继续作为唯一全量写入者消化结构化和文档队列；完整度结论仍以固定版发布、明确缺口和最终队列闭合为准，不因本次日志优化改变。
