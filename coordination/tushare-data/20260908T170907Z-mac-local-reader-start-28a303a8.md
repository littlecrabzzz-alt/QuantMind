# 固定 release 本地读取扩展：开始

- Mac / text_contracts 第三子任务；codex/tushare-text；worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-text。接续 20260908T170625Z-mac-document-helper-11a20555.md；主执行者明确移交 tushare_store.py 本轮归属。
- 仅编辑 backend/shared/tushare_store.py 和新增 scripts/test_tushare_store_extended.py；允许 cherry-pick 已提交结构化/市场契约供读取，不编辑契约、pipeline、mirror、文档下载器或 API 路由。
- 目标：保留原七类，按九文本/二十六结构化/二十三市场契约支持固定版本的 schema、字段、日期/标的/关键词/观察时间筛选和 JSONL 导出，禁网络回退；不同正文版本不误合并。
- 验证将在临时目录使用模拟 Parquet，禁生产网络及凭据。as_of 仅本系统观察时间，不代表历史 PIT。完成后独立提交供主执行者集成。
