# 技术指标/筹码/备用行情纯候选开始
- Mac，remaining_markets；codex/tushare-technical-extra，基线8c2e938，隔离worktree quantmind-tushare-other-markets。
- 范围：stk_factor296、stk_factor_pro328、cyq_perf293、cyq_chips294、bak_daily255；均263基线未注册真实API，非别名。
- 仅新增 backend/shared/tushare_technical_extra_contracts.py、scripts/test_tushare_technical_extra_contracts.py、docs/tushare-technical-extra-intake.md。
- 不改运行模块、目录、台账或配置；无上游数据调用/生产访问。优先复用_contract等纯helpers，明确全字段/复权/PIT/权限/分片未知。
- 下一步官方表格核查、纯惰性planner与离线测试，提交push供父后续批量集成。
