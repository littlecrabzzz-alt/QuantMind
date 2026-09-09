# 股票风险状态与交易所提示5接口纯候选开始
- Mac remaining_markets / codex/tushare-risk-event，基线94d66a1；DC runtime归属已交还父。本次仅新增backend/shared/tushare_risk_event_contracts.py、scripts/test_tushare_risk_event_contracts.py、docs/tushare-risk-event-intake.md。
- 比对263+13目录及152生产+DC2候选，stock_st397/st423/stk_shock451/stk_high_shock452/stk_alert453均未注册、无查询别名重复。仅纯合同+离线tests，不触runtime/ledger/config/生产，不probe/enable，不暂停采集。
- 官方原文已存/tmp/tushare-risk-docs/{397,423,451,452,453}.{html,txt}；5cap1000，完整29输出默认Y。stock_st日状态从20000101，st公告与实施双轴且无range，shock输出trade_date为公告日/period异常期，alert输入trade_date为提示起始/输出end_date为参考截止（含ETF样例）。全部权利unprobed，历史/PIT/退市/ETF发现缺口保留。
