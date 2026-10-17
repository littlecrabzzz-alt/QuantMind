# QuantMind 开发约定

## 开发边界

- 开发、业务服务与数据均在本机。Main 工作树用于开发，业务服务使用 Library 下已核准的运行快照；源码修改不会自动发布。
- 部署、维护、数据恢复和实盘操作须属于明确任务；实盘开关保持关闭。
- 保留已有修改，只提交本次明确文件。实验或并行任务可用 worktree，但数据库、配置和容器挂载仍需单独隔离。
- 测试只写独立沙盒或临时目录。操作前核对 Compose 项目、端口和数据挂载，不能在主业务库上试写。
- 改配置前核对挂载和作用范围；凭据不入代码、文档或日志。不因清理、初始化或恢复而删除数据库、采集检查点、研究输入或成果。

## 开发与验证

优先扩展现有页面、API、任务和存储入口，不另建重复系统。命令均从仓库根目录按需运行：

```bash
bash scripts/local-dev.sh status
bash scripts/local-dev.sh start core                         # 已准备沙盒，且主业务已停妥
npm run dev:react --workspace=electron -- --host 127.0.0.1    # Web；已有服务不重复启动
npm run dev --workspace=electron                             # Electron，二选一
npm run typecheck                                            # 前端变更
python backend/run_tests.py unit                             # 隔离的测试配置与数据
```

Python 使用 ruff，行宽 88。验证实际改动路径，不以编译成功代替行为验收。沙盒 Python 变更在相关任务空闲后用 `scripts/local-dev.sh restart-backend` 加载；研究 worker 用 `restart-research-worker`。业务发布使用已核准运行快照和受管入口。前端使用 Vite HMR；无依赖变化不重建后端镜像。纯文档变更不重启服务。

## 关键约束

- 策略 CRUD 只走 `backend/shared/strategy_storage.py`；外部报单前先本地持久化。
- 成交/委托使用 `TIMESTAMPTZ` 和 aware UTC，复用 `backend/shared/utc_datetime.py`，JSON 带 `Z`。
- 股票代码转换用 `StockCodeUtil`，前端用 `normalizeStockCode`：QuantDB `600036.SH`、Qlib `sh600036`、PG/大多数 API `SH600036`，不手写切片混用。
- 不同时启动内嵌和独立业务 Celery worker；`research-worker` 消费独立队列，不按全局 `brpop` 数量判断重复。
- 市场原始数据由本地唯一采集器持有；采集目录、业务库、沙盒及固定研究输入分开，只使用校验完成的数据版本。
- Qlib 复用 `QlibDataBuilder.build_all` 的校验和原子发布；验收实际截止日、派生结果和页面，不以下载成功代替可用。
- QuantBot 技能通过 `scripts/quantbot_init.sh` 的 API 流程安装，不手工复制进技能池。

## 研究与文档

研究先固定输入版本和截止日。最后六个日历月只用于策略、参数和评价冻结后的最终验证；开发、选品、调参和全样本预处理不得使用保留段。已接触的数据不再算独立验证。具体课题日期与状态读取其冻结方案，不在通用规则里复制。

研究产物保留输入版本、代码版本、参数、任务 ID 和验证证据；历史研究、虚拟盘、实盘分别标明。

本文件只放需要常驻上下文的约束。[README.md](README.md) 是项目入口，[文档索引](docs/README.md) 说明各指南用途，均按任务读取。不要默认遍历文档、读取旧工作记录或为普通修改新建流水账。修改规则时替换旧结论，不追加互相覆盖的历史说明。
