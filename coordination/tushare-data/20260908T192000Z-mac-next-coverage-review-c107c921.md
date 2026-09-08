# 下一批12接口：覆盖缺口与官方契约核查
- 2026-09-09，Mac remaining_markets，审阅共享 master `ca2eca792a2f483d3067993e3563ce610ce7d97a` 的 catalog/ledger/registry；子任务分支 codex/tushare-other-markets。只新增本记录，不改运行模块、进度文档或台账，不访问生产。
- 接续总体 `docs/tushare-integration-plan.md` 与 other 交接；下面是可直接实现的候选顺序，**并非账号已授权/数据已完整**。主数据基础接口已接入，不表示股票/ETF退市全集已验证。

## 计数和不能漏的分类/别名

固定目录263条，227个唯一已提取API名，36条api_names为空，已提取名字没有重复。运行合同97=90 extended+7原始；六个财务VIP采集别名映射 income/balancesheet/cashflow/fina_indicator/forecast/express 原文档，不能额外算六份目录覆盖。静态ledger为 planned143/implementing52/ingested_partial25/permission_blocked5/review_required36/excluded_mutation2；其中新other15已注册仍写planned，不能重复列为下一批，也不能把planned数当纯未实现API数。候选12均在catalog、ledger为planned，且不在97合同中。

