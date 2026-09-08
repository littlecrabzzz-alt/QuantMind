# 首5补充接口契约交接
- Mac remaining_markets，codex/tushare-other-markets，提交b1a417d86f0bdad0c0a8573099049bfaccf131f4，worktree clean；仅两个约定新增文件。接续20260908T192714Z-mac-supplement-contracts-start-30e748d8.md及12候选核查c107c921。
- 导出SUPPLEMENT_CONTRACTS、iter_supplement_jobs(config,today,identifiers=None)、supplement_prerequisites；配置supplement_apis与supplement_history_start(str或API映射，回退history_start)。父注册group supplement/enable_supplement，维护planner签名和家族失败隔离，模块加入Mac mirror运行时。
- 五API按原文名：moneyflow_mkt_dc/date唯一（trade_date），moneyflow_dc/ths以及etf_share_size键ts_code+trade_date，mkt_idx_bmk键ts_code+bmk_level。全部59字段显式extra_fields；ETF隐藏nav/close；金额大盘CNY、个股与ETF规模10000 CNY，不混合来源。未声明别名。
- moneyflow_mkt_dc合法start_date/end_date年度分区（每段<=366日）与最近7日重叠；另三daily全市场trade_date，满额分别stocks/stocks/funds兜底。DC文档首日20230911，更早通用scope裁至此日；指定更晚起点保留历史裁剪gap，其他首日未知不发明。
- mkt_idx_bmk无过滤+一类库/二类库，不猜bmk_type；满500报警，由indexes逐代码兜底且全集未证。发现可并入indexes，原始000171.CSI等应按指数规范化且保留source_ts_code，不误当A股。ETF不限制两交易所，输出BSE与输入SSE/SZSE枚举不一致已记录。
- 所有输入表都没有offset/limit，合同未设pagination；权限均unprobed，minimum_points来自明细，50rpm只是保守运行上限。prerequisites即便非空发现也保留universe_complete=false。
- 6项纯离线测试与ruff通过：全scope字段、单位/来源身份、双层无过滤发现、年度/逐日闰日精确无重叠覆盖、DC首日裁剪与未知gap、配置优先级、发现全集未证和错误输入、惰性生成。无API调用/生产访问/部署，未改registry/pipeline/store/ledger。父下一步合入并有界实测。
