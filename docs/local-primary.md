# Mac 单节点运行（local primary）

QuantMind 在 Mac 本地开发和运行。业务 API 使用本机 8000 端口，业务页面使用本机 3080 端口；Main 工作树保存开发源码，业务服务使用 Library 下已核准的运行快照。本页说明当前运行目录、版本安装和受管启停，不作为数据恢复或实盘授权。

## 角色

业务实例使用 `QM_NODE_ROLE=local`：

| 能力 | 本地业务实例 |
| --- | --- |
| 业务数据库 | 本机正式业务库，与开发沙盒隔离 |
| 应用内供应商采集（`upstream_collection_allowed()`） | 禁用；市场数据由本机独立采集器负责 |
| celery-beat 的 `tushare-acquire-continuation` | 不启动 |
| `tushare_pipeline.authority()` | 不授予采集权；Tushare 原生 worker 使用 `archive` 角色 |
| 研究工作台 `research/runtime.settings()` | 允许按任务使用，不自动启动研究 |
| 受管子容器路径 | `HOST_RUNTIME_PATH` 指向运行快照自己的 `.local-primary/project` |

涉及 `QM_NODE_ROLE` 的代码必须显式处理 `local`；测试不能依赖“不是某角色”而意外放行。

## 运行目录与 Compose

- 运行状态：`<运行快照>/.local-primary/`，其中 `project/{data,db,models,logs,user_pools_local}` 为业务运行数据，`AUTHORITY.json` 保存数据基线与验证信息；这些文件不入 Git。
- Compose 项目名 `quantmind-local`，容器名前缀 `quantmind-local-`、卷名前缀 `quantmind-local_`。开发沙盒使用独立 `quantmind-dev_*` 资源；不得复用其他项目的持久卷。
- `deploy/compose.local-primary.yml` 由 `scripts/local-primary.sh` 加载；脚本按所在运行快照设置 `QM_PRIMARY_PROJECT` 和 `QM_PRIMARY_STATE`：
  - 所有服务使用 `QM_NODE_ROLE=local`，`HOST_RUNTIME_PATH` 指向 `.local-primary/project`；
  - 包含业务 `celery-beat`、`celery-worker`（队列 `market_sync,qlib_backtest_srv`）、`data-gateway`、`huntly`、`rsshub`、`qwenpaw`、`web`。不因历史 `research/settings.json` 启动 `research-worker`；研究 worker/agent 不自动重启，Strategy Lab 自主扫描和应用内行情采集派发关闭。既有生产推理、资讯和市场分析按原语义保留，现有独立 R01 容器不受影响；
  - 不包含 `tushare-worker`、`tushare-document-worker`；
  - `ENABLE_REAL_TRADING: "false"`、`ENABLE_TDX_PUSH: "false"` 在所有服务上保留；
  - 端口只绑 127.0.0.1：API 8000，web 3080；其余服务不对外发布端口；
  - ashare-lab 源码与固定面板只读挂载仓内 `vendor/ashare-lab/{src,data/panel}`，不再默认依赖 `~/code` 活跃源码；`/data/tushare` 只读挂载 Tushare 归档；
  - `restart: unless-stopped`（主节点需要在 Docker Desktop 重启后恢复）。

### Main 源码与 Library 部署快照

Main checkout 仍是源码权威，保留在原 Documents 位置；不搬仓库、依赖或用户文件。
主节点实际运行的 `PROJECT` 则使用 `~/Library/Application Support/QuantMind/` 下独立、
全新的代码/部署快照。launchd、controller、Compose 和 restore 都使用这同一份已核准
字节，不再为日常运行必读 Documents。Main 后续编辑不自动改变已部署版本。

在 Main 中一次性执行文件安装入口：

```bash
scripts/local-primary.sh install-runtime \
  "$HOME/Library/Application Support/QuantMind/primary-runtime-<approved-version>" \
  "$HOME/Library/Application Support/QuantMind/primary-artifacts-20261016"
```

`install-runtime` 在 Docker/launchd/adopt 的门控之前独立分派，不探测或启动 Docker，
不安装 launchd，不恢复数据，也不创建 `.local-primary`、`READY` 或假的账户。
目标必须不存在且是真实 Library 管理根内的新目录；artifact-root 必须是已存在的
Library 真实目录，与代码快照不重叠，不能通过链接逃逸到 Documents 或其它位置。

