# 首5补充接口纯契约
- remaining_markets，Mac隔离codex/tushare-other-markets，基线d8424c9。接续下一批12核查记录c107c921。
- 独占新增 backend/shared/tushare_supplement_contracts.py、scripts/test_tushare_supplement_contracts.py；父持有registry/pipeline/store/coverage及生产集成。
- 仅moneyflow_mkt_dc/moneyflow_dc/moneyflow_ths/etf_share_size/mkt_idx_bmk五只读API；官方字段/日期轴/权限未知保留。复用stocks/funds/indexes饱和发现family，宏观大盘逐年度、个股/ETF逐日、基准无过滤+双层目录。
- 纯规划离线测试，不发API或访问生产；完成后交接delta。
