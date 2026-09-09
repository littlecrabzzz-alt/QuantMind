# DC 两项纯候选 ready
- remaining_markets / Mac；codex/tushare-dc-extra，commit523d32bee4a380ee6d3f91e0f52d327de50c1ed2；仅新增 tushare_dc_extra_contracts.py、test_tushare_dc_extra_contracts.py、docs/tushare-dc-extra-intake.md。父已有concept基线后只pick本delta，不重复concept提交。
- 目录263+13发现逐项对照：363 dc_member、382 dc_daily 均未在148生产+concept4候选中，acquisition同名无别名差异；不改catalog/ledger/runtime/生产，未probe未enable未采集，不宣称目录覆盖完成。
- 官方完整17输出/10输入已复核，默认隐藏列0，6000门槛仅候选权利。member从20241220历史每日，daily从2020年（20200101仅规划floor）逐日三idx_type；category输出与请求名称不同，按请求身份保留。组dc_extra、dc_extra_apis/dc_extra_history_start；7近期日、历史公平惰性。不依赖当前代码集，不造offset。
- 自然键member(trade_date,ts_code,con_code)、daily(ts_code,trade_date,category)；不同源行保留，daily另idx_type请求身份。DC代码独立namespace；未来dc_indices必须并入三种历史来源观测。member单日单板块饱和第二维con_code合法但现有单维运行不支持证明穷尽，保留blocked。历史日期不证明PIT/发布时刻、缺权重/生效区间；全部权限和完整性未验证。
- python3 -S -B scripts/test_tushare_dc_extra_contracts.py：7 tests passed；Ruff、diff-check通过，无Pipeline/网络/生产。下一步父独立review后另安排runtime与有限真实probe，采集持续不因纯候选暂停。
