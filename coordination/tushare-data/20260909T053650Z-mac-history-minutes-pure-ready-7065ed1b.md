# Historical minutes7 pure candidate ready
- Mac独立worktree quantmind-tushare-history-minutes，codex/tushare-history-minutes，基线79f4498；增量bd197c8已提交push，只有声明3新文件。无runtime/catalog/ledger/config/production或source probe。
- stk_mins/etf_mins/idx_mins/sw_mins/ft_mins/opt_mins/hk_mins全58输出，0隐藏，freq严格1/5/15/30/60min且成为不可变请求身份。日期参数仅带秒start/end；原始trade_time含T/空格与跨日不改交易日，不猜时区或session。
- 官方主差异：SW页469 cap5000但权限表290写8000，取5000且保留冲突；ft/opt有oi；SW amount在vol前且volfloat；ft/opt误称股票代码，HK样例16:10，opt样例时间用T；ETF/指数/HK具体授权套餐映射仍未知。8份原文SHA保存，原文/tmp/tushare-history-minutes-docs。
- 所有权限unprobed；10100积分不等于分钟权限；HK120分2次试用未消耗。2009/2010/2015仅广告年份，不伪造精确最早时间；全scope留gap。
- 纯family history_minutes，7个隔离minute_*发现族；默认5freq。recent为today前7完整wall dates，历史仅显式scope，按最多一wall date时间窗口惰性轮流规划、共享午夜端点。端点包含性/更细饱和仍需实测，不能用理论bar数证明完整。
- 未来runtime注意：history_minutes_frequencies必须加入本family规划签名；现有helper不会自动包含；固定reader精确trade_time筛选/身份也待专项。未接运行模块，不启动全市场分钟下载。
- Python3.10.19专用8tests通过0.006s，socket/DNS禁止，Ruff/diff-check通过。可仅pick bd197c8审查；文档docs/tushare-history-minutes-intake.md，工作树清洁。
