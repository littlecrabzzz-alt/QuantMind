# 历史分钟运行接线（默认关闭）

基于父候选 `de8e8eb` 的已审七份纯合同，接入 `history_minutes` family。七 API 为 `stk_mins/etf_mins/idx_mins/sw_mins/ft_mins/opt_mins/hk_mins`，共 58 已知输出字段，全部显式请求；未知列、原金额/量/持仓小数、null、修订均沿用不可变原文及 Parquet 保留。没有使用积分推定独立分钟权限，没有生产调用或配置启用。

配置沿用纯合同：`enable_history_minutes` 默认 false，`history_minutes_apis`、`history_minutes_history_start`、`history_minutes_frequencies`。默认五频率完整枚举，任何频率子集仍记录 scope gap。频率配置进入 policy；频率、证券发现和时间窗口按原有限 snapshot 冻结，保留有界 recent/history 游标。调用日期只是墙钟日期锚点，不代表数据源时区。

发现按数据源 API 分族，不使用一个股票列表代替其他市场。股票基本资料和历史日行情、ETF 专属资料、指数基本/行情和中信层级字段、申万全层级、期货基本/行情及 `fut_mapping.mapping_ts_code`、期权基本/历史日行情、港股基本/历史日行情，以及对应分钟原始观察分别补入七个 minute_* 列表。不筛掉退市状态、T 历史码、ETF 七位码、期权连字符、港股复用标记。中信成员的股票 `ts_code` 不进入指数集合。期货 L/L1/L2/L3/8888/9999 连续符号保留在 unmapped gap，只有实际来源合约可供分钟请求；未知全集和其他连续标记不能据此宣布排除完成。

规范码：股票沿用交易所前缀（含 T），港股沿用 HK 并保留 !；ETF `FUND:`、指数 `IDX:`、申万 `SW:`、期货 `FUT:`、期权 `OPT:`。原 `source_ts_code` 可关联源表；这不是证券可交易性或跨产品同义证明。所有 `trade_time` 原字符串保留，频率来自不可变 request identity，不覆盖未来响应中的同名 `freq` 字段。

固定 reader 对本 family 的 `trade_time` 默认/显式时间过滤使用秒级无时区 TIMESTAMP 比较，支持空格或 ISO T 分隔，跨午夜不会转为 DATE。筛选参数可用明确秒时间，或整日日期（00:00:00 至 23:59:59）；拒绝带时区或不符合已知秒格式的边界，其他 family 原日期行为不变。未带时间过滤时源值原样返回；未知源时间格式/更细精度需单独审计，不能自动解释。`as_of` 仍只作用于本系统观察时间，不能证明 PIT。

饱和复用既有秒级边界拆分，保持 code/freq 与共享边界；单 code/freq/second 饱和保持 gap，不猜 offset、页码、交易日或时间区间语义。元数据保留单位、调整、时区、历史起点、修订、权限和秒边界未实测等全部合同说明。

相邻小接点：已单独 pick text 纯合同 `def23cb`（本分支 `62f8e22`）；`_planning_inputs` 的 factor_value 依赖按其 `planning_dependencies_by_value_mode` 选择，policy 包含 `factor_library_value_mode`。默认 factor_name 与 factor_list 依赖不变。显式模式变更不会把旧 offset 当新枚举位置；旧 jobs 保留，但生产模式切换仍须独立审核，不能以此候选自动改配置。

专项测试覆盖七市场全列、源代码、两频率不同身份、null/未知字段、跨午夜精确秒过滤、未填 freq 拒读、历史/退市来源分族、实际期货映射、时间饱和终点、有界规划/默认关闭，以及 factor mode 实际未完成扫描的签名变化。临时库、MockTransport，socket/DNS/get_secret 禁用；没有分钟实际权限/返回/吞吐验收。
