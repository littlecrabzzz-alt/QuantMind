# Tushare：RRG etf_limit 后代精确运行器待交接

- 时间、节点、任务标识：2026-09-10 09:53:52 UTC，Mac，rrg-descendant-runner
- 状态：待交接
- 分支、worktree：`codex/rrg-descendant-runner`；`/Users/lizeyu/.codex/worktrees/quantmind-rrg-descendant-runner`
- 分工：只新增后代 plan/runner、测试、说明和脱敏证据；未调用生产上游、未写生产、未发布或切换 `CURRENT`

云端 schema 6 只读 plan 在 09:53:20Z 观察到 48 个 `split_pending` 父任务、134 个唯一后代，其中 115 个 `pending`。一层为 77 pending/19 split_pending，二层 38 个全部 pending，所有任务优先级 24。完整任务状态在本地 plan 产物，摘要与哈希见 `docs/tushare-rrg-descendant-plan-20260910.evidence.json`。

运行器默认只读 plan；执行前在共享锁下重算完整图并核对 authority/config/helper/task-set 四项哈希、schema 6 和 100 GiB，沿用 360 次/90 秒硬界、既有频控与日额度。图继续扩展会改变 task-set 哈希并拒绝旧计划。

验证：18 项目标及相邻单测通过，Ruff check/format check 和 JSON 校验通过。下一步由集成人合入并部署脚本，重新生成最新 plan 后才决定是否执行；生产执行不属于本提交。
