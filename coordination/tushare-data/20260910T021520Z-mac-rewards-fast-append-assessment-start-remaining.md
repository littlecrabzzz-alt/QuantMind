# stk_rewards 新观察组合有限快追评估

- 承接父：生产新已观察合法 pair=393、planned=54，冻结 recent/history 本轮各推进500。仅只读两个 planning_state 及白名单配置，使用独立 worktree 纯planner计算确切剩余枚举量；不构造生产 Pipeline、不访问上游或凭据、不改任务、游标、配置或服务。
- 首选评估自然完成的剩余步数/条件时间；若有限追加确有必要，先向父报告具体公共文件接点，再在独立候选实现，不争正在处理的 publish/documents。
- 本阶段只持有 `/tmp/rewards-frozen-progress-*` 与独立短报告，现有 `codex/tushare-stock-context-invalid-gap` 干净树仅作只读代码基线。共享 master 已8193d14。

- 02:15:07Z 只读观测：recent offset1000/prefix6317，剩5317（11轮满500）；history offset7317/total21496，剩14179（29轮满500，其中managers13079/nineturn1027/AH73），冻结54对。旧history完成至少7h15m条件时间，另需刷新轮，不是900秒必追上。
- 因此实现最小候选，独立新分支 `codex/tushare-rewards-period-fast-append` 基线8193d14，复用同隔离worktree。新增独立scope仅历史已观察pair、不读取股票全集；仍属stock_context采集组和稳定history任务ID。归属 registry append声明、pipeline _planning_inputs精确alias依赖与plan_extended有效族选择/mode/budget接点、新专项test及已有rewards doc；不碰publish/tick/documents或其他族算法。已向root报告文件边界。
