# 后端开发入口

QuantMind 的业务边界保留为四个 FastAPI 服务；当前仓库 `docker-compose.yml` 的 OSS 部署把它们运行在同一个 `quantmind` 容器内，不是四个独立容器。

| 服务 | 默认端口 | 应用入口 | 负责范围 |
|---|---|---|---|
| API | 8000 | `services/api/main.py` | 认证、用户、管理与服务代理 |
| Engine | 8001 | `services/engine/main.py` | 策略生成、回测、模型推理、投研计算 |
| Trade | 8002 | `services/trade/main.py` | 订单、成交、账户、模拟撮合与交易控制面 |
| Stream | 8003 | `services/stream/main.py` | 行情 REST 与 WebSocket 推送 |

端口表是代码默认值，不是服务正在运行的证明；本地开发源收敛不代表数据库或服务已迁移。

## 启动与配置

部署、环境准备和数据目录从[根 README](../README.md)进入。`main_oss.py` 根据 `SERVICE_MODE=all/api/engine/trade/stream` 调度上述服务，端口可由 `API_PORT/ENGINE_PORT/TRADE_PORT/STREAM_PORT` 覆盖。

`main_oss.main()` 在启动服务前执行 schema 初始化、管理员播种和内置股票池准备，可能写数据库与成员文件；不要把运行它当只读检查。单独启动 `services/*/main.py` 与走 OSS 启动器的初始化行为不同。

- 配置来源由 `shared/config/` 及部署注入环境决定；不要在服务子目录另维护一套数据库凭据。
- 普通客户端先访问 API 网关，由其转发鉴权上下文；内部调用密钥不得下发桌面端。
- 保持 `shared/` 为跨服务公共能力；不要通过导入另一服务的私有实现绕过边界。
- 运行态与资产归属以实际配置、数据库和挂载为准，不沿用旧 GKE 参数表或历史验收结论。

## 领域合同与排障入口

- [Qlib 回测](services/engine/qlib_app/README.md)：异步任务、策略存储和结果查询。
- [模型推理](services/engine/inference/README.md)：模型选择、数据日与信号生效日。
- [因子挖掘集成](services/engine/rd_agent/README.md)：RDLoop、市场适配与运行资源。
- [股票池](shared/stock_pool/README.md)：成员事实源、引用语法和空池语义。
- [ashare-lab 桥接](shared/ashare_lab_bridge/README.md)：次日开盘撮合与适用条件。
- [WebSocket 协议](services/stream/ws_core/README.md)：握手、订阅和心跳。
- [最小联通检查](DOCS/backend_smoke_checklist.md)：只用于已配置实例，不代替业务回归。

AI-IDE 的 `services/engine/routers/ai_ide/skill_templates/*.md` 由 `skill_engine.py` 加载为运行时模型指令，不是普通开发说明；修改时应按提示模板合同评审并随运行包保留。
