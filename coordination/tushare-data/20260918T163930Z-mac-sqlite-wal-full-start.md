# Mac Tushare SQLite WAL FULL 优化开始

- 时间、节点：2026-09-18T16:39:30Z，Mac 全量归档唯一写入者。
- 目标：在隔离 worktree 验证 `pipeline.sqlite` 与 `documents.sqlite` 从 `DELETE + FULL` 切换为 `WAL + FULL`，减少每请求限速预约和响应落盘的本地提交耗时，加快仍有约 284 万结构化任务的历史补采。
- 边界：不改变 Tushare 账户或接口 RPM、每日配额、任务身份、原始响应、提交顺序、文档处理上限、云端缓存角色或 Token 存放。请求前 gate 与响应后结果仍分别提交；`synchronous=FULL` 保持断电耐久级别。
- 当前证据：生产周期无空队列等待，718 次请求耗时约 103.5 秒；本机同盘 800 次独立事务微基准中，`DELETE + FULL` 中位约 0.299 秒，`WAL + FULL` 中位约 0.057 秒。微基准只用于选择候选，最终以测试、迁移恢复和真实生产周期验收为准。
- 文件范围：`backend/shared/tushare_pipeline.py`、`backend/shared/tushare_documents.py`、相关 Tushare 测试与运维说明。候选分支 `codex/tushare-sqlite-wal-full-20260919`。
