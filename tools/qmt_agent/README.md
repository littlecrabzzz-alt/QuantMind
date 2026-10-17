# QMT Agent 独立部署包

QMT Agent 在装有券商 QMT/`xtquant` 的 Windows 主机独立运行。Electron 提供凭据初始化、在线状态和下载入口；关闭 Electron 不应被当成停止 Agent 的方法。真实交易前必须确认账号、环境和平台交易门禁。

## 安装与运行

优先使用平台提供的 Windows 安装器；源码包解压后的入口为 `desktop_app.py`（桌面配置与托盘）或 `qmt_agent.py`（CLI）。具体配置字段、日志路径和排障命令统一见同目录 [help.md](help.md)，该文件也由桌面壳“帮助中心”直接加载。

仓库根目录下的源码入口：

```bash
python tools/qmt_agent/desktop_app.py
python tools/qmt_agent/qmt_agent.py --config <配置文件路径>
```

在独立源码 ZIP 中，进入解压目录后使用 `python desktop_app.py` 或 `python qmt_agent.py --config <配置文件路径>`。配置和凭据放在运行主机，不提交到仓库。缺少 `xtquant` 时的联调/mock 行为不能证明真实 QMT 已连接。

## 维护与发行

- 版本唯一来源是 [version.json](version.json)，不在说明中锁定版本号。
- 从仓库根目录运行 `python tools/qmt_agent/build_windows_agent.py` 构建 Windows 发行包；脚本的 `ZIP_PACKAGE_FILES` 是源码包清单，`qmt_agent_desktop.spec` 是 PyInstaller 资源清单。README 和 help 都是交付资源，不能只在仓库删除而不调整打包链。
- `runtime_supervisor.py` 负责监督，`schedule_policy.py` 定义时段和上报策略，`runtime_workers.py` 执行后台任务；时段和默认参数以当前代码及配置为准。
- 鉴权使用 Access/Secret Key 换取短期 bridge session，再连接 `ws/bridge`；账户快照和心跳共同影响平台就绪判断。仅“测试连接成功”不能代替持续在线状态。

QuantMind 平台和业务数据库只在本地 Mac 运行；Windows 上的 QMT Agent 是可选券商交易适配器，不承载另一套 QuantMind 业务栈或开发源码。启用前核对实际平台连接地址、账户和交易授权；本地单机运行不自动开启实盘权限。
