# 主题：R01-P0.3 H1 验收缺陷修复·导出侧（p03_execution I1E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-I1E1（wave I1 attempt 1）
- 状态：**done**（H1-AC01 + H1-AC02 导出侧）
- 提交：`herdr/r01-p0` @ `57d4fc21c9aca96c06153934d6204fb817fc560f`（仅 owns 2 文件）
- 证据：`<run>/artifacts/p03/h1/fixes-i1/`（probes.json 前后对照+逐日对齐、probe_ac01.py）；`view-fields-v2.md` 字段合同；sample-511090-5day-view.json 已重生成（view_schema=2）

## 要点

1. **H1-AC01**：days[].risk.status/high_water_mark 改取当日 equity 快照（缺字段显式 ViewBuildError，禁止最终态补历史）；顶层 risk_state 保留最终态；探针（损失线 100 验收场景）逐日 native vs view 全对齐、状态切换存在、HWM 单调。
2. **H1-AC02**：持仓收盘标记字段 mark→**last_mark**（与页面消费字段统一），mark_source/stale_days 语义保留、真缺失不伪造；验收引用日期 04-24=113.031/04-29=110.685 与原生逐日全对齐；view_schema→2，字段合同见 view-fields-v2.md（原生 evidence 规范化归 p04 适配层）。
3. 测试 15 用例（+4：逐日风险切换/缺字段拒绝/last_mark 两日期+全窗口/陈旧语义）；全量回归 **302 passed**；v2 十窗口 ALL_PASS 不回归；AB-QUICKSTART 字段同步。
