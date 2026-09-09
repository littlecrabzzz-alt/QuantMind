# 股票上下文7纯契约候选开始
- remaining_markets，Mac新独立worktree quantmind-tushare-stock-context，codex/tushare-stock-context，基线a68c6d9。
- 仅新增 backend/shared/tushare_stock_context_contracts.py、scripts/test_tushare_stock_context_contracts.py、docs/tushare-stock-context-intake.md。
- API stk_premarket329/stk_managers193/stk_rewards194/stk_auction_o353/stk_auction_c354/stk_nineturn364/stk_ah_comparison399，现有合同未重复。公告/报告期/竞价/特殊代码及全部字段分别核查。
- 不改runtime/registry/store/pipeline/config/ledger/生产，不调用数据API；复用纯helpers，权限与历史缺口不推断已授权。
