# Strategy Lab SDK 与接口合同

用途：对接编辑器与运行器、维护脚本兼容性和解释运行边界。用户操作见 [用户手册](Strategy_Lab用户手册.md)；本文不保留 Sprint 计划或历史验收指标。

## SDK

实现：`backend/services/engine/strategy_lab/sdk/context.py`、`bar.py`、`position.py`。

脚本至少定义 `setup(ctx)`，配置 `universe/start/end/cash`；按需要定义 `on_bar(ctx, bar)` 等运行器支持的钩子。股票池配置与请求 `stock_pool` 会共同影响实际标的，不能只看脚本字面名单。

| 能力 | 入口 |
| --- | --- |
| 历史与特征 | `history(symbol, n=20, field="close")`、`feature(symbol, name, n=1)`、`list_features()` |
| 快照与基准 | `snapshot()`、`benchmark_history()` |
| 交易意图 | `buy()`、`sell()`、`set_position()`、`set_target_holdings()` |
| 持仓 | `position(symbol)`、`positions()` |
| 风控声明 | `set_stop_loss(symbol, pct)`、`set_take_profit(symbol, pct)` |
| 研究与输出 | `param()`、`log()`、`plot_line()`、`plot_marker()` |

方法的可选字段、单位和校验以对应源码签名为准，不建立另一份易漂移的完整复制。价格与特征必须满足当时可得性；SDK 可读不代表数据无前视偏差。

## HTTP

路由实现 `backend/services/engine/strategy_lab/routers.py`，网关前缀下使用 `/api/v1/strategy-lab`：

| 方法与相对路径 | 行为 |
| --- | --- |
| `POST /run` | 同步运行并返回结果 |
| `POST /run/async` | 提交，返回 `run_id` |
| `GET /run/{run_id}/status` | SSE 进度，支持 `last_index` |
| `GET /run/{run_id}/result` | 查询结果；未完成不是空的成功结果 |
| `POST /overfit-check` | 执行四关诊断，可能多次回测 |
| `POST /translate` | 转换并保存模板 |
| `POST /watch`、`GET /watch`、`DELETE /watch/{script_sha}` | 登记、列出、移除扫描脚本 |
| `GET /signals` | 查询最近扫描产物 |
| `POST /scan/run-now` | 触发扫描，产生计算与写入 |

运行请求字段：`code` 必填；`params/options` 为字典；可传 `qlib_data_path`、`stock_pool`、`drawn_lines` 和 `timeout_sec`。数据路径需与实际运行环境匹配，不把宿主路径直接当容器路径。

进度与结果通过 runner/progress/result_collector 存取。结果包含配置、指标、净值、交易、日志、`script_sha` 和可选 `data_snapshot_at` 等；精确字段见 `RunResult`。`script_sha` 是代码与排序后参数的哈希，不是数据或环境完整指纹。

## 安全与运行边界

AST 白名单由 `runner/ast_checker.py` 定义，禁止危险模块、内置调用及反射属性。执行器在子进程运行，达到超时会终止 worker。

**不能把这些措施当安全沙盒证明。** 当前 `subprocess_runner.py` 启动的是同运行环境的 Python 子进程；文档不承诺脚本已获得独立只读文件系统、断网或单租户 cgroup。模块白名单内存在可触及系统资源的对象，只允许可信研究脚本，不向不可信多租户开放执行入口。

## 诊断评分边界

四关实现为 `overfit/runner.py`；总分按 `0.30/0.30/0.20/0.20` 加权。跳过/失败/warning 必须与分数一起解释，不能隐藏后称“通过”。

当前第四关对日收益洗牌后比较累计收益，顺序置换不改变收益乘积，不能据此声称统计显著性或可靠防过拟合。前三关也不能替代冻结候选族、完整成本和真正未见样本。页面评分不授权实盘。

## 转换与定时任务

`translator.py` 负责 SDK 脚本转模板；`cron/daily_scan.py` 负责扫描登记和产物。转换前后必须检查语义；登记扫描不会自动启动调度器，也不等于下单。任何生产/交易使用另行遵守对应模型、数据、风控与执行端合同。