复制范围是 Main Git tracked/staged 名单对应的**当前工作树字节**：
`backend/scripts/deploy/docker/config/strategy_templates/docs/requirements` 及必要根
Compose、requirements、`.dockerignore`、`pyproject.toml`。alphaagent 与
TradingAgents-astock 若是 nested Git，改用各自索引名单；不复制 `.git`。
不带 node_modules、venv、rd-agent、运行 data/models/logs、用户目录或模型/依赖二进制，
但保留已跟踪的 ORM `models/*.py`、alphaagent 日志模块等真正源码。
客户端政策文件及政策目录均不读取、不复制。
vendor 仅复制 ashare-lab 的 `src`、`frozen-source.json`、`frozen-data.json`、
`requirements.txt`；前端只带已有 `electron/dist-react` 构建资源，不重新构建。

Main 现有 `.env.local` 与 `config/runtime.env` 原字节复制为私有 0600 文件，
不生成凭据、不输出配置值、不更改 Main 原配置。快照的 `output` 链接到显式
Library artifact-root，vendor `data/reports` 重建为该归档的相对链接，不复制归档内容。
此 artifact-root 由唯一部署负责人迁移/维护，installer 不移动它，也不改变 Main 的别名。

最后写私有 `MAIN_CODE_MANIFEST.json`：`source_project/source_commit`、
nested commits、每个复制路径的 SHA-256/size/mode 以及符号链接目标。
标准输出仅给安装路径、总文件数/字节数与 manifest 字节 SHA，供安装验收及版本核对；
它证明本次安装的 Main 字节，不代表业务数据已恢复或服务已启动。
未来 controller 只核已安装快照和此 manifest，不回读 Main。失败的未完成目录保留，
无完整 manifest 就不能作为已核准部署版本；重试须选新的目录。


## 脚本 `scripts/local-primary.sh`

以下入口用于已准备并通过数据验证的本地实例；必须从当前已核准运行快照执行。不要手工补造 `READY`、`AUTHORITY.json` 或恢复收据绕过门控。

- `start`：要求数据基线和恢复验证齐全，并拒绝同时运行 local-dev。先启动 db/redis，再由 `local_primary_broker_guard.py` 检查业务队列及 unacked 路由；有未处理业务消息时拒启消费者，不清队列。通过后启动明示业务服务并检查本机 8000 health。
- `stop`：停止该 Compose 项目的服务，保留数据卷。
- `status`：只读查看服务状态、数据基线信息和本机 8000 端口归属。
- `install-autostart` / `uninstall-autostart`：安装 / 卸载 `~/Library/LaunchAgents/com.quantmind.local-primary.plist`（登录时执行 `start`）。模板放 `deploy/com.quantmind.local-primary.plist`。
- `install-runtime <new_Library_runtime_dir> <Library_artifact_root>`：以上述白名单安装代码/部署快照并输出 manifest SHA；纯文件操作，不触及正式运行资源。

local-dev.sh 的 `start` 在 `quantmind-local` 栈运行时必须拒绝（避免两个后端抢 8000 和同一份数据）。


## 行情数据

执行 `scripts/local_market_source.py` 前确认运行快照的 `.local-primary/READY` 及配置已核验。该模式将已校验的 QuantDB / BC 版本应用到 `quantmind-local` 栈，复用 `scripts/quantdb_refresh.py` 的本地应用与派生逻辑。实际生效版本、PG/Qlib/H5 截止日和真实消费查询分别验收；不得只用 READY 文件存在代替数据验证。

## 回测

快速回测页的"A股真实撮合"开关默认打开（localStorage 无记录时为 ON）。

## 文档

通用开发规则以根 `AGENTS.md` 为准。部署版本通过安装 manifest、数据基线和运行回执核对；变更历史通过 Git 查证，不另建协调流水账。

## 不做

- 不把私有 `.env.local`、`config/runtime.env` 或运行凭据写入文档、日志和 Git。
- 默认关闭实盘及交易推送，涉及账户或下单能力时单独确认授权。
- 文档维护和服务发布不自动触发研究、选参或收益作业；撮合及冻结观察账本继续复用既有引擎和账户入口。
