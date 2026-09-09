# 技术指标/筹码/备用行情纯候选交接
- Mac remaining_markets，codex/tushare-technical-extra，独立worktree quantmind-tushare-other-markets，基线8c2e938；仅需pick 07a7fde。
- 新增3文件：backend/shared/tushare_technical_extra_contracts.py、scripts/test_tushare_technical_extra_contracts.py、docs/tushare-technical-extra-intake.md；运行模块、目录/台账/配置/生产均未修改。
- 5真实API stk_factor296/stk_factor_pro328/cyq_perf293/cyq_chips294/bak_daily255，全342输出(35/261/11/4/31)与原目录及本次官方逐列核对；全部默认Y，所有jobs显式全fields，逐字段gap和字面计算参数保留。官方HTML及表格仅Mac /tmp/tushare-technical-docs，SHA记录于模块。
- 导出TECHNICAL_EXTRA_CONTRACTS/iter_technical_extra_jobs/technical_extra_prerequisites；config technical_extra_apis/technical_extra_history_start(兼容history_start)。筹码必须stocks依赖，近期逐股日、历史逐股月，复用日期二分；pro至少ts_code/trade_date一项，因此保持合法全市场日。其余未知下界不造日期；筹码2018年份包络不是首日证明；bak约2017年中与早期缺失留gap。
- 重点：pro BBI M4=20/21/22、pre_close差异，全部261列不删；筹码price自然键/未知算法复权；bak offset/limit合法但稳定性不明，未开runtime分页；满cap终端仍blocked。所有权限unprobed、无enable/probe/publish、无研究准入。
- 验证：python3 -B scripts/test_tushare_technical_extra_contracts.py，8项通过(1.585s)，包括现有assess_response/date_children满cap与闰月29叶保留T代码；Ruff、git diff --check通过。只纯候选，父后续审查/接线与真实验收。
