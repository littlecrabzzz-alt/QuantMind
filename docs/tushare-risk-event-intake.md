# ST 状态与交易所风险提示五接口纯候选

比对 263 项目录基线、13 项发现，以及 152 个生产 API 加 DC2 候选，选取以下五个未注册同名 API；不是查询别名替代。初版仅新增纯合同、专属测试与本文；随后运行候选见文末，仍不修改台账或配置，不调用业务 API。原始官方 HTML 与文字已保存在 `/tmp/tushare-risk-docs/{397,423,451,452,453}.{html,txt}`，便于下一轮独立复核。

| 官方接口 | 分数门槛 / 完整输出字段 | 关键区别 |
|---|---|---|
| [stock_st / 397](https://tushare.pro/document/2?doc_id=397) | 3000；`ts_code,name,trade_date,type,type_name` | 历史每日 ST 状态，文档从 20000101 起，且明确较早历史不能补齐；标示每天 09:20 更新。 |
| [st / 423](https://tushare.pro/document/2?doc_id=423) | 6000；`ts_code,name,pub_date,imp_date,st_type,st_reason,st_explain` | ST 变更记录，公告与实施两个日期，含叠加、部分撤销等，不能当单一布尔标记。 |
| [stk_shock / 451](https://tushare.pro/document/2?doc_id=451) | 6000；`ts_code,trade_date,name,trade_market,reason,period` | 输入标“交易日期”，输出标“公告日期”；`period` 是异常期间字符串。 |
| [stk_high_shock / 452](https://tushare.pro/document/2?doc_id=452) | 6000；`ts_code,trade_date,name,trade_market,reason,period` | 严重异常独立数据集；样例输出使用 ISO 日期及期间字符串。 |
| [stk_alert / 453](https://tushare.pro/document/2?doc_id=453) | 6000；`ts_code,name,start_date,end_date,type` | 输入 `trade_date` 指提示起始日；输出截止日是参考值，样例含 ETF `513310.SH`。 |

五项上限均为 1000 行，29 个输出字段全部默认 Y；显式请求所有字段，允许非关键源字段空值，保留后续未知列。接口页未列独立权益与每分钟/日调用额度，门槛不代表账户实际授权，全部 `unprobed`；50 rpm 仅本地操作上限。未从用户购买的文本权益推断这些接口也已获授权。

除 `st` 外，完整输入均是 `ts_code,trade_date,start_date,end_date`；`st` 只有 `ts_code,pub_date,imp_date`，没有范围输入。导出 `RISK_EVENT_CONTRACTS`、`iter_risk_event_jobs(config,today,identifiers=None)`、`risk_event_prerequisites(...)`；建议未来组 `risk_event`，配置 `risk_event_apis`、`risk_event_history_start`（字符串/每 API 映射，回退 `history_start`）。

近期七个自然日按准确日期轴规划：`st` 独立查询 `pub_date` 和 `imp_date`，其余用 `trade_date`。历史按 API 公平轮转：ST 状态使用文档边界，未知下界的三个交易所接口仅在显式配置范围后回填，样例日期绝不充当全历史起点。`st` 复用现有历史/T 股票发现与 `_stocks` 校验，逐股票请求无日期边界的历史事件；它没有合法范围参数，所以配置起点只限制近期日期扫描，不能截掉返回中已公告的未来实施或较早事件。没有主数据时保留发现 gap，不造当前股票清单。

所有自然键增加不同来源行身份：`stock_st` 为 `(ts_code,trade_date,type)`，`st` 为 `(ts_code,pub_date,imp_date,st_type)`，两个 shock 为 `(ts_code,trade_date,reason,period)`，alert 为 `(ts_code,start_date,end_date,type)`。保留原始证券代码、名称、期间及说明，历史 T 代码不得与复用的普通代码合并。官方样例中的股票代码与市场标签存在不一致，不能擅自修成看起来正确的代码。

运行候选遵循以下边界：

- 股票与历史风险观测代码参与饱和发现；alert 还必须并入基金/ETF 历史发现。不能仅取当前 `stock_basic`，也不能用一批饱和返回的标的宣称历史全集已穷尽。
- 四个范围接口可以保留过滤参数后日期二分，再按证券分片。`st` 无范围，单股票饱和时，两个精确日期过滤虽合法，但尚无完整日期全集证明，不能虚构范围/offset 或标记完成。五页都没有 offset/limit 参数。
- 读取日期轴必须明确指定：`st` 默认公告 `pub_date`，alert 默认提示起始 `start_date`。本运行候选已针对风险组使用合同声明的默认轴，同时在 schema、查询与 JSONL 导出保持一致；显式 `date_field` 仍可独立查询实施日或截止日。
- shock 公告日不能替代异常期间；alert 的查询结束参数不能当作返回提示截止日上限，也不能制造输出 `trade_date`。精确日期示例展示多种返回日期，真实过滤含义必须有限探测核对。
- 日状态、公告日、实施日、提示期间均不等于精确的当时可知时间。09:20 更新表述不是每条历史记录的 PIT 证明；近期重叠和一次历史扫描也不证明旧修订/删除全覆盖。RRG `blocked_data` 保持。

离线命令：`python3 -S -B scripts/test_tushare_risk_event_contracts.py`。7 项测试覆盖全部字段和参数、29 列、日期轴及未来语义、ST 历史/T 代码发现、未知起点、闰日连续覆盖、惰性轮转、ETF 分片义务与配置校验；没有 Pipeline、凭据或生产数据访问。


## 风险组运行候选（基线 e87dc2b）

通过现有 registry 注册 `risk_event` 组，须显式 `enable_risk_event`；未修改任何生产配置、capability 权限或启用状态。复用原惰性规划和公平队列，不改变发布函数、发布间隔或计时。字段全部显式请求，源后缀保留在 `source_ts_code`，内部股票与 ETF 使用前缀，历史 T 保持区别；不同来源行保留，重复观测去重。

新增独立 `risk_stocks` 发现来自已存历史股票、历史列表、交易事件及 ST/异常观测；`risk_securities` 再并入基金/ETF 与 alert 观测。registry 将 `risk_stocks` 适配为纯 planner 的逻辑 stocks，并将真实规划依赖声明为 `risk_stocks`，不污染其他组的 stocks。前三类风险股票接口和 st 饱和使用股票集合；alert 使用更宽的证券集合。仅被 alert 观察且类型未知的证券不被猜成股票，集合始终未证穷尽。

专项测试在临时目录模拟采集→规范化→发布→固定版读取/导出，覆盖 29 列与未知列、同日不同来源行、T/ETF 标识、公告与实施/参考截止分离、默认与显式日期筛选、历史发现适配、独立家族验证、日期二分和真实 1000 行终端饱和。终端及不完整集合保持 gap/blocked；未构造 offset 或 st 日期范围。此候选仍未 probe、未发布、未启用，不能据测试提升真实权限/覆盖或 RRG 准入结论。


## 2026-09-09 生产与固定版样本验收

以上“候选/未probe”描述为开发阶段记录，当前a68c6d9已部署。9次实际请求中stock_st203行、st8行（去重6）、stk_shock12行，三接口已启用；stk_high_shock和stk_alert仅返回空样本，仍禁用且权限unverified。29个已知字段中18个经非空样本验证；另外11个仅空表头，不提升为全字段通过。

固定cc8ed219…db55完成云端原文/Parquet/实际reader、认证HTTP与Mac禁网读取，去重221行；ST公告/实施日期的精确与无界请求逐行比较通过。Mac报告/tmp/risk5-mac-verified.json，原probe SHA03335b6da5338ef86f39a15db3f4dce80d2f9c3f0c05efd4e484fc4714d55f38。完整版本与上线证据见tushare-progress 10:36记录。全部历史、完整来源字段、当时可知性仍未完成，8项样本/语义gap保留。
