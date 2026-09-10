# Tushare realtime/TMT bounded probe candidate start
- 时间、节点、任务标识：2026-09-10，Mac，realtime-tmt-probe
- 状态：进行中
- 分支、worktree、提交：`codex/tushare-realtime-tmt-probe`；`/Users/lizeyu/.codex/worktrees/QuantMind-tushare-realtime-tmt-probe`；基线 `bec7e6aa`
- 分工：仅新增 `scripts/tushare_realtime_tmt_probe.py`、对应离线测试和本任务证据；父任务负责生产执行、配置和发布。
- 接续：已合入的 5 个默认关闭合同 `f6e43f4f`。

实现最大 8 次、120 秒、默认 dry-run 的权限/字段/饱和/过滤探针；实时只用固定发布中验证的实际 stock/ETF 种子，TMT 只用官方产品 1..65 且窗口不超过 30 个月，动态过滤只从本次原始响应派生。执行要求 helper SHA、权威根、非阻塞 pipeline.lock、schema6 和 tiered_v1 gates；不自动启用或改配置。
验证：本阶段不访问生产、Token 或 Tushare 上游。
下一步：完成离线测试、Ruff、候选提交并提供父任务生产命令。
