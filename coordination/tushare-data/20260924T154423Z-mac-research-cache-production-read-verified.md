# Tushare 云端固定研究读源恢复验收

- 时间、节点、任务标识：2026-09-24 15:44 UTC，Mac 发起、云端验收，research-cache-production-20260924。
- 状态：生产离线读取与定时增量缓存恢复；最新全量追平、研究语义准入仍待验证。接续本主题 `20260924T150749Z`、`20260924T153200Z` 两条记录。
- 代码：master `af7df927`，已推送、双端 handoff 对齐；Mac 仅重启 `com.quantmind.tushare-source`，全量采集 worker 未重启；云端缓存 timer 保持 enabled/active。

云端缓存服务真实成功（Result=success, ExecMainStatus=0），从 Mac 私有入口校验并下载 83678 个缺失文件、851017133 bytes，`CURRENT` 原子切至 `data-2841a9ef...`。固定子集含 12 个 API，状态 `verified`、`upstream_calls=0`，占用约 6.8 GB / 50 GiB 预算。正式容器 `QM_TUSHARE_READ_STORE=research-cache`、healthy，在新固定版 `trade_cal` 与 `daily` 各读 2 行且零供应商调用；`daily` 耗时 39.36 秒。云端剩余约 514 GiB，Mac 剩余约 1110 GiB。

边界：子集实际源版本 `data-86e61947...` 是 Mac 2026-09-24 05:21 的全量发布；Mac 最新 `data-525e814e...` 于 20:15 发布，云端 `source_lagged=true`，Mac 正后台准备新版。下一次云端 timer 预计 23:56 CST，完成时按固定版、源滞后、查询再验。子集 manifest 仍明确 `history_complete=false`、`historical_versions_complete=false`；RRG case 仍 `blocked_data`，中信历史分类、成员 known_at 和 ETF 执行证据需单独补齐，不能将当前离线读通认作 RRG 可生产研究或交易授权。
