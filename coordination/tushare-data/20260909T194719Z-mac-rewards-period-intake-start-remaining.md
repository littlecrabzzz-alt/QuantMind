# 接入线A：stk_rewards 已观察报告期补采
- remaining_markets独占 backend/shared/tushare_stock_context_contracts.py、registry stock_context依赖/映射块、pipeline identifiers的end_date投影与stk_rewards行分支、新scripts/test_tushare_rewards_observed_periods.py、docs/tushare-rewards-observed-periods.md。
- 独立worktree quantmind-tushare-rewards-observed-periods，branch codex/tushare-rewards-observed-periods；代码基线4446d36，创建时origin/master已追加2a6e462协调记录（无runtime变更）。不动init/next_job/tick/publish/通用planner预算/缓存/配置/ledger。
- 当前离线重算236具名/227注册，9未注册仍为Connect4官方合同失效、私有组合2、写操作2、SDK入口1；保存 /tmp/tushare-line-a-scope-4446d36.json。选择已probe未enable的薪酬合法end_date补采；官方194本地原文SHA f640e1ef2120aab9af52459fa460e9cbdbd34bae02bd473c9abdb9e6256bef19。
- 保留code-only发现，每个实际code+period只从本API已保存jobs∪attempts原文观察产生；无猜测季度、ann/range/offset。历史稳定任务+最近已见报告期刷新；原父cap/未知期间全集/PIT gap不清除，不自动enable。
- 无生产/API/Token访问；父已同意方向，structured已通知identifier最小接点，由父串行整合。
