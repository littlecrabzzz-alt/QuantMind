# 龙虎榜与游资4接口纯合同交接
- Mac remaining_markets；codex/tushare-trading-events；基线 eb3bf64，增量 4d2f953；已完成，无生产访问。
- 仅新增 backend/shared/tushare_trading_event_contracts.py、scripts/test_tushare_trading_event_contracts.py、docs/tushare-trading-event-intake.md。范围与开始记录 20260908T223506Z-mac-trading-event-contracts-start-daa5b4df.md 一致。
- top_list106/top_inst107/hm_list311/hm_detail312；全部权限 unprobed。37已核查字段，hm_detail.tag required+nullable，显式 requested/job fields；原自然键原因/席位side/游资标签保留不同源行，identical multiplicity保持gap。
- history：top_list按官方2005年、hm_detail按2022年8月规划下界（非verified首日）；top_inst未知下界仅近期或配置范围；hm_list仅近期快照。7自然日recent然后按API轮转历史日，无假offset/开市过滤。
- 父接入必要：group trading_event；config trading_event_apis/trading_event_history_start回退history_start。stocks加历史/退市/T及observed trading_event_securities发现；hm_name二级分区仍须专门接线并审查名单完整性。全scope/PIT/修订/饱和均未解除。
- 明确阻断：原hm_list catalog误含示例名 zhouyu1933/bike770/Asking。enqueue取catalog与合同字段并集，接线前须定点修catalog或字段override，纯合同正确不足以避免错误请求；保留原证据和分母。本提交不改catalog/runtime/ledger。
- 验证：python3 -S -B scripts/test_tushare_trading_event_contracts.py 10 passed；Ruff check通过。4页官方hash与固定证据一致，详见新增doc。待父review/cherry-pick并集成，不能计作已运行4API。
