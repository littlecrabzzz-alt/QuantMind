# Mac Tushare 双路隔离采集候选开始

- 时间、节点、任务标识：2026-09-18，Mac，capture2
- 分支和范围：将在独立 `codex/tushare-capture2` worktree 中仅修改采集进程数的有界配置、相关测试和运维文档；不修改数据合同、任务身份、请求频控、每日配额或云端写入角色
- 依据：最近六个生产采集周期在约 100 秒采集阶段内完成 338–420 次请求；最新轮 393 次请求的单路 HTTP+落盘累计为 79.138 秒，而主进程 35.798 秒选择时间中 32.827 秒是按 500 次/分钟规则的主动等待，频控事务仅 0.921 秒
- 边界：候选只允许 `acquisition_capture_workers=1..2`；两路必须同时使用已有的 process 隔离和 depth 2。所有任务仍由主进程逐个持久化共享账户/API gate，崩溃后 `inflight` 恢复和已预留 gate 不回滚
- 验收：先用本地 HTTP 夹具证明峰值两路且非法组合拒绝，重跑 pipeline/rate-policy/installer 回归；生产灰度保持 `batch_requests=800`、`batch_seconds=100`、账户 500 次/分钟及所有接口级上限，对比真实请求数、`rate_limited`、失败阶段和资源使用
- 运行边界：Mac 生产 worker 继续运行；云端只保留研究缓存，不恢复全量 writer
