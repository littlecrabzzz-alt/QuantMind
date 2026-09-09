# 股票历史/发行/代码变更/市场统计4纯合同开始
- Mac remaining_markets，独立codex/tushare-listing-extra，基线b5b6a80；只own新backend/shared/tushare_listing_extra_contracts.py、scripts/test_tushare_listing_extra_contracts.py、docs/tushare-listing-extra-intake.md。
- 已与共享263基线+13discovered和140注册对比，选择bak_basic262/new_share123/bse_mapping375/daily_info215；不会把VIP aliases当未实现API。避开Connect旧4和龙虎榜4。
- 仅读5页官方：stk_premarket329明确独立开通，用户现有权益未证实此项，暂不选入。不改runtime/ledger/catalog/production，不请求生产API。
- daily_info保存目录误把板块代码表当input_fields；纯合同纠正输入、保留31板块各自起日为元数据；不编辑catalog。new_share发行日与上市日不同、bse_mapping上市日不是代码生效日，均保留源语义。
