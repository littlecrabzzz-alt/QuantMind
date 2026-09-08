# Tushare tick 顶层计时交接
- 节点/分支：Mac codex/tushare-structured；已合入父 228db0d。
- 候选提交：e1f2591bc46e1964e0ecd3197870ca0cd5fc62d8；仅 tick 函数及 scripts/test_tushare_tick_timing.py。归属释放；未部署/改配置/生产请求。
- 接续：20260908T205848Z-mac-throughput-review-structured.md 和本轮 tick-timing-start。

现有返回 report/pipeline-status.json 新增 timing：stage_seconds（initialize 含构造、planning、archive、acquire、可选 document_registration/documents、publish、close）、completed_stages、failed_stage、total_elapsed_seconds。总值包含入口准备与 close，截止报告序列化前；elapsed_seconds 仍保留原采集含义。reconciliation 在原 run 内，included_stages 明确归入 acquire，未移动/重复调用。异常仍抛出，状态仅记录类型，不记录异常文本；失败报告写入故障不能掩盖原异常。提前 disabled/资源/凭据/锁拒绝返回仍原样。

验证：5 专项 + 17 原 pipeline + 3 extra pipeline 测试通过；Ruff/diff 检查通过；AST 确认其他顶层/class 方法完全未改。临时目录+mock、禁网络。正常/逐阶段错误/报告写失败/inline documents/显式预算/提前退出覆盖。

限制：无每请求写库或状态写入；硬杀/OOM 无法保证本轮计时落盘；未单独测 class 内 identifiers/expand/reconciliation；未证明实际提速。父集成后只需观察正常两轮 timing 以定位 90 秒外耗时，不需修改调用参数。
