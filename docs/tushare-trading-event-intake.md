# 龙虎榜与游资 4 接口接入

以下为纯合同阶段记录；2026-09-09 已完成生产接入，验收见末节。原设计基于 `eb3bf64`（131 个已注册接口），本增量只提供纯合同和离线惰性规划。仍以既有 263 项目录基线 + 11 项额外发现为审计范围；这 4 项已在基线，不增加目录分母，也没有获得运行接入、权限或全历史完成证明。

| API / 官方依据 | 门槛 / 单次上限 | 合法分区与历史范围 | 关键语义 |
|---|---|---|---|
| [top_list / 106](https://tushare.pro/document/2?doc_id=106) | 2000 积分 / 10000 行 | 必填 `trade_date`，可选 `ts_code`；文档称 2005 年至今 | 同股同日不同 `reason` 均须保留；官方例中 002219.SZ 的两个上榜原因不能合并 |
| [top_inst / 107](https://tushare.pro/document/2?doc_id=107) | 5000 / 10000 | 同上；历史下界未公开 | `exalter + side + reason` 区分席位榜单；`side` 保持源字符串 0/1，不能当布尔买卖信号 |
| [hm_list / 311](https://tushare.pro/document/2?doc_id=311) | 5000 / 1000 | 可选 `name`；无日期输入，仅快照 | `orgs` 类型未指定；名称、组织列表是供应商标签，不是已核实账户归属或历史 PIT 映射 |
| [hm_detail / 312](https://tushare.pro/document/2?doc_id=312) | 10000 / 2000 | 可选 `trade_date/ts_code/hm_name/start_date/end_date`；2022 年 8 月起 | `tag` 默认隐藏；`hm_name/hm_orgs/tag` 与源行区分标签，不以股票日线键覆盖 |

纯合同阶段账户权限全部 `unprobed`，后续真实样本权限已记录到覆盖台账。10100 积分只超过这些页面写明的数值门槛，独立权益、实际频率和可返回历史仍须真实能力探测；合同中的 50 rpm 是保守运行上限，不是官方频率承诺。4 页均未提供 offset/limit 输入。

## 父任务接入边界

- 导出 `TRADING_EVENT_CONTRACTS`、`iter_trading_event_jobs(config, today, identifiers=None)`、`trading_event_prerequisites(...)`；建议组名 `trading_event`，配置 `trading_event_apis` 与 `trading_event_history_start`（字符串或按 API 映射），后者回退 `history_start`。
- 按 `planning_epoch` 生成最近 7 个自然日，然后按 API 轮转历史日；不依赖当前股票或开市日过滤。`hm_list` 每个近期 epoch 仅一个无筛选快照，没有历史日期任务。历史 epoch 固定为 `history`；外层仍使用既有有限扫描/固定 anchor 机制。
- `20050101`、`20220801` 是官方年/月范围的规划下界，并非已经验证的首条数据日期；显式更晚起点会缩窄范围并保留 gap。`top_inst` 未配置起点时仅规划近期，不能声称全历史。
- 接入时在 registry 注册组/键，在 pipeline 增加启用选项、该组相关配置签名、gaps 和 installer 模块名单；store 日期列分别为 `trade_date`，`hm_list` 无源日期列。纯候选不改这些运行文件。
- 候选 keys：`top_list(trade_date,ts_code,reason)`；`top_inst(trade_date,ts_code,exalter,side,reason)`；`hm_list(name)`；`hm_detail(trade_date,ts_code,hm_name,hm_orgs,tag)`。都要求 `preserve_distinct_rows`，保留 `_row_identity` 区分不同源行，并保持原始响应。内容哈希仍不能证明同值多笔交易的真实 multiplicity。

### 必须显式选择字段

合同 `required_fields` 要求全部已核查列存在，允许非代码/日期字段为 null。`hm_detail.tag` 同时属于 `required_fields` 和 `nullable_fields`：缺列必须可见，合法空值可以保留。所有任务携带完整 `fields`，并提供同一 `requested_fields/extra_fields` 清单：

```text
top_list: trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason
top_inst: trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason
hm_list: name,desc,orgs
hm_detail: trade_date,ts_code,ts_name,buy_amount,sell_amount,net_amount,hm_name,hm_orgs,tag
```

任何实际调用若仍使用 `fields=''`，只会请求供应商默认列，不能凭本合同写有 `tag` 就认定它已采集。父集成必须验证字段清单确实进入业务客户端请求，并对 raw response 字段做验收；同样需要保留未来发现的未知列和更新官方 schema 证据，而非永远冻结这 37 列。

### 饱和与发现缺口

三个每日接口首先全市场精确日请求。达到上限时可按 `ts_code` 拆分；父接线必须将完整存储的历史/退市/T 前缀股票与观测到的事件源代码取并集。纯合同暂以既有 `stocks` fallback 命名，同时显式声明 `trading_event_securities` 发现依赖；这不是现有运行层已经具备该并集的保证。不能仅用当前上市代码证明日期分区完整。

`hm_detail` 还可按 `hm_name` 二级分区，但当前通用运行器未因此自动获得该能力；需要从名单与明细发现独立标签集合并审查覆盖。`hm_list` 到 1000 行时，按已看到的名字重查无法证明截断外名字齐全，必须保留饱和 gap。所有 terminal cap、未知历史、历史标签变更和旧公告修订继续未闭合；7 日重叠不等于完整修订捕获。

## 目录提取纠正（不修改基线）

`hm_list` 官方 schema 只有 `name/desc/orgs`；固定目录误将示例表里的 `zhouyu1933/bike770/Asking` 提取为列。此次只在独立合同纠正该项，保留原 `config/tushare-catalog.json` 抓取证据和全部计数。`eb3bf64` 的 `Pipeline.enqueue` 将 catalog 列与合同列取并集，且不会直接使用纯 planner 的 `fields`。因此父接入前必须定点更正该 catalog schema（保留原哈希/证据），或采用已经审查的字段覆盖机制；只改纯合同仍会把示例名字发作 fields。应登记这一提取错误，不减少目录项和全局分母。

本次仅重读这 4 页，保存的 HTML 与目录哈希相同：

| doc_id | SHA-256 |
|---|---|
| 106 | `c6896f3bbba618d9aa7ce08e869cfd2426ff451f2a3466e5c1cfc9320c29207e` |
| 107 | `9da4e8fff195e2d35319fb2ee92d1394b7f713b9f24ed3322daec05b8d887d0f` |
| 311 | `6ea2c654c4c31b413f527d7d97fa603a9eea0390658684fcbe13120b2ce6d7a4` |
| 312 | `64e42c09934c74aea5bd28fe1f0f439ae64fed68a372fdfbac045217a42adc7b` |

可独立复验：`python3 -S -B scripts/test_tushare_trading_event_contracts.py`。测试不实例化 Pipeline、不连接网络、不读写权威数据，覆盖完整字段、隐藏列、合法参数、历史边界、闰日/周末连续性、惰性轮转和未知范围保留。

## 2026-09-09 生产验收

f2cd52e 经双端校验部署，4次真实请求2.789秒：top_list57、top_inst660、hm_list117、hm_detail246，共1080行、37输出列全部返回。hm_list.orgs为原始字符串；hm_detail.tag列存在且246行全部null，未把空值当缺列或自行补标签。原文、观察与Parquet逐字段/日期匹配，固定API及Mac禁网读取全部一致。

已启用trading_event组，首次近期22项、历史478项新任务；旧12组历史签名与游标保持。源证券发现5910、游资名称117，均不是历史全集证明。固定版本data-1a593ee58c333ebb02b025b1529f342c914a82cf389ac7878eeb34c73f45d668，证据validation/eight-acceptance.json、eight-api-acceptance.json及/tmp/tushare-eight-mac-verified.json。历史成员/PIT和饱和末端仍保留缺口。
