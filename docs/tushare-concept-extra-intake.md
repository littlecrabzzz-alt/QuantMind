# THS/DC 板块 4 接口接入

本组接入 `ths_index/ths_daily/ths_member/dc_index`，完整保留目录、行情、最新成员和分类来源。范围仍为263项固定目录与13项额外发现，接口上线不解除RRG的历史成员/PIT限制。

| 官方接口 | 页面门槛 / 行数限制 | 日期与字段关键约束 |
|---|---|---|
| [ths_index / 259](https://tushare.pro/document/2?doc_id=259) | 6000 分 / 5000 行 | 官方要求一次取全、不要循环。只规划一个无筛选快照，不做 A/HK/US × 7 类型网格；无历史日期查询。`list_date` 不是行情历史可用下界。 |
| [ths_daily / 260](https://tushare.pro/document/2?doc_id=260) | 6000 / 3000 | `trade_date` 日线；`total_mv/float_mv` 默认隐藏。价格是指数点位，量为手，市值为元，不能沿用其他市场统计单位。历史起日未公布。 |
| [ths_member / 261](https://tushare.pro/document/2?doc_id=261) | 6000 / 上限未公布，200 次/分钟 | 官方明确最新成分。隐藏 `weight/in_date/out_date/is_new`，前三项注明暂无；无日期和 `is_new` 输入，不能伪造历史成员区间。 |
| [dc_index / 362](https://tushare.pro/document/2?doc_id=362) | 6000 / 5000 | 每个交易日的板块数据。`idx_type` 输入表标必填，样例省略；显式规划行业、概念、地域三类并保留请求身份。历史起日未公布，市值为万元。 |

40 个官方输出字段、全部输入参数与现有目录一致。所有已知列放入 required/requested/extra 字段清单，非核心代码/日期允许 null；这不会把文档“暂无”变成已经可获取。实际未返回某列必须记录字段 gap，保留完整原始响应、未知新增列，不能用默认字段或静默补空宣告采集完整。

合同初始权限为 `unprobed`；实际账户样本与启用状态见下方验收。用户10100积分本身不代替访问证据，合同50rpm是本地运行上限。

## 纯计划及接入边界

导出 `CONCEPT_EXTRA_CONTRACTS`、`iter_concept_extra_jobs(config,today,identifiers=None)`、`concept_extra_prerequisites(...)`。运行组为 `concept_extra`；配置 `concept_extra_apis`、`concept_extra_history_start`（字符串或每 API 字典），回退 `history_start`。

`ths_index` 每次刷新 epoch 只生成一个无筛选请求；`ths_member` 对存储发现的 `ths_indices` 每代码生成一个当前快照，不按日期循环、不查询伪历史参数。该依赖写入合同 `dependencies`，既有有限规划器才能在新代码发现后安排补齐。日线和 DC 最近覆盖 7 个自然日；历史下界全部未知，没有显式起点时不生成历史日期，配置后轮转惰性回填。无成员时仍可规划目录、日线和 DC，并保留待发现 gap。

股票、港股、美股和退役板块不能按当前 A 股过滤。`ths_indices` 接受存储源代码或带 `ts_code` 的记录，保持原拼写，不将 `.TI` 强制转换为股票。DC 使用独立 `dc_indices`；`BK1186.DC` 不与 THS 同名板块自动合并。`ths_member.con_code` 的外市场格式，以及 `dc_index.leading_code` 的交易所/代码格式尚无充分样例，应保留源值并标待核验，不能自行补交易所或注入 A 股集合。

键候选：目录 `(ts_code,exchange,type)`、行情 `(ts_code,trade_date)`、成员 `(ts_code,con_code)`、DC `(ts_code,trade_date,idx_type)`。保留不同源行和原始观察；DC 还设置 `request_identity_fields=["idx_type"]`，后续运行接线和全合同 store fixture 必须保留真实类别请求。

## 不可省略的缺口

- THS 成分没有官方单次上限。合同中的 5000 只是本地保护阈值，`row_cap_verified=False`，小于该数也不证明完整。达到阈值时，不能按日期拆分；按 `con_code` 需要独立完整的跨市场成员集合，当前股票或截断响应中的成员不足以证明覆盖。
- 目录没有退役板块全量历史；THS 日线即使拆成单日/单代码，也要保留历史板块发现缺口。DC 同理，三类板块各自的退出、改名和历史集合不能靠当前目录推定。
- 无 offset/limit 文档。日线/DC 可拆合法日期范围与源代码；单日单代码饱和保持 blocked。目录达到 5000 时遵从“不循环提取”要求保留 gap，不自创分页或网格证明。
- `weight/in_date/out_date` 不可用，`is_new` 也不建立历史可知时点。当前成分、上市日期、事后榜单及本系统抓取时间不能取代 PIT 成员证据；旧修订和删除仍未闭合，RRG 的整体数据阻塞不解除。

复验：`python3 -S -B scripts/test_tushare_concept_extra_contracts.py`。8 个测试覆盖完整字段、隐藏/暂无列、单次目录快照、跨市场/退役代码保留、三类 DC 请求、闰日分区、未知起点及按真实依赖校验；无 Pipeline、账户或生产访问。


## 2026-09-09 08:36 生产与固定版验收

- runtime100e4df已合入master/GitHub/cloud，404隔离tests（12.380秒）、Ruff和diff检查通过；双端源4574文件/hash b13bc9862198982a70eb86f1b3228497c9cbcfb929aeeee871a90a48182508a0一致。共152采集接口、6财务查询别名（KEYS158；扩展145+基础7）。此次无schema迁移。
- 8真实请求耗时6.139秒：ths_index2517行（A/HK/US、七种type均观察到），ths_daily1877行，DC三类496/504/31行，三个ths_member快照309/15/54行，合计5803。40个显式字段全部返回，无日期/代码/类别过滤错配；raw/观察SHA及Parquet全列、请求identity通过。
- THS日线total_mv/float_mv样本均非空；成员weight/in_date/out_date的378行全部null，is_new全部Y，不能推断历史区间。目录标A/typeBB的700014.TI成员实际309个.HK代码，目录count306与返回309不一致；目录exchange不是成员市场证明。HK目录871001.TI返回15个.HK；US目录861001.TI返回54条含.O/.N/.A代码。全部原码保留，不强转A股、不过滤超出目录count的记录；本次未宣称真实A股成员样本已验。
- 四接口已启用，首轮近期500新任务；history游标先跳过500个近期项、尚未进入历史尾部，仍需持续推进，不能把此状态称为历史已下载。原13个未完成history签名/offset保留；limit历史规划已完成，不重置它。
- 固定data-e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce：30次云端HTTP查询与独立raw/Parquet/去重结果全5803行一致，匿名401、upstream_calls=0。Mac新增4058、共159836镜像文件校验，禁socket/DNS/凭据同样5803行全列通过，24样本证据文件SHA通过；snapshot查询不套用日期过滤，DC三类别身份/THS成员与领涨股原码均保留。
- 证据在云端validation/concept-extra-probe.json、concept-acceptance.json、concept4-api-acceptance.json、concept-runtime.json；Mac /tmp/concept4-mac-offline-verified-20260909.json。自动任务已有四个ths_member返回5549/5424/5216/5099行，因未知官方上限和本地5000guard标possibly_truncated/blocked，完整原文仍归档；这不是证明源实际截断。其余成员与日期任务继续。全历史/旧修订/退出成员/PIT和所有供应商隐藏字段全集仍未证完整。
