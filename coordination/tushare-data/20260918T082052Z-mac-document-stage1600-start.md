# Tushare：文档阶段 1600 灰度开始
- 时间、节点、任务标识：2026-09-18，Mac，document-stage1600
- 状态：进行中
- 分支/worktree：接续 `codex/tushare-document-parse2`、`/private/tmp/quantmind-tushare-document-parse2`
- 分工：仅扩展归档/Celery 文档阶段配置有界上限及相关测试和说明
- 接续：`20260918T080503Z-mac-document-parse2-start.md`

双路解析三个连续生产周期均完成 1000 阶段，下载/解析为 511/489、503/497、477/523；解析活跃仅约 62/77/74 秒，真实请求 615/613/641，失败阶段为空。当前瓶颈已从解析资源转为 `document_worker_max_documents=1000` 配置硬上限。

代码上限计划从 1000 扩到 2000，生产只灰度 1600；100 秒总截止、6 下载、2 解析、单子进程资源上限、主线程事务、磁盘保护和限速不变。先验证 2000 接受、2001/非整数拒绝，再观察连续真实周期。
