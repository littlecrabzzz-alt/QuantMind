# 信用交易7接口纯合同开始
- remaining_markets / Mac / codex/tushare-other-markets；合入共享基线8249f6c，复用已有T历史股票校验；接续20260908T204509Z-mac-futures-seams-next-seven-readonly.md。
- 仅负责新增backend/shared/tushare_credit_extra_contracts.py、scripts/test_tushare_credit_extra_contracts.py；父继续13接口运行接入与HTTP兼容；不动registry/pipeline/store/台账，不请求生产API。
- 7接口 margin/margin_detail/margin_secs/slb_len/block_trade/pledge_detail/pledge_stat，官方参数字段已核查；惰性历史/近期，保留ETF+股票、退市与T代码、日期轴和未知权限/历史/同值交易身份缺口。
