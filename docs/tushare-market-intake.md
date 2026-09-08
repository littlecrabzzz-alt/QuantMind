# 基金、行业、可转债和期货接入契约

2026-09-09；接续 [总计划](tushare-integration-plan.md)及[首批结构化契约](tushare-structured-intake.md)。本批独立新增 23 个只读端点，不改采集器、不读取凭据、不调用生产 API、不部署。主任务负责共享限速、权限探测、分片落盘、完整性验收和 Mac 镜像。

| 组 | 端点 | 覆盖与请求方式 |
|---|---|---|
| 公募基金 | fund_basic、fund_company、fund_manager、fund_nav、fund_share、fund_div | 场内 E/场外 O × 摘牌 D/发行 I/存续 L，附加不筛状态请求发现新状态；基金经理分页；净值按基金时间窗；沪深 ETF 份额按日/市场；分红按基金完整快照 |
| ETF/指数/行业 | etf_index、index_weight、index_classify、index_member_all、sw_daily | ETF 基准指数全集；指数权重逐月；申万 SW2014/SW2021 × L1/L2/L3；三级成员分别 Y/N；申万日线逐日 |
| 可转债 | cb_basic、cb_issue、cb_call、cb_rate、cb_daily、cb_price_chg、cb_share | 基础全集含历史债券；发行/赎回按公告月；利率/转股价逐债完整快照；行情逐日；转股结果逐债时间窗 |
| 期货 | fut_basic、fut_daily、fut_mapping、fut_settle、fut_wsr | 六交易所普通/主力连续合约，保留到期合约；日线/结算/仓单按交易所和日，主力映射按日全集 |

六交易所为 CFFEX/DCE/CZCE/SHFE/INE/GFEX，不通过股票后缀猜测期货市场。期货基础请求不加上市起点，避免排除已到期合约。原始代码及未知状态留存，消费端统一代码规则由共享标准化器承担。

纯函数入口：

```python
MARKET_CONTRACTS[api_name]
iter_market_jobs(config, today, identifiers=None)
market_prerequisites(identifiers=None, enabled_apis=None)
```

复用首批 `_contract` 构造与日期校验。`config.history_start` 必填，`market_apis` 只供主任务显式分批启用；不是删除剩余目录项的范围设置。`today` 为上海当地 date。所有基础发现与近期请求在历史之前，输出 `{api_name, params, priority, epoch}`；近期 25、历史 45。父作业持久化计划日期/游标与任务状态，不依赖迭代器留在内存。

标的发现约定：

| identifiers 键 | 原始来源与字段 | 用途 |
|---|---|---|
| funds | fund_basic 全 E/O、D/I/L 及不筛状态记录的 ts_code；允许供应商代码字符串 | 净值、分红初始规划；基金份额单日饱和 fallback 用 ts_code，并按请求市场限定 |
| indexes | index_basic 全市场 ts_code 与 etf_index 的基准 ts_code 去重 | 指数月度权重；不声称所有指数都支持权重接口 |
| bonds | cb_basic 全历史 ts_code | 利率、转股价、转股结果；可转债日线和事件饱和 fallback |
| sw_l3 | index_classify 的 index_code，原始字典带 level 时只取 L3；包括两分类版本 | index_member_all 的 l3_code，Y/N 分开 |
| sw_indexes | index_classify 全层级 index_code 与已保存 sw_daily ts_code | 仅申万单日饱和 fallback，不作为全市场日线启动前提 |
| futures | fut_basic 普通/连续全部 ts_code，保留请求 exchange 与 fut_type 来源 | 期货单日行情/结算饱和 fallback，按 exchange 过滤 |
| futures_continuous | fut_basic 请求 fut_type=2 的 ts_code（类型来自观察请求，不能依赖输出有 fut_type 字段） | 主力/连续映射单日饱和 fallback |
| futures_products | fut_basic 的 fut_code 与 exchange，及历史已保存仓单 symbol；去重保留交易所 | 仓单单日饱和 fallback 的 symbol；不能把合约 ts_code 当产品代码 |

初始规划器只读取 funds/indexes/bonds/sw_l3 四类，其余声明在 `saturation_fallback` 和 `saturation_param`，由主采集器从原始发现记录构建。缺少依赖返回显式缺口；有一条记录也不能证明集合完整。不要过滤未知状态、历史退市或到期记录。基金净值历史用每基金一个完整区间，达到 cap 再日期二分；会产生必要的叶分片，不能为了队列更短跳过老数据。

关键正确性与非阻塞卡点：

