# ST 状态与交易所风险提示五接口纯候选

比对 263 项目录基线、13 项发现，以及 152 个生产 API 加 DC2 候选，选取以下五个未注册同名 API；不是查询别名替代。仅新增纯合同、专属测试与本文，不改运行模块、台账或配置，不调用业务 API。原始官方 HTML 与文字已保存在 `/tmp/tushare-risk-docs/{397,423,451,452,453}.{html,txt}`，便于下一轮独立复核。

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

未来运行接入必须落实这些边界：

- 股票与历史风险观测代码参与饱和发现；alert 还必须并入基金/ETF 历史发现。不能仅取当前 `stock_basic`，也不能用一批饱和返回的标的宣称历史全集已穷尽。
- 四个范围接口可以保留过滤参数后日期二分，再按证券分片。`st` 无范围，单股票饱和时，两个精确日期过滤虽合法，但尚无完整日期全集证明，不能虚构范围/offset 或标记完成。五页都没有 offset/limit 参数。
- 读取日期轴必须明确指定：`st` 默认公告 `pub_date`，alert 默认提示起始 `start_date`。目前 store 的一般日期列猜测可能先选 alert 的 `end_date`；后续运行接入必须修正这一个数据集的默认读取轴，并独立验收区间与未来截止日，不得仅注册键后宣称可消费。
- shock 公告日不能替代异常期间；alert 的查询结束参数不能当作返回提示截止日上限，也不能制造输出 `trade_date`。精确日期示例展示多种返回日期，真实过滤含义必须有限探测核对。
- 日状态、公告日、实施日、提示期间均不等于精确的当时可知时间。09:20 更新表述不是每条历史记录的 PIT 证明；近期重叠和一次历史扫描也不证明旧修订/删除全覆盖。RRG `blocked_data` 保持。

离线命令：`python3 -S -B scripts/test_tushare_risk_event_contracts.py`。7 项测试覆盖全部字段和参数、29 列、日期轴及未来语义、ST 历史/T 代码发现、未知起点、闰日连续覆盖、惰性轮转、ETF 分片义务与配置校验；没有 Pipeline、凭据或生产数据访问。
