# 技术5运行候选就绪
- remaining_markets，Mac隔离codex/tushare-technical-extra，基线8c2e938；按07a7fde纯→c36f629运行pick（已有pure只pick后者），已push origin，worktree clean。
- 7文件：registry/store/mirror，pipeline仅18新增行(imports/identifiers/record_extra_planning_gaps/plan_extended验证tuple)，新增专属runtime tests、store fixture数量159→164、候选doc。不改__init__/next_job/publish/interval或其他planner，AST逐方法对比确认。
- technical_extra显式flag，technical_stocks独立发现族合并历史挂牌/退市T/股票事件+已存daily/daily_basic/adj_factor/本组来源含饱和attempts，不掺ETF/概念目录也不改变其他stocks集合；cyq逻辑stocks适配为该族，缺发现/不完整/坏代码保留family gap。
- 所有342列显式请求，固定read/schema/export默认trade_date；cyq键ts_code/trade_date/price并保留不同原始行；其他按ts_code/trade_date+rowidentity。源代码/负值/null/未知列/复权units与逐字段gap保留。bak未启用未验证offset分页，单股单日满cap仍blocked。
- 无SQLite/Parquet/manifest schema变化、无旧release重写或语义变化；无enable/probe/生产写入。权限仍unprobed，历史和PIT不宣称完成。
- 全Tushare隔离456 tests通过21.199s（新增6runtime+8pure），Ruff/diff通过；日志/tmp/tushare-technical-runtime-tests.log。父后续组合风险5+技术5+text公平候选审查/统一发布，当前候选不需暂停采集。
