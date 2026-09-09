# 股票盘前、管理层、竞价与衍生指标：7 API 纯候选

基线 `a68c6d9`，2026-09-09 官方复核。仅新增纯合同、惰性 planner 和隔离测试；未注册运行接口、修改完整目录义务或访问生产。全部权限 `unprobed`，不以 10100 积分替代独立权限或真实探测。

| 官方接口 | 全字段 | 单次上限 | 权限/更新 | 日期与历史边界 |
|---|---:|---:|---|---|
| [stk_premarket 329](https://tushare.pro/document/2?doc_id=329) | 7 | 8000 | 独立权限；9:00、18:10 | 目标交易日；权限总表写近2年、更新次日，未给精确起点 |
| [stk_managers 193](https://tushare.pro/document/2?doc_id=193) | 12 | 未公布；本地 guard1000 | 2000 分；具体频率未给 | 输入 ann_date 或公告 start/end；输出任职起止不是输入范围 |
| [stk_rewards 194](https://tushare.pro/document/2?doc_id=194) | 7 | 未公布；本地 guard1000 | 2000 分；具体频率未给 | 必须 ts_code；可选 end_date 是报告期，输出另有 ann_date |
| [stk_auction_o 353](https://tushare.pro/document/2?doc_id=353) | 9 | 10000 | 独立权限；盘后更新 | 9:30 开盘竞价口径，最早日未知 |
| [stk_auction_c 354](https://tushare.pro/document/2?doc_id=354) | 9 | 10000 | 独立权限；盘后更新 | 15:00 收盘竞价口径，最早日未知 |
| [stk_nineturn 364](https://tushare.pro/document/2?doc_id=364) | 13 | 10000 | 6000 分；21:00 | 20230101 起；输入/输出为时间戳，明确 literal daily |
| [stk_ah_comparison 399](https://tushare.pro/document/2?doc_id=399) | 11 | 1000 | 5000 分；17:00 | 20250812 起，明确旧历史难补、需继续累积 |

全部 **68** 列及输入表与既有 catalog 一致，字段名、类型、默认开关和说明保存在 `FIELD_METADATA`；只 `stk_managers.resume` 为默认 N，所有 job 显式请求全字段。简历允许空值，缺整列仍是 schema gap；新增未知列、出生年/月等部分日期、多个职务/任期及来源修订不能丢弃。原始 HTML/表格仅 Mac `/tmp/tushare-stock-context-docs/{329,193,194,353,354,364,399}.{html,json,txt}`，每页 SHA 在合同中。

[权限总表 290](https://tushare.pro/document/1?doc_id=290) 明确盘前股本 500 次/分，但竞价行链接的是另一 API [stk_auction 369](https://tushare.pro/document/2?doc_id=369)，不能把其权限/频率/ETF范围或历史起点套到 353/354。本批不是 `stk_auction` 的别名，也未添加该接口。其他端点未明确每分钟/日总量的保留未知；本地统一30rpm仅保守运行上限，实际仍需共享gates及逐API探测。

导出 `STOCK_CONTEXT_CONTRACTS`、`iter_stock_context_jobs(config,today,identifiers=None)`、`stock_context_prerequisites(...)`；拟 group `stock_context`，配置 `stock_context_apis`、`stock_context_history_start`（字符串/API映射，回退 `history_start`）。没有精确下界时只规划近期并保留 scope gap；传入已约定 `19900101` 就按范围生成，不把1990称作最早数据。明确起点的九转/AH从各自下界夹取。API间逐条轮转，近期优先、历史惰性；复用已有 `_contract/_parse/_stocks/_days`。

六个日期型 API 近期7日及历史均用精确源日期：管理层 `ann_date=YYYYMMDD`；九转 `freq=daily,trade_date=YYYY-MM-DD 00:00:00`；其余 `trade_date=YYYYMMDD`。九转文案提到60分钟，但未列合法分钟freq或会话格点，本候选只实现有依据的daily并显式保留其他频率义务，不捏造“60min”参数或宣称分钟齐全。未知权限或缺 rewards股票依赖不阻止其他纯分支生成。

薪酬每个规划epoch按已存完整历史股票/T/退市发现逐股请求 `ts_code`，不传日期，返回供应商可得全部期间；它没有合法日期范围，不能造季度全集，也不能把local history_start变成输出截止日。该全期间请求位于近期lane，每epoch每股一次，不重复再建相同历史lane。将来固定读取建议默认公告 `ann_date`，报告 cohort 显式选 `end_date`，不能提前知道尚未公告薪酬。

运行接线仍需处理：股票与HK命名空间分别保留 source_*，AH自然键含 A代码/HK代码/日期（HK不能剥前导0或复用标识）；九转键含时间戳/freq且保留请求freq身份；管理层/薪酬身份含公告/人员/职务/任期或报告期，并保留不同原始行。没有供应商人员ID，不能把同名人强合并或证明相同值事件重数。日期二分仅使用合法输入轴，管理层 output end_date 不参与请求范围判断；九转范围按秒分片，不能改写为日格式。所有API均无 offset/limit；薪酬满guard缺完整报告期分片、AH单A股满cap缺HK第二维全集，必须保持gap。

研究限制也留在合同：盘前近2年/次日与两次更新的版本保存未实现，不把晚上回抓当早盘可知；竞价盘后才能获得，不把9:30标签当时可用；AH两地休市/滞后价格/汇率与溢价算法未知；竞价与九转成交量、金额单位/复权不明，不套daily倍率。盘前股本万股、薪酬元/持股股数按原表保留。七日重叠不能证明旧订正、删除或任期/PIT完整性。

验证：`python3 -B scripts/test_tushare_stock_context_contracts.py`，8项通过；全68字段、隐藏resume缺列、合法参数、公告/报告/时间戳差异、闰日连续无重复、未知范围、1990请求范围与已知下界、退市T、权限/未知上限、既有response assessor及date_children保留过滤器均覆盖。Ruff通过；无上游数据请求、启用、发布或研究准入。


## 默认关闭的运行候选

纯提交之后的增量接入 registry `stock_context`，由既有 `enable_stock_context`（缺省 false）控制；没有改生产配置或完成真实权限探测。独立 `stock_context_stocks` 继承已存历史/T/退市、技术/风险/事件观察，并加入本批来源记录；ETF和概念主数据不混入。只有 rewards 的枚举依赖这份发现；其余接口仅饱和时使用，未知全集仍不证明完整。

固定读取复用既有自然键和来源行身份，不改 schema、release 或 manifest 格式。管理层/薪酬默认 `ann_date`，报告 cohort 显式 `end_date`；其他默认 `trade_date`。九转保留完整时间戳及 immutable request freq。AH额外规范化 `hk_code` 的五位后缀为 HK 前缀，保留前导零、历史 `!` 标识及 `source_hk_code`；未知形状不猜。所有68列、额外未知列、null、原始行SHA和来源代码保留。相同行的重复观察去重，不同来源行/修订与AH配对保留。无合法第二维或日期切分时保持 blocked，不猜 offset/report-period/HK全集。

专项 `test_tushare_stock_context_pipeline.py` 用临时目录、MockTransport及断socket/DNS/provider secret验证实际capture→normalize→publish→固定读、全68字段、隐藏resume、AH历史与当前代码、日期轴、默认关闭、规划幂等/独立校验、历史发现及七接口饱和拒绝伪完成。本候选尚未部署、启用或探测，原权限/日内版本/分钟频率/历史/PIT/单位缺口全部继续有效。


## 2026-09-09 生产探测

十个实际请求中盘前和开收盘竞价拒绝；管理层、薪酬、九转、AH共1801来源行、去重1775、43字段非空样本完整。管理层/九转/AH已启用；薪酬1428行保留且单期22行过滤通过，未知cap保护与完整性缺口未解除。固定ed2f8b46…3faf原文/Parquet/reader及8HTTP（含401、7筛选scope）通过；Mac清单同步正在补修。完整版本与耐久证据见tushare-progress 11:15记录。


2026-09-09后置Mac验收已完成：固定ed2f8b46的release、probe SHA、全部probe_samples、dataset_checks和gaps与云端逐项相等，原文/Parquet/实际reader固定1775行完整对账；仍为3启用、3拒绝、薪酬自动禁用。完整历史与PIT未通过，不能将固定样本验收扩展到未采数据。报告validation/intake-batch-20260909T025328Z/stock7-mac-verified.json。
