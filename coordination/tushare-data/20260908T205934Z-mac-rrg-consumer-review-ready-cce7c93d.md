# RRG 消费前置只读梳理：可以立即并行的最小验收

本轮只读现有报告、固定 release、配置、研究文档及少量已存 Parquet schema；未重复执行 30 行业价格/日历审计，未计算策略、回测或修改研究状态，也未访问上游/凭据/生产。

## 结论

可以立即开一个独立的“固定快照→RRG 坐标消费”技术验收批次，无需等待全量 263 接口或 pending 清零。先停在坐标与日期对齐输出，不输出绩效、排名择优或交易建议。历史行业定义、成员 known_at 和 ETF 可交易性各有独立门槛；价格齐全不能代替它们。现有研究 case 继续保留 blocked_data。

## 精确证据

- 已有审计：`/tmp/quantmind-rrg-slice-parent-20260909/report.json`，SHA256 `36c0c9ed2ea0c3a2c91bca7714dc53f06d15b71a991fa8b74b20a15d1b2787d4`。状态 `slice_structure_passed`；窗口 2022-09-01 至 2026-08-31，warmup 起点 2021-05-17，318 个预热交易日；30 个行业各 1286 日，共 38580 行。排除 CI005029 综合和 CI005030 综合金融后，28 个候选行业共 36008 行。已有报告记录日历缺失、价格无效、最新键重复等均为零；这是既有验收结果，不是本轮重跑。
- 固定 manifest：`/Users/lizeyu/Library/Application Support/QuantMind/tushare/releases/data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6/manifest.json`。本轮确认文件存在、原始字节 SHA 与 release ID 一致。此 release 仍标记 `rrg_status=blocked_data`、`history_complete=False`、`historical_versions_complete=False`、`retained_observations_included=True`。
- 当前输入配置：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/config/rrg_sector_rotation.json`，原始 SHA256 `c44c31d10f03ebea641481c3f8a2d147fddd12c2b1cd84300ef54df141ec5632`，与既有审计报告记录一致。参数为 220/60/20，行业日收益等权累乘基准；月末收盘信号、下一交易日开盘执行。比较期是原文已报道区间，不是独立测试集。
- 消费读取实现：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/backend/shared/tushare_store.py` 的 `read_dataset(root, release_id, api_name, ...)`；只读固定 release，无网络 fallback。`as_of` 是本系统观察时间，不等于历史可知时间。
- 既有审计脚本：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/scripts/verify_tushare_rrg_slice.py`；其中 30 代码集合属于验收清单，不能视为官方完整历史行业定义。
- 阶段约束：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/docs/research-case-workflow.md`；方法记录：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/docs/2026-09-05-RRG行业轮动研究笔记.md`。
- 本地既存研究状态：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/data/research_cases/rrg-sector-rotation/state.json`，最近检查 `checks/20260908T011524.415857Z`，三个 readiness 门槛均 blocked。它是本地既存状态，不能代替更新后的云端状态。
- 既有切片协调记录：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/coordination/tushare-data/20260908T200754Z-mac-rrg-slice-review-structured.md`。

## 建议下一批：仅消费契约技术验收

1. 新建隔离输出目录，例如 `/tmp/quantmind-rrg-consumer-acceptance-<UTC>/`。冻结上述 release、配置 SHA、审计报告 SHA 和消费代码 commit；不跟随 CURRENT。更改输入契约时按研究工作流建立新 case/输出目录，保留旧 case，不修改旧审计结论。
2. 实现一个薄适配器读取 `ci_daily`、`trade_cal`，采用已审计的 28 行业清单。将 ts_code/trade_date/cal_date/is_open 映射至消费者 IndexCode/time/TradingDate/IsTradingDay，保留原始字段和 release 引用。分类标签仅作为本次固定清单上下文，显式标记官方历史定义尚未验证。
3. 配置现在仍指向旧 QuantDB glob 和列名，尚未自动接入 Tushare store。适配器是实际前置工作。已有 `frozen_research_worker.py` 使用个股 LightGBM/TopK、下一交易日收盘的执行语义，不能仅改配置就作为 RRG 下一交易日开盘消费者。
4. 对照研究笔记与其冻结上游 revision `558536af13715aa13fd2131eaf90c70d32108a38` 核实公式，然后固定 220/60/20 与行业日收益等权累乘基准。可以先做纯函数/合成数据测试；本轮未读取该上游 revision，笔记中的简化公式尚不能宣称已经核验。不要参数搜索。
5. 最小测试：相同走势与基准在预热完成后坐标为 100；第一有效输出应在 319 条价格观察之后（索引 318，最终以核验后的公式约束）；修改未来数据不得改变此前坐标；价格整体缩放不改变相对结果；排序和重跑结果确定；缺少所需固定快照数据明确失败且上游调用为零。
6. 只验证月末信号日期到下一可用交易日的映射。最后一个月末的下一交易日落在已有审计窗口之外，需额外验证那一个日历边界或明确缺口，不能暗用当日开盘。暂不模拟成交或收益。
7. 输出 `inputs.json`、`technical_acceptance.json`、可选坐标文件和 `readiness_gaps.json`，记录固定输入哈希、行业范围、公式版本、首个有效日期、行数、无未来泄漏及无网络回退结果。技术状态使用 `consumer_contract_passed/failed`；分类/PIT/ETF 门槛单独保留，不能升级为研究复现通过。

精确 100 边界属于哪个象限、并列排名、筛选后不补足时现金权重尚需冻结。坐标阶段不需要猜这些规则；进入持仓/控制组比较前再固定。策略发现、完整回测和绩效宣称不属于本批。

## 可同时推进的三个独立缺口

### 1. 行业信号历史定义

需要官方历史版本、各期完整行业列表、代码/名称变更生效日期与公布日期，以及行业指数价格/全收益口径和修订说明。当前 30 行业价格齐全和当前成员标签不能证明 2021—2026 各时点分类完整。此项是小范围证据/定义核查，不依赖新闻、海外行情等全部回填。

### 2. 扩散度的成员与股票 PIT

固定 release 中 `ci_index_member` 有 59 个保存分区，样本含 in_date/out_date/is_new 但不含 known_at 或公布时间；样本为 `parquet/c1f27bee323209356fc772d981def07ffbc2e8f83d2edf8e823653d434bcc529.parquet`（相对上述 Tushare root）。in/out_date 不等于可知日期，`_fetched_at` 更不能回填为历史 known_at。未知时间保留未知，不能以当前成员倒填历史。

该 release 的 daily、adj_factor、daily_basic 各只有 1 个已存分区，另有 pending，因此不能由存在表推断窗口覆盖。按历史成员和 220 日回看窗口定向验收这三类即可；浮动市值/自由流通口径、单位与修订需单独核实。样本 daily_basic 虽含 circ_mv/free_share/close，不能未经定义校验直接等同自由流通市值。扩散度层不是纯行业坐标消费的前置。

### 3. ETF 映射与可交易性

固定 release 已保存 fund_daily 1626、fund_adj 2920、fund_portfolio 4149、fund_div 412 个分区；这些是清单分区计数，不是目标 ETF 全历史覆盖证明。先在看绩效之前冻结一个很小的验收证券集合，检查上市/退市、状态、成交量额单位、复权开收盘及分红口径，并针对该集合补缺即可。

etf_basic 样本有 list_date/list_status，但无 delist_date；可用 fund_basic 的 list_date/delist_date/status 做来源核对，不能单表推断无幸存者偏差。fund_portfolio 有 ann_date/end_date，应在公告之后才使用，检查季报披露滞后、仅部分持仓和未解释仓位。etf_index 当前元数据不是历史 ETF→中信行业敞口。

本固定 release 没有 PCF 数据集。静态目录存在 `etf_sh_cons`（官方文档 471）与 `etf_sz_cons`（472），实际权限和历史范围未验证。若 ETF 执行研究需要历史篮子，可单独做这两类小样本权限/历史验证；季度持仓不能冒充每日 PCF。

## 与第一批消费验收无关的全量工作

九类付费文本、PDF/HTML 附件、HK/US、期货期权、债券、宏观、审计/盈利预测/券商研报等全历史完成度，不阻塞固定行业价格坐标验收。全部股票明细、成员 PIT 与 ETF 层也不应成为坐标技术验收的隐含依赖；它们分别约束后续扩散度和可交易实现。

完整回填继续运行。需要加速的数据应由父任务在现有队列按具体 API/标的/日期提升优先级，避免另建重复请求队列或清理已有 pending/成果。本轮无生产调度改动。
