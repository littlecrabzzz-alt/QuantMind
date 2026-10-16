# DeepSeek：S03 暴露与首日成交根因调查

- agent：`ds-2` / `w1:p7`
- 实际模型：`deepseek-flash`
- 方法：只读整理既有 CSV、summary、runner、scan-004 Qlib 0.9.7 源级证据；未重跑容器/回测/训练。
- 证据：`evidence/s03-root-cause-010.json`

## 结论

- 18 组均确认前五个测试日 `2025-04-07~04-11` 无成交，首个非零 turnover 日为 `2025-04-14`。
- model 和 single_factor 各场景登记 18 个信号日、有效成交日为 12；等权有效成交日随资金为 3~12。
- model 实际平均暴露低于 nominal risk，短缺范围 `0.1010~0.4182`；持仓上限随资金增加，说明存在明确的资金规模依赖。
- Qlib 0.9.7 的 target-weight→order 源级路径已证：`1/20` target 经 `risk_degree * current_value` 缩放；空 target 对当前可交易持仓的目标金额默认为0并生成卖单；前一 bar 信号通过 `shift=1` 读取。

## 结论边界

- **已证**：文件覆盖、算术一致性、首日空账、18/12 成交日差异、暴露短缺和资金依赖模式。
- **合理假设**：可能存在按资金规模影响的执行/数量门槛，以及 2025-04-03→04-07 的订单生成后被某个交易门控拒绝或裁剪。
- **未解决**：CSV 没有 requested/dealt quantity、拒单原因或逐单 gate，因此不能把原因归为整手、最小票额、涨跌停、限价或 ST。
- k=0 六场景全部 `not_applicable`，测试区间没有 qualified=0 周，不构成清仓验证。

## 下一 wave 最小任务

1. 对 `2025-04-03` 信号→`2025-04-07` 执行做一次隔离 order-fill trace，逐名记录 target、requested amount、dealt amount、价格来源和具体 gate；同时用 `2025-04-11`→`2025-04-14` 作单步对照。不产生 PnL、不重跑18组矩阵。
2. 从同一冻结镜像提取 `CnExchange.deal_order`、`_calc_trade_info_by_order`、`round_amount_by_trade_unit` 与 tradability 的准确源码行号，匹配实际 gate。

本次不选 winner、不继承 optimize 门槛；开发区间已查看；虚拟盘和实盘保持关闭。
