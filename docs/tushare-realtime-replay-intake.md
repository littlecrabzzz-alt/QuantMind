# 实时分钟回放 2 API 纯候选

基于 realtime8 纯候选 `2233d3d`，独立新增 `tushare_realtime_replay_contracts.py`，不修改旧模块，不注册、不启用、不采集。`rt_idx_min_daily` 和 `rt_fut_min_daily` 是官方明确命名的实际 API，不能视作旧 `rt_idx_min` / `rt_fut_min` 的别名；这两项是额外目录义务，不受早期发现数量限制。

| API / 官方页 | 完整输入 | 完整输出（全部 default Y） | 明示时间范围 |
|---|---|---|---|
| [rt_idx_min_daily / 420](https://tushare.pro/document/2?doc_id=420) | ts_code 单个实际指数；freq 必填大写 1MIN/5MIN/15MIN/30MIN/60MIN | ts_code(str), time(None), open/close/high/low/vol/amount(float) | 当日开盘以来所有分钟；正文和调用示例明确 daily 名称；无 date 输入 |
| [rt_fut_min_daily / 340](https://tushare.pro/document/2?doc_id=340) | ts_code 单个实际合约；freq 必填同上五种；date_str 可选 YYYY-MM-DD | code/freq/time(str), open/close/high/low(float), vol(int), amount/oi(float) | 当日开市以来分钟快照回放；默认交易当日，支持回溯一天 |

两页在 daily 名称/参数说明之后给出共享输出表，共18列，无已披露隐藏 N。候选复用且深拷贝已有逐字段描述，不删字段、不按示例裁剪；请求全部列并保留未知返回列和 null。当前仅文档契约，daily 实际返回结构、字段类型/单位及与同页普通接口的一致性仍待真实验证。

官方 HTML 证据已保存在 Mac `/tmp/tushare-full-schema-audit-20260909/`：

- 420.html SHA256 `a6eb3ee102aa6a8446776137b15158b507ed7aa7d8d75badb8cff4da423ed879`。
- 340.html SHA256 `5f5012e5b93f067a93a2c82b38bd81e92194a18606b47a930fef63e79a882bb7`。

420 的限量1000行和340的500次/分钟位于普通实时接口说明，是否同样适用 daily 未明确。两项均不宣称已验证供应商 cap/rpm；本地1000行/30rpm只是保守保护。两页说明权限另行开通，实际 daily 权限、调用额度和积分门槛不明，保持 unprobed，不因10100积分或普通接口权限推定已授权。没有已披露历史下界、具体更新时钟或最后一分钟完成时间。

## 可执行规划范围

导出 `REALTIME_REPLAY_CONTRACTS`、`iter_realtime_replay_jobs(config,today,identifiers=None)`、`realtime_replay_prerequisites(...)`；family=`realtime_replay`。配置 `enable_realtime_replay=False` 默认关闭，`realtime_replay_apis` 只包含本2 API；`realtime_replay_frequencies` 默认全部5种、保持精确大写；`realtime_replay_snapshot_epoch` 为显式 UTC 时间，复用现有 `_epoch` 验证属于传入 today 的北京时间日期。`history_start` 或手填日期配置不会产生历史任务。

按已有实际 `indexes` / `minute_futures` 来源惰性逐代码、逐频率规划，两个 API 公平交错，每次只传一个代码，不用通配符/逗号多码。复用既有 `_source_codes` 校验并保留大小写；产品/8888/9999连续代码不猜成真实主力合约，必须有实际合约发现/有日期的 mapping。未支持代码保留计数及发现缺口。

默认 `realtime_replay_futures_scope='current'`，请求 `{ts_code,freq}`，省略 date_str 由供应商决定当前交易日。可选 `current_and_verified_previous` 只额外使用已验证的上一交易日，并不会取消当前请求。依赖 `identifiers['realtime_replay_futures_windows'][source_contract]`，字段为：

- `epoch`：与当前请求一致的 `snapshot-UTCepoch`；`source_api='rt_fut_min_daily'`。
- `current_trade_date` / `previous_trade_date`：精确 ISO 日期；后者严格早于前者。
- `lookback_verified=True` 与 `immediate_previous_trading_day_verified=True`：未来运行层必须依据实际源请求/完整响应、日期过滤对照及相关交易所日历/session 关系认证后才能提供，不能仅由文档或任意手填 bool 声明。

纯模块只能验证形状和日期，不能认证上面证据真实性；不能把手动配置或股票日历改装成已验证来源。缺失、旧 epoch、未确认回溯/紧邻关系，或供应商当前交易日与 today 不一致，都保留前日缺口并仅规划当前回放。夜盘把业务日期归入次日、周末延续上次交易日等情况，本候选不猜日期映射；该保守限制需后续实际 session 证据才能扩展。

节假日跨度可能大于1个自然日，只有真实上一交易日和该接口确实可回溯的双重证据才可传 date_str；测试中的周末/长假日期是合成元数据，用于证明算法不做 today-1，不是交易所日期或上游可用性验证。任何一般历史 range/date/offset 都不接受，也不以该端点替代已登记历史分钟义务。

## 保留身份、字段与缺口

请求身份包括源 ts_code、精确 freq，以及期货可选 date_str；当前默认与显式前日请求不能合并。同页输出未含指数 freq、期货输出却含 freq，均应保存原字段并以请求身份区分5个频率，实际freq/code/date错配应阻止通过。观察标识与实际请求/采集时间都要留存，旧epoch不能被运行层当成准时历史观察。

指数使用 IDX:、期货 FUT: 上下文，保留原始输出 ts_code/code，绝不因 SH/SZ 后缀当成股票；合约大小写和交易所映射不擅自改写。指数页把代码写为“股票代码”、vol写“股”，time类型写None，均保留原文并标单位/类型待验证；期货未明示合约乘数、货币与持仓量口径，不作股票股数或价格单位换算。

没有分页和更细分钟起止过滤；单代码/频率到保护上限、has_more、缺列或时间越界都保留未完成缺口，不改更粗频率冒充细粒度补齐。开盘以来回放也可能有未完成bar和后续修订，不能作为PIT、完整历史或已收盘证据。运行集成仍须处理权限、共享gate、源日期对照、实际采集时间、固定版本验证和快照过期规则。

验证：Python3.10 专属7tests（禁止socket/DNS）覆盖18列、独立schema/cap声明、5频率、源命名空间、当前epoch、同epoch按合约前日依赖、日期格式/闰年/周末/假期与不扩展未来、惰性消费。另复验基线 realtime8 的12tests；不发真实数据请求。
