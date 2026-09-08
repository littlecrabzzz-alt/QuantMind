# Tushare 顶层批处理阶段计时候选
- 节点：Mac；codex/tushare-structured；已合入父 228db0d。
- 归属：仅 backend/shared/tushare_pipeline.py 的 tick 与新 scripts/test_tushare_tick_timing.py；不修改其他 class 方法、配置或部署。
- 接续：20260908T205848Z-mac-throughput-review-structured.md。
- 方案：标准库 monotonic 顶层计时，保留返回字段与异常传播，错误报告保留阶段。reconciliation 在 run 内，明确 included_in_acquire，不新增调用或虚构独立计时。
- 验证：隔离临时目录和 mock，无网络或生产数据。
