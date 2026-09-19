# 附件批次磁盘预算

Mac：负责 scripts/tushare_archive_worker.py、scripts/test_tushare_archive_worker.py。隔离 worktree /private/tmp/quantmind-document-disk-budget-20260919。

用户要求本地至少预留 200 GB。现有 300 GiB 仅在轮次入口检查；2500 项 × 256 MiB 的附件批次理论超过 100 GiB 缓冲。拟按每次启动附件阶段时的空闲空间，扣除 300 GiB 后，以单附件上限加解析输出上限计算本轮最大阶段数。磁盘充足时保留当前吞吐。业务后端由其他 agent 负责，本任务不改业务服务。
