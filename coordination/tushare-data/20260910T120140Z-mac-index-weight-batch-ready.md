# Tushare index_weight 精确批次候选就绪

- 基线 `ca9fdaf3`；分支 `codex/tushare-index-weight-batch`，独立 worktree；只读权威队列，无 Token、无上游、无生产写入或发布。
- 11:50Z 审计：empty 312、pending 96,849、split_pending 90；capability `available`，当前分层限速解析 500 rpm。history 当时 pending 87,497、199 指数；持续 planner 到生成候选时变为 87,870、200 指数，故全集未闭合。
- 固定 360 个现有 history/pending task ID，覆盖 200 指数及 2026-08-01—2026-09-01；manifest SHA `526027196072ab9d51a6303de81cdfcdcadcb09d0b6c742ac0dda89fb00923c1`，task-set SHA `8342c8d55a5b642608d5316f99256297893a758d09b9b2759459c46f1c4ae784`。
- 默认 plan-only；execute 需任务/配置/runner 三重 SHA、authority/schema6/ENABLED/共享锁/100 GiB 门槛，最多 360 请求或 90 秒，不发布、不切 CURRENT。
- 估计 45—90 秒，非空留存约 59—66 MiB，按 100 MiB 预留。known_at、指数全集、历史下界和单日饱和闭包均继续未验证，不能解除 PIT/`blocked_data`。
- 验证：专项 unittest 5 项通过，ResourceWarning 升级为错误仍通过；Ruff 和 JSON/diff 检查通过；真实清单离线 plan-only 复核通过。
