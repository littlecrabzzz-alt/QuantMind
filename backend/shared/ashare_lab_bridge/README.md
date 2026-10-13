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

## 接入回测服务（2026-10-13 用户确认：合入并接页面，只在 Mac 上用）

### 后端：`backend/services/engine/qlib_app/services/backtest_service_runtime.py`

新增模块级函数：
- `_ashare_lab_universe(universe) -> str | None`：`csi300→000300.SH`、`csi500→000905.SH`、`csi800→000906.SH`、`csi1000→000852.SH`（大小写不敏感）；其他（`all`、空、文件路径、`pool:` 自定义池）返回 None。
- `_rebalance_days(request, strategy) -> int`：优先 `strategy["kwargs"]["rebalance_days"]`，其次 `request.strategy_params.rebalance_days`，都没有为 1。
- `_sample_rebalance_dates(pred_df, n) -> DataFrame`：按 `datetime` 层的唯一日期排序，保留第 0、n、2n… 个日期的全部行；n<=1 原样返回。
- `_run_ashare_lab_vectorized(pred_df, request, strategy, commission, transfer_fee) -> BridgeResult`：先 `_sample_rebalance_dates(pred_df, _rebalance_days(...))`，再 `run_signal_backtest(..., request.start_date, request.end_date, BridgeConfig(initial_capital=request.initial_capital, topk=request.strategy_params.topk, universe=_ashare_lab_universe(request.universe), commission=commission, transfer=transfer_fee))`。印花税用 ashare-lab 的历史分段（2023-08-28 前 0.1%，之后 0.05%），滑点用 ashare-lab 默认 0.1%。

修改：
- `_is_vectorized_safe(request, strategy)`：`_ashare_lab_universe(getattr(request, "universe", None))` 非空**且** `ashare_lab_available()` 时返回 True，否则 False。旧的分数股引擎永远不算安全。
- `use_vect` 分支：不再使用 `VectorizedBacktestEngine` 和 `D.features` 取价；物化 `pred_df` 后调用 `_run_ashare_lab_vectorized`（在线程里跑，`asyncio.to_thread`），失败抛 `RuntimeError`；成功后照旧交给 `RiskAnalyzer.analyze(portfolio_dict=...)`。日志里写明引擎为 ashare-lab、实际调仓日数、股票池指数代码。
- 没有面板或股票池不是上述指数时，`_is_vectorized_safe` 为 False，回测走原有 step 模式，**行为与改动前完全一致**（云端即此情况）。

### Mac 本地挂载：`deploy/compose.local-dev.yml`（只被 scripts/local-dev.sh 使用，云端不用）

`quantmind` 和 `celery-worker` 两个服务各加：
- 卷：`${ASHARE_LAB_ROOT:-${HOME}/code/ashare-lab}/src:/opt/ashare-lab/src:ro` 和 `${ASHARE_LAB_ROOT:-${HOME}/code/ashare-lab}/data/panel:/opt/ashare-lab/data/panel:ro`
- 环境变量：`ASHARE_LAB_SRC=/opt/ashare-lab/src`、`ASHARE_LAB_PANEL=/opt/ashare-lab/data/panel`

`docker-compose.yml`（云端也用）不改。

### 页面：`electron/src/components/backtest/QlibQuickBacktest.tsx`

在"尾盘交易"开关旁边加一个同样样式的开关"A股真实撮合"（默认 OFF，记在 localStorage，键 `qm.quickBacktest.ashareLab`），ON 时请求带 `use_vectorized: true`，OFF 时带 `use_vectorized: false`。悬停提示：ON 时"ashare-lab 引擎：T日信号、T+1开盘成交，整手、涨跌停、停牌、退市按真实规则；仅 Mac 本地且股票池为沪深300/中证500/中证1000 时生效，否则自动按标准引擎运行"；OFF 时"标准引擎（Qlib）"。
