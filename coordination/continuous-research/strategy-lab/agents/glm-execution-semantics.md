# GLM-5.3：小额成交语义审查

**GLM 执行语义审查（静态读取，未运行任何计算）**

1.【已证·复权】model-trades.csv/model-positions.csv 列名即 adjusted_quantity/adjusted_price，价格如 SH601398=11.0139 非真实两位报价。机制见 cn_exchange.py `get_factor`（读 $factor）与 `_calc_trade_info_by_order` 中 `round_amount_by_trade_unit(deal_amount, factor)`：取整在复权空间进行，故数量带小数。账务自洽因全程同一复权口径，但产物不能直接对照真实行情价。

2.【待查·100股单位】`CnExchange.__init__` 未设置/透传 trade_unit，取整粒度取决于基类。需主控查 `qlib.backtest.exchange.Exchange.__init__` 的 trade_unit 默认值，及 run_frozen_research.py 构造 CnExchange 时是否传 trade_unit=100；再用 adjusted_quantity×$factor 换算真实股数验证 100 整数倍（如 SZ000564 895.15 股静态无法判定）。**在证实前不得称引擎已实现整手约束。**

3.【已证·最低佣金生效、分项缺失】`calculate_cost` 返回 comm+tf+tax+impact 合计，`deal_order` Redis 记录仅 "commission":trade_cost，CSV cost 列同为总额。10万档买单 cost≈5.00–5.05 对应成交 2000–4700 元，名义佣金不足 5 元，最低佣金逐笔生效；但佣金/印花税/过户费/冲击四项不可拆分。

4.【已证·现金约束；待查·先卖后买】`_calc_trade_info_by_order` BUY 分支：cash<cost→置 0，cash<val+cost→`_get_max_buy_amount` 迭代收缩后取整；SELL 分支 min(持仓,订单)、现金不足付费用置 0。CSV 2025-04-08 先 5 笔 sell 后 buy，cash_after 无负值。同日 sell 先于 buy 的顺序源自 Qlib 策略/executor 下单序，需查 `qlib.contrib.strategy.signal_wrappers.TopkDropoutStrategy.generate_trade_decision`。

5.【缺口·整手归因】要断言"整手是资金档差异原因"，至少需：逐股逐日 $factor 换算真实股数并验 100 倍数、真实未复权价、费用分项、逐日目标 vs 实际仓位与现金闲置序列、跨资金档信号 hash 一致。缺任一项只能表述为"最低佣金与取整相关的成本差异"，不得归因整手。

6.【待查·建仓完整性】lower_exposure-100000 首日（04-07）仅 10 笔买入、持仓 10 只，投入约 1.99 万（cash_after 80107），明显低于 Top20×50% 目标；higher 档首日≥12 笔。首日未满额原因（信号覆盖/下单截断/现金）未证，报告须含逐日实际持仓数与实际暴露序列，避免把建仓节奏误读为交易单位效应。
