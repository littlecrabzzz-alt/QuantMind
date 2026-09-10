# Tushare 附件队列吞吐候选开始

- 时间、节点、任务标识：2026-09-10 03:18:01Z，mac，document-throughput-candidate
- 状态：进行中
- 分支、worktree、基线：`codex/tushare-document-throughput-20260910`，`/Users/lizeyu/Documents/ChatGPT/投资/.worktrees/quantmind-tushare-document-throughput`，`9ce875e01b6f9bb3474c26fd58c245d925c1682d`
- 分工：仅负责 `backend/shared/tushare_documents.py`、相关测试和本候选协作记录；不触碰生产、凭据、远端配置、worker 并发度、磁盘保护或其他开发任务。
- 接续：`20260910T022030Z-mac-document-throughput-readonly-structured.md`

目标：先增加可观察的 phase/DB wait 耗时；只有在不少于 100 万行的 SQLite 代表性基准中确认有收益，且未来 retry/claim 语义保持时，才加入有序 eligible-claim 索引/查询。
验证计划：Python 3.10 文档队列定向测试、Ruff、`git diff --check`；仅本地临时 SQLite，不读 Token、不访问上游、不写正式数据。