36条无API名中至少三条不是普通分类页：[146复权行情](https://tushare.pro/document/2?doc_id=146)与[109通用行情](https://tushare.pro/document/2?doc_id=109)同为SDK `pro_bar` 入口，不支持HTTP；它们属于本地派生行为/SDK验收，不能塞入采集队列或漏计覆盖义务。[314历史Tick](https://tushare.pro/document/2?doc_id=314)明确期货Tick仅CSV网盘交付、独立服务，无API且不属积分权限；保留 external_delivery_pending，不能假造fut_tick。其余33条暂保留分类页候选/链接复查，本次没有逐条证明其无隐藏接口。保留两项mutation排除，不因全目录目标执行写操作。

## 候选顺序（所有文档于本次重新读取）

字段基线为固定catalog对应doc_id的完整output_fields，不只默认展示。下表注明列数与容易丢失的列；API均没有在本次核对的输入表中声明offset/limit，不自行分页。阈值命中时日期二分或完整代码集拆分，若无合法参数继续记gap。

|序|API / 官方明细|字段与建议自然身份|计划分区 / 已具备依赖|明细积分、限额与待实测项|
|---|---|---|---|---|
|1|[moneyflow_mkt_dc](https://tushare.pro/document/2?doc_id=345)|15列；trade_date唯一，保留沪深close/pct及elg/lg/md/sm净额和比例；金额为元|无主数据依赖；历史按年范围（<=366行）、最近7日重叠|6000正式/120试用；3000行；首次历史日未知，不能从示例推断|
|2|[moneyflow_dc](https://tushare.pro/document/2?doc_id=349)|15列；ts_code+trade_date；net和elg/lg/md/sm金额及占比，单位万元|全市场逐trade_date；饱和兜底stocks，保留全市场请求|5000；6000行；文档明确20230911开始，账号未实测|
|3|[moneyflow_ths](https://tushare.pro/document/2?doc_id=348)|13列；ts_code+trade_date；latest、net_d5_amount不可漏，金额万元|同上，不能把THS与DC及已接入moneyflow覆盖成同一源|6000；6000行；历史首日与准确频控未知|
|4|[etf_share_size](https://tushare.pro/document/2?doc_id=408)|8列；ts_code+trade_date；默认隐藏nav/close必须请求，份额万份、规模万元|全市场逐trade_date，完整funds兜底；目录用etf_basic并集，不只在市；重取最近7日|8000；5000行；数据分批次日约08:30入库，海外更迟；输入exchange只列SSE/SZSE但输出含BSE，保留无过滤，不能闭合成两所全集|
|5|[mkt_idx_bmk](https://tushare.pro/document/2?doc_id=462)|8列；建议ts_code+bmk_level，保留fullname/bmk_type/bmk_src/idx_type|无过滤目录+一类库/二类库；可并入indexes发现，但保留本数据独立身份|5000；500行；参数bmk_type说明“宽基指数”等与示例“宽基”不一致，优先不传type；边界饱和按文档分层/已发现指数兜底，完整性待证|
|6|[dividend](https://tushare.pro/document/2?doc_id=103)|16列；ts_code/end_date/ann_date/div_proc/imp_ann_date及事件日期保留；默认隐藏base_date/base_share必须请求，税前cash_div_tax与税后cash_div均留|stocks逐代码存量+ann_date/imp_ann_date逐日增量；至少一个参数，**不支持start_date/end_date**，不可套通用日期范围|2000；2000行；明确20000101开始。单代码饱和改合法公告日/实施公告日分区；无事件ID，未经实测不能按年度简单覆盖不同分红阶段|
|7|[stk_holdernumber](https://tushare.pro/document/2?doc_id=166)|4列；ts_code+ann_date+end_date；holder_num|公告start_date/end_date月区间，满3000二分/逐股；stocks已具备|2000；3000行，基础200次/分钟；输入截止参数拼成enddate，输出end_date是截止日，start/end范围却是公告日，不能混淆|
|8|[stk_holdertrade](https://tushare.pro/document/2?doc_id=175)|13列；ts_code/ann_date/holder_name/holder_type/in_de/begin_date/close_date及原始行身份；隐藏begin_date/close_date不可漏|公告月区间→日期/股票二分；无类型过滤覆盖IN/DE及C/P/G|2000；3000行；trade_type输入对应in_de输出，不是同名；无事件ID，保留同主体多笔事件/原始观察，待真实重复键审计|
|9|[repurchase](https://tushare.pro/document/2?doc_id=124)|9列；ts_code/ann_date/end_date/proc/exp_date及原始事件身份；保留vol/amount/高低价|公告月区间→逐日；**无ts_code输入**，不能用stocks代码fanout|2000；仅说无参数默认2000条，筛选后的硬上限未明确；先以2000报警，单日饱和保留gap，不虚构offset。首日待证|
|10|[share_float](https://tushare.pro/document/2?doc_id=160)|7列；ts_code/ann_date/float_date/holder_name/share_type；float_share/float_ratio|历史按解禁start_date/end_date，增量另按ann_date发现未来解禁；不可只回填至今天float_date而漏掉已公告未来事件|明细120（与权限概览3000不一致，不能断言权限）；6000行，stocks兜底；首日未知|
|11|[top10_holders](https://tushare.pro/document/2?doc_id=61)|9列；ts_code+end_date+ann_date+holder_name（同名股东冲突保留原始行）；hold_float_ratio/hold_change/holder_type都请求|**ts_code必选**；stocks按代码+报告期年度范围，start/end是报告期不是公告期；月度分批历史修订|2000；文档未说明cap，不假定100/1000或全季度VIP；先单股一年样本，保守报警与饱和分期|
|12|[top10_floatholders](https://tushare.pro/document/2?doc_id=62)|9列，身份同上；hold_change的0=未变，空=新进，不能填0|同上；与top10_holders是不同口径独立数据集，不是别名|2000；cap/首日未知，不能以相似字段合并身份|

## 实施边界与未覆盖项

先并行实现1–5（低依赖/低请求量），6–10（事件日期语义需定制）随后；11–12需要已有stocks发现并集，但完整退市全集仍须验证，按代码/年度会更多请求，单独权重渐进回填。各API只发送文档允许参数、显式全部字段、保存未知列与观察时间；申报日/报告期/实施日/解禁日分别存，不以当前响应冒充当时可见数据。事件无可靠唯一ID时先保留完整行身份，不能以粗主键覆盖不同事件；后续版本读取规则需实测重复键后定。

本次不宣称这12项以外完成；下一层仍包括new_share、block_trade、pledge_stat/detail、margin/detail/secs、stk_premarket、THS/DC板块资金流、index_global、idx_anns以及大量其他条目。特别是index_global文档中的XIN9/HSI等是代码表，catalog误列进input_fields，不能直接当参数；THS/DC行业/概念代码也不能拿A股stocks全集替代，需要相应目录。`mkt_idx_bmk`不是已有`etf_index`的别名，`etf_share_size`不是`fund_share`的别名，三类moneyflow数据也分别计入来源。

验证：只读核对catalog全部263条与97合同的集合/别名、ledger状态差异，12篇明细参数/字段/权限重新读取；未生产调用、未更新台账状态、未声称已获授权。下一步父任务可据本表分配纯契约实现，再统一有界实测、记录权限/饱和/历史gap。
