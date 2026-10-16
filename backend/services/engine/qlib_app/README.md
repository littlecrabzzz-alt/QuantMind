# Qlib 回测适配层

用途：维护网关到执行器的回测合同，定位任务、策略加载与结果问题。应用由 `backend/services/engine/main.py` 挂载，客户端通过 API 网关访问 `/api/v1/qlib`。

## 请求与任务

- `POST /backtest`：同步执行；`?async_mode=true` 时提交 Celery 并返回 `backtest_id/task_id`。队列不可用返回 503，不创建进程内替代任务。
- `GET /backtest/{backtest_id}/status`：查状态；`GET /results/{backtest_id}`：查结果；`GET /history/me`：查本人历史。
- `GET /compare/{id1}/{id2}` 与 `DELETE /results/{backtest_id}` 必须遵守认证用户归属。身份由 `api/identity.py` 从请求解析，不信任任意用户 ID 覆盖。
- 异步请求生成的 `backtest_id` 必须一直透传到 worker 与持久化层，否则提交与轮询会断链。

接口字段和完整端点以 `api/` 与 `schemas/backtest.py` 为准，优化和风险接口不要继续堆入 `api/backtest.py`。

## 执行与存储

- `services/backtest_service.py`：服务入口；`backtest_service_runtime.py`：运行；`backtest_service_query.py`：查询与进度；`backtest_persistence.py`：持久化。
- `services/strategy_builder.py` 与 `utils/strategy_adapter.py`：策略构建、路径解析与参数适配。用户代码规范见[本地策略说明](../../../../user_strategies/README.md)。
- `backend.shared.strategy_storage.StrategyStorageService` 承载 PG 元数据与 COS 代码；`services/user_strategy_loader.py` 保留 `STORAGE_MODE=local` 或数据库不可用时的文件扫描。不能把磁盘目录存在等同于策略已注册给某用户。
- 数据提供器、模型目录、Redis 认证和存储模式必须与目标实例实际配置一致，不能照抄历史机器路径。
- 请求 `pool_id` 经[股票池解析器](../../../shared/stock_pool/README.md)物化；空池不能扩大为全市场。
- “A股真实撮合”路径及与标准 Qlib 的时点差异见 [ashare-lab 合同](../../../shared/ashare_lab_bridge/README.md)。

## 排障顺序

1. 先确认网关认证与租户身份，再查 `backtest_id/task_id` 是否一致。
2. 异步任务不启动时检查对应 Celery worker、队列与 Redis 配置；不要重复提交来掩盖原任务状态。
3. 加载失败时核对有效模型、策略代码来源、provider 的 instruments/calendars 与股票池覆盖。
4. 用任务日志中的 `event`、`backtest_id` 关联 worker、执行器和结果记录。缺失/空结果不能当零收益成功回测。
