# Tushare：目录下一批离线接入开始
- 时间、节点、任务标识：2026-09-10，mac，catalog_next_batch
- 状态：进行中
- 分支、worktree、提交：`codex/tushare-catalog-next-batch`，`/Users/lizeyu/.codex/worktrees/QuantMind-tushare-catalog-next`，基线 `9ce875e0`
- 分工：审计固定目录与覆盖台账；选择不超过 8 个目录内未实现或实现不完整接口；负责新增契约模块、registry/planner/store/query 接线、离线测试及本候选记录。主工作树、凭据、Tushare 上游和生产均不触碰。
- 接续/更正：接续 `docs/tushare-progress.md` 中全量本地化长期任务。

本次先以固定官方目录字段为唯一字段证据，复用现有 pipeline/store 机制；权限、字段或分页尚未真实验证的接口默认关闭并保留显式缺口。
验证：待完成 Python 3.10 相关与全量 Tushare 测试、Ruff、diff check。
下一步：按覆盖状态和本地复用价值确定批次并实现。