- 所有输出字段从既有目录字段表请求，含 index_classify.src、fut_basic.trade_time_desc、仓单 wh_id/area/year/grade/brand/place/pd/is_ct/exchange 等隐藏字段。仓单自然键包含仓库与品级/产地等，不能把同日同产品同仓库的不同明细合并。
- 基金经理官方支持 offset/limit，契约 `pagination` 初始 offset=0、limit=1000；每个满页继续，空尾页/短页、重复页、错误和中断检查由共用采集器承担，不能把初始页当全集。
- 基金净值页未公开当前 cap，契约 row_cap=1000 只是保守饱和告警，`row_cap_verified=false`。基金管理人、分红、指数权重/分类同样保留未核实上限。API 返回数量小于告警值不能证明上游完整。
- 基金基础场外列表或历史期货合约仍可能超过单次限额。文档没有任意 offset 保证；不能发明分页参数。所有变体及原响应保留，饱和且没有完备独立标的清单时登记发现缺口。cb_basic 未指定 exchange 的合法取值，不猜 SSE/SH，而先使用官方全集示例；饱和再核实分区方案。
- index_weight 无 con_code 输入，不能按成分代码细分；月份可按 start/end 日期二分，单日仍饱和就保留缺口。权重是官方月度资料，不可补成每日观测或当成入选日已知。
- index_member_all 没有分类版本 src 输入；虽请求 SW2014/SW2021 发现的全部 L3 及 Y/N，不能证明重建了所有历史分类版本。sw_daily 文档默认 2021 行情且无版本参数，2014 口径历史仍列为缺口。成员 in_date/out_date 不等同历史发布时间，RRG 的 PIT 验收独立进行。
- cb_price_chg 明确是独立权限，积分无关；权限未验证。主作业应先探测，拒绝后暂停这一端点并继续其他接口，不代为购买。
- cb_share 参数表把 ts_code/ann_date 都写必选，官方示例只传 ts_code。本批按官方示例使用代码并加公告区间，需生产小样本验证；若参数被拒绝则记录此项并继续其他接口，不擅自声称接口可用。
- 事件按公告区间获取可能无法发现公告日期为空的记录；持有已保存标的全集后的定期逐标的完整复查、老数据修订低频复查仍是后续工作。空响应、无权限、服务错误、截断分别记录。
- 期货价格可能为零或负，契约不统一套用股票正价格检查。基金份额接口公开范围为沪深 ETF，不能把它描述为全部场外基金份额；其他基金规模端点继续留在总目录。

官方文档于本批实现时逐页浏览（公开文档访问不携带 token）：

[fund_basic](https://tushare.pro/document/2?doc_id=19)、[fund_company](https://tushare.pro/document/2?doc_id=118)、[fund_manager](https://tushare.pro/document/2?doc_id=208)、[fund_nav](https://tushare.pro/document/2?doc_id=119)、[fund_share](https://tushare.pro/document/2?doc_id=207)、[fund_div](https://tushare.pro/document/2?doc_id=120)、[etf_index](https://tushare.pro/document/2?doc_id=386)、[index_weight](https://tushare.pro/document/2?doc_id=96)、[index_classify](https://tushare.pro/document/2?doc_id=181)、[index_member_all](https://tushare.pro/document/2?doc_id=335)、[sw_daily](https://tushare.pro/document/2?doc_id=327)、[cb_basic](https://tushare.pro/document/2?doc_id=185)、[cb_issue](https://tushare.pro/document/2?doc_id=186)、[cb_call](https://tushare.pro/document/2?doc_id=269)、[cb_rate](https://tushare.pro/document/2?doc_id=305)、[cb_daily](https://tushare.pro/document/2?doc_id=187)、[cb_price_chg](https://tushare.pro/document/2?doc_id=246)、[cb_share](https://tushare.pro/document/2?doc_id=247)、[fut_basic](https://tushare.pro/document/2?doc_id=135)、[fut_daily](https://tushare.pro/document/2?doc_id=138)、[fut_mapping](https://tushare.pro/document/2?doc_id=189)、[fut_settle](https://tushare.pro/document/2?doc_id=141)、[fut_wsr](https://tushare.pro/document/2?doc_id=140)。

验证命令：`python3 scripts/test_tushare_market_contracts.py`。4 项离线测试覆盖闰年及跨月完整窗口、近期先行、历史/未知状态保留、所有基础参数组合、申万层级、23 接口字段及参数对官方目录、隐藏字段键、分页和不可用分片轴、发现缺口与输入校验；Ruff 通过。尚无真实权限/数据覆盖/PIT/镜像验收，本批提交本身不更新总目录运行状态。
