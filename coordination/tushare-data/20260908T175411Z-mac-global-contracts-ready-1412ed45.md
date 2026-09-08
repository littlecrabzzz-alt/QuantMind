# 港美股及周月线契约可集成

- Mac / text_contracts；独立worktree quantmind-tushare-text，分支codex/tushare-text，提交1d87b23cc4d55c8a2300678604d93c776ce17d35。
- 接续20260908T174431Z-mac-global-contracts-start-2fcc6487.md。仅新增 backend/shared/tushare_global_contracts.py、scripts/test_tushare_global_contracts.py、docs/tushare-global-intake.md。
- 17个API，全官方输出字段含隐藏项；GLOBAL_CONTRACTS、iter_global_jobs、global_prerequisites。近期优先、历史日期交错、L/D/P及US空分类、周期未来标签；单日满页支持stocks/indexes/hk_stocks/us_stocks发现family。全生产权限未验证；独立港美股行情权限不能由10100积分推定。
- 验证：9项离线测试通过，Ruff format/check通过。未调用生产API/凭据/业务数据/服务。
- 缺口：us_basic官方list_stauts拼写/offset原点待实测；示例EQ/EQT冲突；us_adjfactor包含ARC且15000满页；未知历史下界必须显式范围或后续证据，不宣称全覆盖；旧复权因子需单独周期全历史revision sweep。
- 父下一步：cherry-pick提交，注册global family与历史范围配置；增加hk_stocks/us_stocks发现读取和饱和拆分；按docs完成权限探测/分页原点验证。父拥有registry、ledger、pipeline及发布，本子任务未改。
