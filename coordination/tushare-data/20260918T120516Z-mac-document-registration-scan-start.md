# Tushare 文档登记连续扫描补齐
- 时间、节点、任务标识：2026-09-18，Mac，document-registration-scan
- 状态：进行中
- 分支、worktree：`codex/tushare-document-registration-scan`，`/private/tmp/quantmind-tushare-document-scan-batch`
- 分工：只修改登记 attempt 连续扫描和对应测试；不修改记录身份、事务分块、供应商请求或下载并发
- 接续：`20260918T120106Z-mac-document-registration90-production.md`

生产发现单页 1000-attempt 上限会在低附件密度区仅使用约 5 秒即返回，剩余 90 秒预算空置。候选将保持每页 1000 条和精确游标，但在同一硬截止、观测/记录上限内继续读取下一页；以基线等价测试、锁/截止测试和真实积压净变化决定是否保留。
