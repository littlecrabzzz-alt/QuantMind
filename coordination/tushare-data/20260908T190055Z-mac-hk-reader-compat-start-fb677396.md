# 港股遗留读取兼容
- remaining_markets，Mac隔离codex/tushare-other-markets，基线69bc483。仅改store.py与test_tushare_other_pipeline.py；父继续独占pipeline.publish。
- 固定release读取视图在去重/过滤前，对hk_*数据集五位!?后缀HK做保守canonical projection，保留source_*与!，不改原始/Parquet/manifest和as_of语义。
- 新夹具含旧/新两份同退市标的观察与同号码当前标的；验证只保留HK00013!和HK00013及历史时间切片。
