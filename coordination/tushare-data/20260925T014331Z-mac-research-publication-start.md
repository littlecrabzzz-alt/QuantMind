# 重点结构化数据独立发布
- 节点：mac；状态：进行中
- worktree：QuantMind-worktrees/research-data-priority-20260925；branch：codex/research-data-priority-20260925；base：9a245d2a
- 分工：backend/shared/tushare_pipeline.py、scripts/tushare_research_cache.py、scripts/tushare_archive_worker.py、相关发布/缓存测试与 docs/research-data-priority.md、结果记录。
- 接续：20260924T180249Z-mac-research-data-priority-complete.md。
复用现有发布器，给 15 个重点 API 独立不可变版本与 RESEARCH_CURRENT 指针；正文索引与全量归档保留原入口。仅在独立 worktree 编辑。保留 R01 P0 任务的全部修改与固定数据版本，不启停它的计算服务。
验证后再占 native archive/source 升级窗口；在途采集与文档任务自然排空。云端仅验证既有研究缓存消费，不更换 R01 输入或执行实验。
