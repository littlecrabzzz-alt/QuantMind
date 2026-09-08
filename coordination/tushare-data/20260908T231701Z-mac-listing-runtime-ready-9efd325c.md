# listing_extra4运行候选交接
- remaining_markets Mac独立codex/tushare-listing-runtime；基线父3dc7567+8ea0199纯合同；只交运行delta c8783a09ea0272e99d11b28f3d0cfe1692631dca，不重复merge。无生产访问。
- 六文件：registry/store、pipeline仅import/identifiers/prereq/初始validate tuple、mirror模块名单、新test_tushare_listing_extra_pipeline.py、store全合同数量140→144。未改主planner/helpers、catalog、ledger、schema3/document/router/archive/生产。
- enable_listing_extra默认关闭；listing_extra_apis/listing_extra_history_start复用纯计划与签名机制。bak_basic/new_share/bse_mapping发现独立historical_listing_securities，保留T和BSE两码且并集既有stocks；不改旧stocks集合。daily_info 31官方类别和观测类别进入独立market_stat_categories，绝不进股票/指数代码集合。
- 复用generic ts_code fanout：bak_basic历史集合、daily_info类别（原日期/请求维度保留）；均coverage_proven=false/universe_unverified。new_share范围按ipo_date二分；其单日或无筛选快照、BSE快照、单统计类别cap实际run都blocked，无伪offset或code子任务。
- fixed-release store：IPO默认日期ipo_date，issue_date可显式查询；BSE o_code/n_code原.BJ只在双映射列视图且选择对应code_field时可筛选，默认ts_code后缀仍拒绝；metadata给date_axis_note/namespace_note/history_gap。list_date依旧上市日，不能当代码变更生效时点；不重写历史代码。
- 50 tests passed：listing纯8+新运行6、store6、planning14、trading16；Ruff/diff-check过。完整字段/未知源字段/负值null/重复观察/未来上市/不同映射源行/独立板块发现都已MockTransport→normalize→publish→store离线验收。
- 仍待实测权限/字段（daily_info深圳tr缺列保留schema_gap）、主表完整性、旧修订、PIT、IPO截断发现和BSE变更有效期证据。历史类别起点是供应商表范围，非全scope完成证明；父review后再probe/部署。
