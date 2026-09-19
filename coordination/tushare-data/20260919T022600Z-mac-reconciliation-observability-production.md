# Tushare：分片复核可观察性更正与优先扫描生产验收
- 时间、节点、任务标识：2026-09-19T02:26Z，Mac，reconciliation-observability
- 状态：完成；全量补采继续
- 提交：`d10629d0` 增加新增/重复计数，`cb64c598` 优先open父任务并保留resolved审计
- 接续/更正：更正 `20260919T021100Z-mac-reconciliation-budget-production.md` 中把旧 `resolved=200` 写成新增闭合量的表述

旧 `resolved` 字段同时包含此前已闭合父任务，不能证明本轮新增闭合。53项相关测试通过，Ruff/diff通过；运行时与仓库管线SHA一致。生产库存有17810个分片父任务：10691个split_pending、5830个resolved、764个blocked、525个superseded。

未分流的1000项扫描真实显示新增0、重复确认543、耗时9.724111秒。最终配置保持总预算1000，改为936个open优先扫描和64个resolved完整性审计；正式周期open新增0、审计64项全有效，总复核1.679375秒。同轮708次真实请求、1220个文档阶段、107.758秒，错误为空且规划指纹未变。没有额外上游请求。

结论：当前split_pending主要是子分片尚未完成，不是本地闭合队列积压；后台复核用于崩溃恢复和已闭合文件退化检测。完整历史、空响应完整性、修订、known_at/PIT仍开放。证据：`docs/tushare-partition-reconciliation-production-20260919.json`。
