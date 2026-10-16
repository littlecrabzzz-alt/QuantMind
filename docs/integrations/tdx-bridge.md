# 通达信桥接配置与排错

用途：在明确需要时重新配置 Windows 通达信桥、连接 QuantMind 并进行只读诊断。这是可选集成，不是当前已有实例连接证明。基础 Compose 已注明旧通达信内网桥下线；不再沿用旧私有 IP、共享目录或凭据。

QuantMind 代码入口为 `backend/services/live_trading/services/broker_client.py` 的 `TdxBroker` 和 `tdx_push_service.py`；Windows 桥源码在 `tools/bridge-windows/`。它与大 QMT 执行端是不同通道，后者见 [大 QMT 指南](../大QMT真单镜像_部署与上线手册.md)。

## 能力与边界

```text
QuantMind 运行实例 → HTTP/Bearer → Windows 桥 :8550
                                      ↓
                          Windows 本机通达信 :17709
```

- HTTP 提供账户/委托查询、信号推送、执行计划和撤单等接口；通达信端能力依客户端版本、插件、券商权限及账号而变。
- Windows `:17709` 是本机接口，不应暴露给远端直连。跨机器访问经过桥；不要通过公开映射解决连接问题。
- 返回委托号、待确认、已提交和已成交是不同状态。不同账号可能要求人工确认或允许直接提交，不能依据旧测试断言一定弹窗。
- 选股板块推送不等于下单，但桥内止损守护或已接收计划仍可能产生订单。仅关闭 QuantMind 推送不能证明 Windows 端没有在途动作。
- 源码有文件同步通道，但当前 QuantMind `TdxBroker` 是 HTTP 客户端，不承诺自动切换 SMB 容灾。仅 HTTP 接入无需为了照抄旧文档挂载共享盘。

## Windows 部署

1. 准备支持所需 TQ 能力的通达信并登录正确账号；先确认账户/客户端版本，不使用真实下单作探测。
2. 将 `tools/bridge-windows/` 的配套源码与配置复制到受控目录，使用 Python 3.10+ 安装其 `requirements.txt`；当前类型注解使用 `str | None`，旧指南的 Python 3.9 要求已不足。桥 Python 与通达信插件 Python 可能不同，缺 `numpy/pandas` 时确认装在哪个解释器。
3. 生成独立强 token，保存在私有配置或安全环境中，与 QuantMind 侧一致。不要复用文档、发布包、Git 历史或别人实例中的 token。
4. 审阅 `config.yaml` 中监听地址、TDX 本机 URL、通道、订单跟踪和日志目录；保留已有状态，避免覆盖生产配置。
5. 在桥源码目录启动 HTTP 模式：

   ```powershell
   $env:BRIDGE_AUTH_TOKEN = "<独立强随机token>"
   python -m main --mode http --config config.yaml
   ```

   占位字符串必须替换，不能作为真实 token。停止已有进程或重启桥属于维护操作，先核对在途订单与止损守护。

`setup.ps1 http` 是可选辅助脚本，会安装/升级依赖、探测通达信 Python 并添加防火墙规则，不是无副作用启动器。它的默认防火墙规则未限定远端主机；使用时必须另行收紧到可信调用方。脚本/启动日志可能打印 token 或片段，分享前脱敏。

## QuantMind 侧配置

在实际实例的私有配置中设置，不在本地 Mac 沙盒里绕过禁用实盘的 overlay：

```dotenv
TDX_BRIDGE_URL=http://<Windows桥主机>:8550
TDX_BRIDGE_TOKEN=<与Windows一致的强随机token>
TDX_ACCOUNT=<目标资金账号>
TDX_ACCOUNT_TYPE=stock
ENABLE_TDX_PUSH=false
ENABLE_REAL_TRADING=false
REAL_BROKER_TYPE=tdx
```

`false` 是初始安全示例，不代表 Windows 端自身没有持仓或订单。按目标实例已有入口应用配置，见 [运行与部署](../部署指南.md)；不要裸 Compose 重建或覆盖其他券商配置。

需要推送时单独配置 `ENABLE_TDX_PUSH`；需要真实执行时另行完成券商选择、实盘授权和限额/对账核实。设置 `REAL_BROKER_TYPE=tdx` 本身不证明所有策略已经路由到它，页面持久化选择也需核对。

## 只读检查

先在 Windows 检查：

```powershell
curl.exe http://127.0.0.1:8550/api/v1/health
```

再从真正的 QuantMind 网络环境访问 `http://<Windows桥主机>:8550/api/v1/health`，避免只验证宿主能访问而容器不能访问。健康状态和 `tdx_connected` 不证明账号正确、具有下单权限或交易链路已验收。

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 桥与通达信连通状态 |
| `POST /api/v1/account/query` | 账户与持仓查询（需 Bearer） |
| `POST /api/v1/orders/query` | 当日委托查询（需 Bearer） |
| `POST /api/v1/plans/execute` | 执行计划，可能真实下单，不是检查接口 |
| `POST /api/v1/orders/cancel` | 撤单，有交易副作用 |
| `/api/v1/sltp/*` | 止损守护配置/状态，配置可能产生后续订单 |

依据实际账户、持仓与当日委托对账后才讨论交易验证。超时后先查券商委托，不盲目重发订单。

## 排错与安全

| 现象 | 先检查 |
| --- | --- |
| 401 | token 两端是否一致，是否发送 Bearer，避免打印值 |
| `tdx_connected=false` / TDX unavailable | 通达信是否运行并登录，本机 17709 与插件解释器依赖 |
| 运行主机连接不上 8550 | 桥监听地址、网络路线、防火墙来源范围与容器网络 |
| 委托待确认/无成交 | 通达信与券商的实际确认/拒单/成交状态，不依赖客户端推测 |
| 选股没有推送 | 目标实例配置、推理完成日志和实际推送开关；不要因此开启实盘 |

桥的部分只读状态、缓存和 UI 路径豁免 token 鉴权，因此 token 不能替代网络隔离。限制 8550 到可信主机，不公开 UI、账户日志或缓存；共享目录若另行启用，凭据应独立保管，不放在命令历史或文档中。

桥运行日志在 `data/logs/bridge.log`，执行回报在配置的共享/回报目录。保留订单跟踪与止损状态，不通过删除状态文件消除错误。程序化交易的券商权限、报备与合规要求须独立确认。
