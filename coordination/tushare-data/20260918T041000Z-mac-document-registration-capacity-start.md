# Mac Tushare 附件登记追赶容量开始

- 时间、节点、任务：2026-09-18T04:10:00Z，Mac 全量归档所有者，document-registration-capacity。
- 生产证据：`document_cursor=176179`，attempt 最大 rowid 574260，剩余 398081 条；只读 JSON 索引统计其中至少 35738 条属于已购九个文本/附件接口。当前每轮上限 20 observation、500 records、5 秒，而 acquisition 每轮约新增 700 条 attempt，登记游标可能持续落后。
- 方案：让 tick 从私有配置传入有界登记预算，保留旧默认 20/500/5；生产目标 100 observation、5000 records、5 秒。最大仍由代码限制为 1000/5000/20，断点、幂等引用、先文档提交后游标 checkpoint 和数据库忙时延后语义不变。
- 隔离：候选在 `/private/tmp/quantmind-tushare-document-registration-capacity` 的 `codex/tushare-document-registration-capacity` 分支完成；运行中的 Mac worker 不读取该 worktree。代码部署需等完整周期边界，生产先只扩大登记预算，不增加下载并发或 Tushare API 上限。
