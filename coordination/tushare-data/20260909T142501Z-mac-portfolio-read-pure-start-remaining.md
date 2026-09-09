# 自选组合只读 2 API 纯候选

Mac remaining_markets；基线 6b18287，分支 codex/tushare-portfolio-read，独立 worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-portfolio-read。只新增 backend/shared/tushare_portfolio_read_contracts.py、scripts/test_tushare_portfolio_read_contracts.py、docs/tushare-portfolio-read-intake.md。

本地官方446/449完整 HTML：p_list5列、p_get8列，均 defaultY；p_get只读成分查询，name来自真实p_list观察，id不是合法输入。不含p_save/p_delete，不创建修改组合。计划只读同epoch快照，历史/分页/cap/rpm/权限未知保留；空列表是有效无组合观察，私有内容不输出。复用既有纯helpers，默认关闭，无runtime/上游API/生产操作。父持有运行接线文件。
