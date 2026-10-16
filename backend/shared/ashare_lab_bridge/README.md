# ashare-lab 撮合桥接

用途：维护分数信号到 ashare-lab 的次日开盘撮合合同，与标准 Qlib 路径区分时点、费用及适用条件。实现见 `bridge.py`；不修改外部市场面板。

## 环境前提

- `ASHARE_LAB_SRC`：源码目录，默认 `~/code/ashare-lab/src`，其下须有可导入的 `ashare_lab`。
- `ASHARE_LAB_PANEL`：面板目录，默认 `~/code/ashare-lab/data/panel`。
- `ashare_lab_available()` 同时检查源码导入与面板文件：`daily.parquet/calendar.parquet/stocks.parquet/index_members.parquet/index_daily.parquet`。不能仅凭目录存在判断可用。
- 本地 Compose 的挂载见 `deploy/compose.local-dev.yml`；其他运行节点是否具备依赖须实际确认，不预设云端或数据库已经迁移。

## 输入与撮合

`run_signal_backtest(signals, start, end, config=BridgeConfig(), data=None, panel_dir=None)`：

- 输入为 `Series` 或含 `score` 列的 `DataFrame`，双层索引 `(datetime, instrument)`；转换为 `(date, code)` 后缀代码，拒绝重复索引并丢弃空分数。
- 未提供 `data` 时，从面板读取 `start` 前 450 个自然日至 `end`，用于上市天数和成交额筛选。
- 信号日 T 收盘后选股，T+1 开盘撮合；在 `eligible` 成员中按分数取 TopK 等权，同分按代码稳定排序；无信号日不调仓。
- 默认 `BridgeConfig`：资金 1000 万、TopK 50、中证800、上市 250 天、最低成交额 5000 万、整手 100 股；佣金 0.025%、过户费 0.001%、滑点 0.1%；印花税按 2023-08-28 前 0.1%、之后 0.05% 分段。实际请求可覆盖传入的配置项，不能把这些默认值套到标准 Qlib 路径。
- 失败返回 `BridgeResult(success=False, error_message=...)`，调用方必须检查，不能用空净值冒充成功。

## 结果口径

`BridgeResult` 包含 `nav/trades/annual_return/sharpe_ratio/max_drawdown/total_return/portfolio_dict`。前三项年化/夏普/回撤取 ashare-lab 指标（无风险利率 0），总收益为末日 NAV / 初始资金 − 1。

`portfolio_dict.report` 供 `RiskAnalyzer` 使用：`account=nav`、`cash`、`value=nav-cash`；`cost_amount` 是当日费用元额，`cost` 除以前日净值，`turnover` 为当日成交额/前日净值，`return` 是费前收益（减 `cost` 得净收益）；首日以前置初始资金作为分母。`execution_model=ashare_lab_next_open_lot` 用于识别执行语义。

## 接入回测服务

`backend/services/engine/qlib_app/services/backtest_service_runtime.py` 只对可映射的 `csi300/csi500/csi800/csi1000` 股票池且桥接依赖可用时允许该路径；自定义池、文件池和 `all` 不按指数猜测。调仓间隔先读策略 `kwargs.rebalance_days`，再读请求参数，缺省 1。

页面“A股真实撮合”开关发送 `use_vectorized`。条件不满足走标准 Qlib；已进入桥接路径但运行失败则报告错误，不静默换引擎。日志与结果必须能区分两种执行模型。

回归入口：`backend/services/tests/test_ashare_lab_bridge.py`、`test_ashare_lab_runtime_gate.py`；需要外部面板的用例须单独准备依赖，不能由合成单元用例推断真实撮合已验收。
