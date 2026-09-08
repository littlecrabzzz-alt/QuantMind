# 股东与事件7合同增量
- Mac remaining_markets，codex/tushare-other-markets，已merge父b199eab；HK !AE新实测修正以父master为准解决旧cherry-pick合并冲突，未丢弃新语义。
- 独占新 backend/shared/tushare_equity_event_contracts.py 和 scripts/test_tushare_equity_event_contracts.py；不改supplement/registry/pipeline/store/ledger，父负责集成。
- API仅dividend/stk_holdernumber/stk_holdertrade/repurchase/share_float/top10_holders/top10_floatholders。官方各日期轴、隐藏字段、无分页/未知cap与权限gap保留；纯planner/临时离线测试，无生产访问。
- 接续12候选核查c107c921，完成后提交独立delta与接入说明。
