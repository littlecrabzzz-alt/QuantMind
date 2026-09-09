# 涨跌停专题4接口纯候选开始
- remaining_markets Mac独立codex/tushare-limit-extra，基线c8783a0；only own新增backend/shared/tushare_limit_extra_contracts.py、scripts/test_tushare_limit_extra_contracts.py、docs/tushare-limit-extra-intake.md。
- 从263+13与144注册对比，选择limit_list_ths355/limit_list_d298/limit_step356/limit_cpt_list357；四页官方核查，无别名/已接入重复。其他agent字段审计不改这3新文件。
- THS六隐藏列/五池，D接口三分类且排除ST，step/cpt未知历史起日、cpt .TI独立板块与股票隔离；保留PIT/权限/饱和gap。
- 不改registry/pipeline/store/catalog/ledger/runtime/生产/RRG；不调用上游API。
