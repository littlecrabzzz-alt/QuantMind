# Mac Tushare 发布扫描优化开始

- 当前生产全量 worker PID 24039 正常运行；最近真实周期完成 750 次供应商请求和 2500 个文档任务，无失败阶段。
- 上一轮完整发布耗时 788.345 秒，其中 `scan_attempts_and_stat` 282.686 秒、`document_index` 225.245 秒；序列化仅 5.541 秒。
- 本轮候选仅优化发布扫描实现：保留每次完整目录核对、孤儿文件纳入、不可变文件校验和发布字节语义；不改 Token、权限门、采集频次、队列状态与本地完整归档所有权。
- 代码范围：`backend/shared/tushare_documents.py` 及直接回归测试；分支 `codex/tushare-publish-scan-20260918`，独立 worktree 开发。
