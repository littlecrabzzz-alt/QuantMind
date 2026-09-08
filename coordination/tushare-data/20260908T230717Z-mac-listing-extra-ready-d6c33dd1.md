# 历史列表/IPO/代码映射/市场统计4纯候选交接
- remaining_markets Mac；codex/tushare-listing-extra；增量8ea0199d16fd9b77a35b21daf46fb94340739c0d，基线b5b6a80。只新增listing_extra纯合同/专属测试/doc三文件，未接runtime/ledger/catalog/production。
- 对比263基线+13额外发现和140注册，选bak_basic262/new_share123/bse_mapping375/daily_info215。54官方字段/31市场类别起日，权利全部unprobed。stk_premarket329官方独立开通，用户已列权益未证实，因此只列待核实不删scope。
- export LISTING_EXTRA_CONTRACTS/iter_listing_extra_jobs/listing_extra_prerequisites；建议组listing_extra，listing_extra_apis/listing_extra_history_start回退history_start。最近7日+惰性历史轮转，new_share月内范围+无筛选近期发现；mapping仅快照。
- new_share输入范围是ipo_date，issue_date可空/未来；sub_code申购码不能当股票。单日cap无合法ts_code分页；无筛选cap也不推完整history。mapping的list_date不是代码变更生效日，不合并历史代码。
- daily_info目录误将31市场类别写成input_fields；纯合同纠正为6参数，保存类别起日元数据，不动catalog/原sha。ts_code是SH_A/SZ_BOND_CB等类别，不进股票发现；tr深圳暂无，缺整列须schema_gap待实证。
- 未闭合：bak_basic历史/T/退市+观测代码fanout需运行接线；daily_info类别/交易所饱和切分未实现；IPO/映射终端cap和未知historical/PIT/revisions保持gap。父review后方可再接运行候选，不据积分断言访问。
- 8个纯离线测试passed，Ruff通过；无Pipeline实例/上游API/生产访问。参考docs/tushare-listing-extra-intake.md及start记录20260908T230419Z-mac-listing-extra-start-0fff4680.md。
