# 风险5 runtime候选开始
- Mac remaining_markets，codex/tushare-risk-runtime，基线e87dc2b；pure1e701c6等价pick621c1fe。仅独立worktree，不改共享主树源码/生产/配置，不probe/enable/停写。
- own registry/pipeline/store/mirror风险接线、新test_tushare_risk_event_pipeline.py、store159全合同fixture、docs/tushare-risk-event-intake.md必要增量；父DC部署期间不编辑这些接线位置。
- 复用现有纯planner/lazy公平队列；registry仅为st stocks依赖适配risk_stocks（包含历史与观察），独立risk_securities含ETF/基金/alert用于饱和，不污染其他family stocks。store按本风险组合同明确默认日期轴st pub_date/alert start_date；保留未知历史/1000饱和/来源代码/PIT。
