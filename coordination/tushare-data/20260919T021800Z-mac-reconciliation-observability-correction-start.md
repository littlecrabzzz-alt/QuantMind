# Tushare：分片复核新增闭合量可观察性更正
- 时间、节点、任务标识：2026-09-19T02:18Z，Mac，reconciliation-observability
- 状态：进行中
- 分支、worktree：`codex/tushare-reconciliation-observability-20260919`，`/private/tmp/quantmind-reconciliation-observability-20260919`
- 分工：仅修改分片复核报告、相关测试及上一轮生产证据措辞；保留其他未提交工作。
- 接续：`20260919T021100Z-mac-reconciliation-budget-production.md`

生产报告的既有 `resolved` 统计包含此前已闭合且本轮再次确认的父任务，不能解释为本轮新增闭合量。增加向后兼容的 `newly_resolved`、`reaffirmed_resolved` 和 `changed` 计数，修正文档后部署真实验收；复核预算1000和抓取限速保持不变。
