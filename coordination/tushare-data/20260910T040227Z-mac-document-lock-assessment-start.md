# Tushare documents.sqlite 锁冲突候选评估开始

- 时间、节点、任务标识：2026-09-10 04:02:27Z，mac，document-lock-assessment
- 状态：进行中
- 分支、worktree、基线：`codex/tushare-document-lock-20260910`，`/Users/lizeyu/Documents/ChatGPT/投资/.worktrees/quantmind-tushare-document-lock`，`68c18fc2676ab1bf7e915dfca5ccda105dc29b9e`
- 分工：仅评估/测试文档 SQLite 锁冲突、必要时提交最小修复和本主题唯一记录；不访问生产数据、不读凭据、不改并发/范围/证据/磁盘保护。
- 接续：`20260910T035500Z-mac-realtime-doc-rrg-production-root.md`、`20260910T022030Z-mac-document-throughput-readonly-structured.md`。

待验证：区分长审计读事务与正常 registration/document-index 写事务；确认 SQLite 现有 10 秒 busy timeout 对短冲突的处理、claim/finish 提交失败的回滚与后续恢复，再决定是否需要 WAL、额外重试或任务级降级。只用临时 SQLite 做百万行与锁冲突基准。
