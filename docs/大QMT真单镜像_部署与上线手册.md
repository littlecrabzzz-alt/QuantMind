# 大 QMT 执行端与真单镜像

用途：配置可选的 Windows QMT 内置执行端、只读排查连接，再按独立授权启用真实订单镜像。QuantMind 业务在本地 Mac 运行；本指南不授予下单或覆盖数据的权限。

真单镜像是模拟成交旁路：虚拟账本与真实委托独立记账。开启镜像可能真实下单；“模拟交易”页面名称不代表不存在真单风险。

## 前置条件

- Windows 已安装并登录具备相应交易权限的大 QMT，已安装其 Python 组件。
- QuantMind 客户端依赖与当前 `xtquant-big-convert[redis]` 版本匹配；QMT 内置 Python 服务端使用配套文件，不直接安装要求更高 Python 版本的客户端包。
- 建议独立 Redis 实例，设置强密码和主机白名单，不暴露公网；不要因为代码存在回退就默认复用业务 Redis。
- 券商权限、账户类型、报备和申报限制由实际账户核实。本项目不能证明某条技术通道天然合规。

## Windows 配置与启动

1. 在安装客户端依赖的受控 Python 环境，从仓库根目录导出桥接包：

   ```bash
   python backend/scripts/export_qmt_bridge_kit.py
   ```

   默认生成 `dist/qmt-bridge-kit/` 及 zip。首次导出后核对版本；不要使用 `--force` 覆盖已有私有账号配置。
2. 将包内配套文件复制到 QMT 的 `python` 目录。必需 `bigqmt_signal_trader/`、`bigqmt_signal_trader_strategy.py`、`bigqmt_signal_trader_redis_rpc_runtime.py`、`BIGQMT_REDIS_DRYRUN.py`。不要混用不同上游版本。
3. 编辑该目录的私有 `bigqmt_signal_trader_local_config.py`：

   ```python
   BIGQMT_ACCOUNT_ID = "<资金账号>"
   BIGQMT_ACCOUNT_TYPE = "STOCK"  # 信用账户用 CREDIT，两端必须一致
   BIGQMT_REDIS_CONFIG = {
       "host": "<桥Redis主机>", "port": 6380, "db": 0,
       "password": "<独立强密码>",
       "rpc_allow_order_methods": False,
       "rpc_process_in_listener": True,
       "rpc_listener_methods": ("*",),
       "rpc_background_threads": True,
       "schedule_adjust": True,
       "schedule_adjust_interval": "100nMilliSecond",
   }
   ```

   保持下单开关 `False` 验只读。账号配置不得提交 Git、打入公开发行包或贴入诊断日志。
4. 在 **QMT 策略编辑器**加载运行 `BIGQMT_REDIS_DRYRUN.py`，不是在命令行运行 `python.exe`，也不是独立 Python 进程。只有内置策略运行方式才注入 `passorder/get_trade_detail_data`。名称含 DRYRUN 不保证禁止下单，真正开关是配置。
5. 检查面板出现 RPC started 和 init ok；若只显示 finished，检查加载方式。QMT 重启后须重新运行服务端策略。

本项目客户端当前使用 Redis。包中可选 ZMQ 入口不代表 QuantMind 已接好该传输，不把它作为可直接切换的容灾路径。

## QuantMind 配置与只读诊断

设置页“券商实盘接入”选择“大 QMT（执行端）”，配置 `enabled/account_id/account_type/strategy_name` 及桥 Redis 地址、端口、库号、密码。页面配置存于 `broker:config:qmt_exec`，优先于 `QMT_EXEC_*` 环境配置；编辑环境变量不一定覆盖现有页面值。

服务端账户类型由 `BIGQMT_ACCOUNT_TYPE` 决定，不能仅改客户端页面。信用账户按 STOCK 查询可能返回零资产，不应解释为空仓。

先点“测试连接”核对资产与持仓。逐层诊断脚本为 `backend/scripts/qmt_bridge_selftest.py`；在正确的后端 Python 环境、以 `backend` 为工作目录并使仓库根位于 `PYTHONPATH` 后执行：

```bash
python scripts/qmt_bridge_selftest.py
```

它按配置 → Redis 网络 → RPC 监听 → 账号 → 委托逐层只读检查。失败/跳过不算通过；不要用下真实委托验证网络。代码入口在 `backend/services/live_trading/services/qmt_exec_client.py`。

## 从只读到镜像下单

这一步必须作为独立交易授权处理，不能由部署、文档检查或健康检查自动完成。

1. 核对账户与券商规则，先设置可承受的单笔/单日金额、笔数、标的数及滑点限制。
2. 确认真实交易开关与 A 股选择器：`ENABLE_REAL_TRADING=true` 且 `broker:selected:CN=qmt_exec`。Mac 隔离环境默认关闭实盘，不在其中绕过 overlay 开关。
3. 确认 QMT 端允许订单方法后，再配置镜像白名单；空白名单不发单，不用 `*` 代替授权范围。
4. 在“真单镜像”卡开启镜像，按已批准范围执行验证，逐笔核对真实委托、成交回报与虚拟账本。最小整手金额也可能很大，不能把“100 股”通称低风险小额。
5. 核对成交/委托 poller、账户快照、对账及通知后，才考虑扩大范围。

## 停止与排错

先急停并关闭镜像，确认不再发新单。**急停不等于撤销在途委托或清仓**；已有订单必须在券商端核对。不要为了回滚自动切到另一个实盘券商。

| 现象 | 排查 |
| --- | --- |
| RPC 不通 | Windows 策略是否运行、桥 Redis 网络/密码/防火墙；按自检失败层处理 |
| `ORDER_DISABLED` | QMT 服务端订单方法开关；只读阶段保持关闭属于预期 |
| 资产为零/账户类型不一致 | 两端账号及 STOCK/CREDIT，先确认查询对象 |
| 镜像跳过 | 真实交易开关、通道选择、白名单、急停及限额；查看 `blocked_reason` |
| 委托状态不更新 | `qmt_exec_poller`、Windows 服务端日志及真实券商委托 |
| 快照超时 | QMT 登录状态、同步任务与 Redis 连通性，不根据旧快照继续扩大仓位 |

主要实现：`real_mirror_service.py`、`qmt_exec_poller.py`、`qmt_account_sync_task.py`；控制面为 `backend/services/trade/routers/qmt_mirror.py`。日志包含账号与交易信息，分享前脱敏。接口正常与历史验收均不能代替当次对账。
