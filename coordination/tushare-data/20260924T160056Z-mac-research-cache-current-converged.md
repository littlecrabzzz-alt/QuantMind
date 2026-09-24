# Tushare 云端研究读源追平本次完整发布

- 时间、节点、任务标识：2026-09-24 16:00 UTC，Mac 供数与云端验收，research-cache-production-20260924。
- 状态：本次固定发布的生产离线读链路已追平；历史完整性和 RRG 研究准入仍未通过。接续本主题 `20260924T154423Z-mac-research-cache-production-read-verified.md`。
- 代码：master `112265de` 已推送；两端单节点预检确认 Git 提交及源码摘要完全一致。Mac 仅重启 `com.quantmind.tushare-source`；`com.quantmind.tushare-archive` PID 58311 持续运行，云端没有恢复全量采集者。

实测上轮 149734 个分区及 299469 个文件描述在 Mac 最新全量发布中全部保留，新增 511 个分区。增量供数代码复用旧子集的已验证不可变文件，仅核对新增分区；若旧分区/文件描述不一致，则回退精确重扫。Mac 新子集于 23:55 CST 生成，源版本等于 20:15 的全量发布 `data-525e814e…`。云端 timer 自动运行成功，仅下载并校验 1022 个新增文件、25442808 bytes，`CURRENT` 原子切至 `data-d506d637…`，`source_lagged=false`、`upstream_calls=0`。

生产验收：缓存服务 Result=success/ExecMainStatus=0，timer active/enabled，正式 `quantmind` 容器 healthy，读取根目录 `/data/tushare-research`。新固定版 `trade_cal` 和 `daily` 各返回 2 行且零供应商调用，耗时分别 1.54、33.11 秒；未认证 HTTP 返回 401。研究缓存实际目录约 6.9 GB，预算 50 GiB；云端约 514 GiB、Mac 约 1109 GiB 可用。专用缓存测试 7 项、云端数据 API 测试 8 项通过，Ruff/diff check 通过。

仍未准入：研究子集标记 `history_complete=false` 和 `historical_versions_complete=false`；RRG 仍为 `blocked_data`，历史中信分类、成员 known_at 与 ETF 执行证据未闭合。`daily` 约 33 秒的单次查询需后续性能治理。完整双端 `handoff` 的最后本地 HTTP 健康检查因 Mac 本地后端/隧道未监听而失败；未改动该服务，单节点角色、Git 与源码摘要已分别核对一致。正式交易授权不由本次数据读链路授予。
