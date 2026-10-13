# ashare-lab 撮合引擎桥接

把 QuantMind 的打分信号（Qlib 格式）交给 ashare-lab 的逐日撮合引擎回测。ashare-lab 的引擎按 A 股真实规则成交：收盘出信号、次日开盘成交，整手，涨跌停和停牌顺延，印花税分段，除权，退市按最后收盘价清算。数据用 ashare-lab 面板（Tushare 归档，含退市股）。

旧的 `backend/shared/vectorized_backtest`（收盘价成交、可买零股、比例费用、Qlib 行情无退市股）自 2026-10-13 起标记为**旧版**，代码保留，只供对照。

## 依赖与开关

- ashare-lab 源码：环境变量 `ASHARE_LAB_SRC`（默认 `~/code/ashare-lab/src`），运行时加入 `sys.path` 后导入 `ashare_lab`。
- 面板：环境变量 `ASHARE_LAB_PANEL`（默认 `~/code/ashare-lab/data/panel`）。
- 两者都可用时 `ashare_lab_available()` 为 True。只在 Mac 上满足；Docker 容器和云端默认不满足，行为不变。
- 不新增第三方依赖（ashare-lab 本身只用 pandas、numpy、duckdb、pyarrow）。

## 接口（`backend.shared.ashare_lab_bridge`）

```python
class AshareLabUnavailable(RuntimeError)
ashare_lab_available() -> bool
import_ashare_lab() -> types.SimpleNamespace
    # 属性：MarketData, load_market_data, ScoreStrategy, Strategy, run_backtest, BacktestConfig,
    #       CostModel, eligible, month_end_dates, metrics（ashare_lab.metrics 模块）
    # 导入失败抛 AshareLabUnavailable
to_ts_code(instrument: str) -> str        # SH600000 / sh600000 / 600000.SH / 600000.sh -> 600000.SH；BJ 同理；无法识别抛 ValueError
signals_to_scores(signals) -> pd.Series   # DataFrame(score 列) 或 Series，MultiIndex(datetime, instrument)
                                          # -> Series，MultiIndex(date, code)，丢 NaN，按 (date, code) 排序

@dataclass
class BridgeConfig:
    initial_capital: float = 1e7
    topk: int = 50
    universe: str = "000906.SH"
    min_list_days: int = 250
    min_amount: float = 5e7
    commission: float = 0.00025
    transfer: float = 0.00001
    stamp_before: float = 0.001
    stamp_after: float = 0.0005
    slippage: float = 0.001
    lot: int = 100

run_signal_backtest(signals, start, end, config=BridgeConfig(), data=None, panel_dir=None) -> BridgeResult
```

`run_signal_backtest`：
1. 信号转为 `signals_to_scores`。
2. `data` 为空时用 `load_market_data(panel_dir 或 ASHARE_LAB_PANEL, start − 450 个自然日, end, universe=config.universe)`（往前多取一段，供上市天数和成交额筛选用）。
3. 策略：每个信号日 t（与日历的交集），在 `eligible(t, data, universe, min_list_days, min_amount=min_amount)` 为真的股票里按分数从高到低取前 topk 只等权（同分按代码排序后稳定排序）。与 ashare-lab `ScoreStrategy` 在默认参数下逐笔一致。没有信号的交易日不调仓。
4. 撮合：`run_backtest(strategy, data, BacktestConfig(start, end, initial_capital, CostModel(...)))`，引擎本身不改。
5. 任何异常都不外抛，返回 `success=False` 和 `error_message`。

`BridgeResult` 字段：`success, error_message, nav(Series), trades(DataFrame, 原样), annual_return, sharpe_ratio, max_drawdown, total_return, portfolio_dict`。
- `annual_return / sharpe_ratio / max_drawdown` 分别等于 `ashare_lab.metrics` 的 `cagr / sharpe / max_drawdown`（rf=0）；`total_return = nav[-1]/initial_capital − 1`。
- `portfolio_dict = {"report": DataFrame, "final_value", "account", "position_value", "execution_model": "ashare_lab_next_open_lot"}`。
- `report`（index=交易日）与旧向量化引擎、Qlib report 同口径：`account`=nav，`cash`，`value`=nav−cash，`cost_amount`=当日费用（元），`cost`=费用/前一日 nav，`turnover`=当日买卖成交额/前一日 nav，`return`=nav/前一日 nav − 1 + cost（即费前收益，`return − cost` 为净收益）。首日的"前一日 nav"取 initial_capital。

## 信号时点

Qlib 的 TopK 策略用 t−1 日的信号在 t 日成交；这里 t 日信号在 t 日收盘后生成、t+1 日开盘成交。两者都只用到 t 日及以前的信息。
