# Mac Tushare 附件解析队列索引优化开始

- 时间、节点、任务：2026-09-18T03:45:00Z，Mac 全量归档所有者，document-parse-index。
- 生产证据：附件 worker 三路并发、300 阶段预算下多轮用满 90 秒。最近完整周期处理 129 下载 + 129 解析；前一轮时序显示 189 次 claim、`claim_db_total_seconds=17.113577`。对生产数据库执行只读 immutable 查询计划后，下载领取 48 行约 0.0012 秒，解析领取 1 行约 0.1765 秒，解析查询出现临时排序。
- 方案：保持网络并发、90 秒预算、失败退避和 Tushare API 限速不变，只为可重试的待解析集合增加按文档 ID 排序的局部索引；claim 元数据从 v2 事务升级至 v3，查询显式使用该索引。
- 隔离：候选在 `/private/tmp/quantmind-tushare-document-parse-index` 的 `codex/tushare-document-parse-index` 分支开发；运行中的 PID 7728 不读取该 worktree。部署需等完整周期边界，短停唯一 Mac writer，原子安装后恢复并以真实周期验收。
