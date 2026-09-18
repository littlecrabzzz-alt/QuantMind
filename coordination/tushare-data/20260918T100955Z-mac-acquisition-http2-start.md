# Tushare：双 HTTP 采集灰度开始

- 时间、节点、任务：2026-09-18T10:09:55Z，Mac，acquisition-http2
- 状态：候选测试通过，尚未部署
- 分支/worktree：`codex/tushare-acquisition-http2`、`/private/tmp/quantmind-tushare-acquisition-http2`
- 基线：`master` / `f970d6793d21f7e0a75aa47b7dd0ef9a60117d70`
- 范围：只增加默认关闭、最多 2 个 HTTP worker 的有界采集路径和对应测试/说明；不修改接口权限、任务规划、文档并发、全量存储边界或官方频率上限。

生产证据：单 HTTP worker 最近一轮在 101.396 秒采集阶段完成 446 次请求；账户门只要求睡眠 35.519 秒，实际捕获累计 80.019 秒，说明网络往返串行化使实际约 264 次/分钟，低于当前合法的 500 次/分钟账户档位。流水线已经在请求前同一事务提交任务 `inflight` 状态和账户/API 频控槽，结果由主线程按派发顺序唯一写入，崩溃恢复不回收频控槽。

候选新增 `acquisition_http_workers`，默认 1、上限 2；值 2 只允许与深度 2、thread 捕获和显式账户频率同时使用。实际 HTTP 开始点另有共享线程门，同时保持账户和接口最小间隔；网络并发上限为 2，结果写入仍为单线程。隔离测试真实形成峰值 2 的网络重叠，四个请求开始间隔不低于门限、任务全部完成且 `inflight` 清零；时序测试连续 5 次通过。

相关 72 项测试在生产依赖环境通过，Ruff、`py_compile` 和 diff 检查通过。完整 1317 项集合中 11 个失败和 11 个功能错误已在未修改基线逐项复现，另 12 个错误为轻量生产环境缺 FastAPI/PyYAML/ReportLab；候选未新增完整集合失败。生产首先使用 `rollout_account_rpm=480`，至少观察三个真实轮次的请求速率、供应商限流、失败、任务事务、CPU/内存和磁盘；异常则恢复单 worker/process 捕获。
