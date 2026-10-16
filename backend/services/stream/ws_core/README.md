# Stream WebSocket 协议

用途：对接与排查行情订阅和心跳。实现入口是 `server.py`，由 Stream 服务同时挂载 `/ws` 与 `/api/v1/ws/market`；两者共用协议。

## 握手与消息

默认本地地址 `ws://127.0.0.1:8003/ws`。客户端按实例的认证配置提交 JWT（`token` 查询参数或 `Authorization: Bearer ...`）；不要把明文 token 放进日志、截图或仓库。

建立连接后服务端返回 `type: "welcome"` 和连接标识。发送：

```json
{"type":"subscribe","topic":"stock.600519.SH"}
```

收到 `subscribed` 仅代表订阅受理，不代表数据源已有新行情。取消订阅使用同一 `topic`、`type: "unsubscribe"`；服务端返回 `unsubscribed`。

心跳：客户端发送 `{"type":"ping"}`，服务端返回 `type: "pong"` 与时间戳。行情 payload、批量订阅和其他主题以 `server.py`、对应 pusher 与前端 `websocketService` 为准。

## 排障顺序

1. 确认目标 Stream 的 `/health`、端口映射与 WebSocket 升级是否成功。
2. 核对 JWT、用户/租户身份及订阅主题；不要仅凭连接成功判断受保护主题已获授权。
3. 已收到订阅确认但没数据时，检查对应 pusher 的数据源、新鲜度和交易时段，再检查客户端监听器是否重复注册或提前清理。

本指南不承诺指标计算、交易执行或历史文档中的 QMT Bridge 能力；它们不能从通用 WebSocket 订阅推导出来。
