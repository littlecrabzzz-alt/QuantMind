# 历史分钟7：纯合同候选

基线79f4498；仅新增纯合同、测试及说明，无runtime注册、授权探测、启用、配置或生产改动。完整263+13 scope继续保留；本组不替代旧分钟接口、实时分钟、Tick或日线，不自动开启全市场分钟下载。

| API / 官方来源 | 列数/隐藏 | 接口页cap | 历史与权限差异 |
|---|---|---|---|
| [stk_mins370](https://tushare.pro/document/2?doc_id=370) | 8 / 0 | 8000 | 页称超过10年；权限表通用历史分钟写2009年，仍非逐标的/频率精确下界 |
| [etf_mins387](https://tushare.pro/document/2?doc_id=387) | 8 / 0 | 8000 | 页称超过10年；通用表没有明确ETF行，不能推定股票分钟权限共用 |
| [idx_mins419](https://tushare.pro/document/2?doc_id=419) | 8 / 0 | 8000 | 交易所指数；页称超过10年，不能扩为全球/所有指数分钟 |
| [sw_mins469](https://tushare.pro/document/2?doc_id=469) | 8 / 0 | **5000** | 权限表申万分钟写2015年及8000条，与接口页冲突，按5000保守处理 |
| [ft_mins313](https://tushare.pro/document/2?doc_id=313) | 9 / 0 | 8000 | 有oi；权限表2010年；主力需先用对应日期fut_mapping取得真实合约 |
| [opt_mins341](https://tushare.pro/document/2?doc_id=341) | 9 / 0 | 8000 | 有oi；权限表2010年且提及股指/商品期权；样例输出时间使用T分隔符 |
| [hk_mins304](https://tushare.pro/document/2?doc_id=304) | 8 / 0 | 8000 | 页写120积分可试2次；正式HK分钟价格/下界/当前试用余额未知 |

[官方权限表290](https://tushare.pro/document/1?doc_id=290)明确分钟权限独立于积分，各类单独开通。历史分钟、期货、期权、申万几行报价个人2000元/年、500次/分钟，但没有实际账户授权证明，且不能将这些行扩为所有ETF/交易所指数/HK产品。期货/期权/申万行写总量不限也只是产品描述，不能绕过实际共享gate/账户额度；合同运行上限暂30rpm，全部permission_status=unprobed。10100积分与已购文本权益均不等于分钟权限，未消耗任何试用请求。

## 完整字段、输入与身份

七页全58列均默认Y，所有请求显式全字段，逐字段类型/描述及来源SHA在模块；保留未来未知列、源空值和标量类型，不因当前58列筛掉新列。基本8列为ts_code、trade_time、OHLC、vol、amount；SW末两列顺序amount/vol且vol为float，其他页vol写int但样例浮点外观，不截断；ft/opt另有oi。

全部仅四个合法输入：必需`ts_code`和`freq`，可选`start_date/end_date`（datetime，字符串精确格式`YYYY-MM-DD HH:MM:SS`）。频率全部严格为`1min/5min/15min/30min/60min`，没有2min/1MIN或通用重采样代替来源。没有offset/limit/page/trade_date/adj/exchange参数；频率说明表不是额外输入字段，也不存在分钟API查询别名替换。

自然身份是API/资产 + 原始ts_code + 完整trade_time + **不可变请求freq**。freq未列为输出，未来必须接现有request_identity_fields机制，不能补假源freq或以间隔推断，也不能仅按日期/ts_code合并5种频率。保持distinct full rows和原始trade_time；如果新响应有freq，核对但不覆盖来源。端点不说明时区、bar起止标签或复权方式，不能直接把naive时间当UTC/Asia-Shanghai，也不能把盘后采集日期当历史可得时点。

单位分别保留：股票/ETF文档vol股、amount元；交易所指数虽也标股/元，其指数聚合与价格尺度仍需审计；SW OHLC点数、vol股/float、amount元；期货文档OHLC/amount元、vol/oi手，但乘数与结算口径未知；期权和HK该页未说明单位/币种，不继承股票或期货单位。期货/期权字段说明误写“股票代码”，以实际接口资产处理，不按股票namespace规范化。

## 纯接口与有界规划

导出`HISTORY_MINUTES_CONTRACTS`、`iter_history_minutes_jobs(config,today,identifiers=None)`、`history_minutes_prerequisites(...)`。未来family为`history_minutes`；配置`history_minutes_apis`、`history_minutes_frequencies`（默认全5）、`history_minutes_history_start`（字符串或逐API映射，兼容history_start）。起点可YYYYMMDD或精确无时区秒字符串；未配置只规划近期并留unknown_history_start gap，不把2009/2010/2015或演示日期伪造成最早时间。频率子集单列scope gap，不削掉其余频率义务。

- 近期为锚定today之前7个完整wall-clock日期；不拉当前日盘中。历史仅显式范围，先近期再历史，API间逐项轮流惰性展开；调用方继续使用现有有限预算和游标，不分配庞大全历史list。
- 每请求最多一个wall-clock日期，从实际起点到下一午夜，窗口共享边界时间，保留跨午夜数据。不是交易session划分、不按周末/股票休市过滤，故不会因“夜盘属于次交易日”的猜测丢失原始夜盘。HK样例16:10与期货夜盘不能套A股15点结束。
- 共享端点与source左右包含性尚未实测，连续时间窗口不是完整性证明；需要真实边界重叠/过滤对照后才能给coverage结论。8000/5000或has_more饱和只按原code/freq的秒范围二分，单秒仍饱和保持blocked，不能造offset或由理论每分钟1条宣称永不饱和。不得把解析出的trade_time日期冒充交易所trade_date。
- 日期anchor必须在扫描间固定。**未来接线必须把history_minutes_frequencies加入该family的规划签名键**；现有通用helper只自动识别family_apis/family_history_start，不会识别这个新设置。不修改旧family指纹。分钟固定reader时间轴/边界过滤与现有日线default_date处理须在runtime批次单独验证，本纯候选不声称已有完整分钟查询能力。

标的只从以下实际来源family输入，不自动使用演示代码；原样保留大小写、退市T、HK复用!及期权hyphen，示例`IO2609-C-4000.CFX`只是测试形状，不会成为真实规划种子。股票/ETF/指数即便代码形状相同也不得跨资产推断。

| 纯依赖 / 未来namespace | 来源义务 |
|---|---|
| minute_stocks / CN | 股票历史master及源观察，含退市/T，不限当前上市 |
| minute_etfs / FUND | ETF历史master/源观察，不能以所有公募基金代ETF |
| minute_indexes / IDX | 交易所指数历史master/源观察，不能混入全球/SW/概念指数 |
| minute_sw_indexes / SW | SW各层级及历史版本/源观察，非仅L3；分类PIT仍未知 |
| minute_futures / FUT | 到期/退市合约及源观察；主力额外需要有日期依据的mapping，不请求猜出的连续代码 |
| minute_options / OPT | 全历史各产品/交易所期权及源观察，保留hyphen，不以股票六位regex裁掉合法期权 |
| minute_hk_stocks / HK | HK历史master与源观察，保留!及带字母复用标记，接口是否覆盖这些身份未实测 |

语法检查只能排除无效/多值代码拼写，不能证明某代码在该分钟产品可用；上述跨资产来源映射需runtime审查。缺master时不发无代码全市场请求，未上市历史、数据删除、早期频率、过期分类与未知源标识继续作为缺口。

## 证据与验证

Mac原文 `/tmp/tushare-history-minutes-docs/{370,387,419,469,313,341,304}.html`，对应json/txt；权限页为`permission290.html/txt`。模块保存8份原始SHA，未修改catalog/ledger。七接口当前目录输入/全部输出与真实字段表一致；本批实际差异是SW cap冲突、单位/oi/时间拼写、独立产品权限映射，不是删减接口。

`/tmp/quantmind-calendar-factor-test310/bin/python -B scripts/test_tushare_history_minutes_contracts.py`：8项Python3.10离线测试，socket/DNS禁用；覆盖58字段、5频率、原始跨市场身份、退市/到期形状、共享午夜/闰日/精确首窗口、缺来源不猜代码、未知权限与cap、非法时区/未来起点、惰性与幂等。纯候选不是已接入、已授权或已完成分钟历史。
