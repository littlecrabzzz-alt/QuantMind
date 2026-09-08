# 其他资产及国际宏观契约增量
- Mac 子任务 remaining_markets；隔离 worktree `/Users/lizeyu/.codex/worktrees/quantmind-tushare-other-markets`，分支 `codex/tushare-other-markets`，基线 39fff3d。
- 独占新增 backend/shared/tushare_other_contracts.py、scripts/test_tushare_other_contracts.py、docs/tushare-other-intake.md。父任务负责 registry/pipeline/生产实测，其他 agent 负责分区闭环和只读 API。
- 按 docs/tushare-integration-plan.md 核对期权、贵金属、外汇和国际利率官方参数、隐藏字段、历史与饱和边界。使用 ponytail skill 复用已有纯契约形状。仅离线临时测试，不请求生产 API、不部署、不操作正式数据。
- 下一步：官方文档审阅、实现与验证后提交交接。
