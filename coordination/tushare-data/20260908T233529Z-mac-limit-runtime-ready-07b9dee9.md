# limit_extra4运行候选交接
- remaining_markets Mac独立codex/tushare-limit-runtime；基线父f2cd52e+纯cd1da8a，增量91fc460042b5c613ba785235ecae7040e8d21f87。父旧listing说明merge冲突保留父新增尾段，不重复交付基线merge。
- 只改6文件registry/store/pipeline import+normalize概念单分支+identifiers+prereq/初始validate、mirror模块名单、新test_tushare_limit_extra_pipeline.py和store全合同fixture。未改intake/documents/catalog/ledger/主有限planner/生产。
- 5池/3类请求身份贯通业务job→capture→normalize→publish→store。同payload跨请求仍独立，多理由源行保留；缺limit_type身份固定release读取拒绝。全合同fixture新增THS/D各自immutable请求记录，数量144→148。
- 6hidden字段实际显式发送，合法null保留，整列缺失产生schema_gap/requested_missing_fields。未知源列、nums/rank/up_stat源字符串、source_ts_code都保留。
- 股票limit_securities并stock/T/历史listing/trading及榜单观测；cpt独立limit_concepts，raw .TI保留且不套股票规范化，未知stock-shaped概念标签也不改成股票。未知标签合法性/按code查询适配仍须实测，未假称授权。
- 饱和复用日期/标的拆分，limit_type/market/exchange等请求维度不丢，universe_unverified持续；单日单代码cap真实run保持blocked。ST排除仍写category_gap，不能称全股票榜单完整。
- 43tests passed（纯8/新运行7/store6/planning14/extended8），Ruff/diff-check通过。全部MockTransport/temp隔离、无secret/network/生产访问；待父下一轮review/pick及实测五池拼写和权限，不参与当前迁移。
