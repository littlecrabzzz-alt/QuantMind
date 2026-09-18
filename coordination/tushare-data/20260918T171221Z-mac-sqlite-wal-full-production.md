# Mac Tushare SQLite WAL + FULL 生产验收完成

- 时间、节点：2026-09-18T17:12Z，Mac 全量归档唯一写入者。
- 状态：本次 SQLite 提速已完成并在生产运行；Tushare 全量历史补采仍在继续，尚未宣称全量完成。
- 分支、提交：候选 `codex/tushare-sqlite-wal-full-20260919` / `814c9a76`；已合入并推送 `master` 的 `651d24b2c5562e2a324ded6f001536b78e0accd7`。
- 接续：`20260918T163930Z-mac-sqlite-wal-full-start.md`。

本次完成：`pipeline.sqlite` 与 `documents.sqlite` 已从 `DELETE + FULL` 原地切换为 `WAL + FULL`；请求前频控槽事务、响应后结果事务及 `synchronous=FULL` 均保持。代码默认使用 WAL，并提供仅在停止唯一写入者后使用的 `QM_TUSHARE_SQLITE_JOURNAL_MODE=DELETE` NAS 回退。`planning_only` 是生产队列持久化扩展周期，会发送 0 次供应商请求，至少等待 5 秒后继续真实采集，不是 dry-run 或演练。

验证：完整 Tushare 套件 1,360 项通过、5 项跳过；日志 `/tmp/qm-tushare-full-suite-wal-full-v4.log`，SHA-256 `e5626114110a6e197ca5f65d41466c549a275ba45486c28881474d3d1d661963`。两库实际转换分别约 3.03 秒和 1.90 秒，版本、schema 与转换前最大 rowid 保持；生产 LaunchAgent PID 45900 运行且从未退出。5 个真实周期共 3,752 次请求和 10,683 份文档，失败阶段均为空；请求频控事务中位耗时由 1.531 秒降至 0.773 秒，文档 claim/finish 由 2.975/4.466 秒降至 1.584/2.365 秒，墙钟吞吐中位数由 432.8 升至 446.9 次/分钟。部署后有界 attempt 尾部审计截至 rowid 777182：4,745 条均为 HTTP 200，显式限流、传输、API、权限或格式错误为 0；7 条 `tdx_member` 达单页上限，均已创建日期二分子任务继续采集。

范围核对：当前目录中的 251 个命名义务有 247 个运行时可读接口；其余 4 个为非运行时 endpoint 名。固定发布中 247 个已注册、246 个已规划、198 个已发布；未规划的可执行注册接口为 0。48 个已规划未出数据的接口保持显式状态：36 个权限拒绝、11 个 API 错误、1 个可用但空；不会伪装为已完成。审计文件位于 `/tmp/tushare-scope-audit-current-20260919.json` 和 `/tmp/tushare-fixed-coverage-current-20260919.json`。

生产证据汇总：`/tmp/tushare-wal-full-production-summary-20260919.json`，SHA-256 `19e00b6b183418fb0d19c689c1ac68f61553f8b1b21af9dc93287bd1ab9f1bbc`。该文件不含凭据。云端主工作树已取得代码提交，完整采集仍只在 Mac；云端只运行受限研究缓存 timer，不运行全量写入者。

下一步：保持本地采集持续运行并按当前约 284 万结构化待执行任务继续补齐；后续优化以真实周期证据为准，不改变账户/API 分层限速、每日总量、权限缺口记录或云端研究子集边界。迁 NAS 前必须验证目标文件系统的 WAL 共享内存语义；否则停写后切回 DELETE。
