# Mac 单节点运行（local primary）

2026-10-14 用户确认：QuantMind 改为纯本地运行，Mac 是唯一主节点；云端停写，数据保留作冷备份；暂停 QuantMind 代码目录的 Syncthing 同步；8000 端口固定指向本机。本文件是这次改造的规格，取代 AGENTS.md「双端开发约束」中关于云端为权威节点的部分。

## 角色

新增节点角色 `QM_NODE_ROLE=local`（Mac 主节点）。与已有角色的关系：

| 行为 | authority（旧云端） | sandbox（旧 Mac 沙盒） | local（新） |
|---|---|---|---|
| 业务库是否权威 | 是 | 否（快照副本） | 是 |
| 应用内供应商采集（`upstream_collection_allowed()`） | 否 | 是 | **否**（采集由 Mac 的 `com.quantmind.market-source` 与原生 Tushare worker 负责，不在应用里重复采集） |
| celery-beat 的 `tushare-acquire-continuation` | 有条件开启 | 无 | **不开启** |
| `tushare_pipeline.authority()` | 云端挂载校验 | 拒绝 | **拒绝**（不变：Tushare 原生 worker 用 `archive` 角色） |
| 研究工作台 `research/runtime.settings()` | 允许 | 允许 | **允许** |
| `docker_host_paths.host_path` | 非 sandbox 逻辑 | sandbox 校验 | 非 sandbox 逻辑（HOST_RUNTIME_PATH 为 `<项目>/.local-primary/project`） |

代码里所有判断 `QM_NODE_ROLE` 的地方都要显式考虑 `local`，不要靠"不等于某值"顺带放行。

## 运行目录与 Compose

- 运行状态：`<项目根>/.local-primary/`（加入 `.gitignore` 和 `.sync-code-ignore`），其中 `project/{data,db,models,logs,user_pools_local}` 为业务运行数据，`AUTHORITY.json` 记录接管信息。
- Compose 项目名 `quantmind-local`（容器名前缀 `quantmind-local-`，卷名前缀 `quantmind-local_`）。**不得**复用或修改旧的 `quantmind_*`（2026-09-08 前的 Mac 主库）和 `quantmind-dev_*`（沙盒）卷与容器。
- 新增 `deploy/compose.local-primary.yml`（只给 `scripts/local-primary.sh` 用；脚本导出 `QM_PRIMARY_PROJECT=<项目根>`、`QM_PRIMARY_STATE=<项目根>/.local-primary/project`，overlay 用这两个变量取路径，缺失时报错），以 `deploy/compose.local-dev.yml` 为蓝本，区别：
  - 所有服务 `QM_NODE_ROLE: local`，`HOST_RUNTIME_PATH` 指向 `.local-primary/project`；
  - 包含业务 `celery-beat`、`celery-worker`（队列 `market_sync,qlib_backtest_srv`）、`data-gateway`、`huntly`、`rsshub`、`qwenpaw`、`web`。不因历史 `research/settings.json` 启动 `research-worker`；研究 worker/agent 不自动重启，Strategy Lab 自主扫描和应用内行情采集派发关闭。既有生产推理、资讯和市场分析按原语义保留，现有独立 R01 容器不受影响；
  - 不包含 `tushare-worker`、`tushare-document-worker`；
  - `ENABLE_REAL_TRADING: "false"`、`ENABLE_TDX_PUSH: "false"` 在所有服务上保留；
  - 端口只绑 127.0.0.1：API 8000，web 3080；其余服务不对外发布端口；
  - ashare-lab 源码与固定面板只读挂载仓内 `vendor/ashare-lab/{src,data/panel}`，不再默认依赖 `~/code` 活跃源码；`/data/tushare` 只读挂载 Tushare 归档；
  - `restart: unless-stopped`（主节点需要在 Docker Desktop 重启后恢复）。
- `docker-compose.yml` 与 `deploy/compose.cloud.yml` 不改。

## 脚本 `scripts/local-primary.sh`

沿用 local-dev.sh 的写法（启动时读入自身内容、加锁、失败回滚）。子命令：

- `adopt <snapshot_dir>`：只接管最终停写窗口快照，不凭 `COMPLETE` 授权。复用 `dual_node_snapshot.verify_snapshot` 重算归档 SHA 和全部 runtime 清单，要求哈希覆盖 `COLD_BACKUP.json`；实时核对云端 latest 身份、明示 writer stopped/restart=no、stack/timer disabled、旧 snapshot service inactive，不可达即拒绝。恢复到全新 `quantmind-local_*` 卷后，重算复制清单，并将恢复库重新 dump，与来源逐表 COPY 行的无序摘要、行数及 sequence/其它 data 语句核对；不打印业务数据。写 `RESTORE_VERIFIED.json`，再次实时核云停写，才写 `AUTHORITY.json`（含两端验证收据）及 `READY`。失败只回收本次创建的状态与卷，不碰其它卷、源快照或原件。
- `start`：要求已验证的最终接管状态，并拒绝同时运行 local-dev。持久 disable/bootout 旧 `com.quantmind.cloud-tunnel` 与 `com.quantmind.snapshot-pull`，保留改名后的 plist，避免把冷备 QuantDB 反向应用到新主节点。先仅启动 db/redis，用 `local_primary_broker_guard.py` 只读核 broker list/priority 队列及 unacked 路由，写 `/data/local-primary/BROKER_GUARD.json`；业务 qlib/market 队列有旧待办即拒启消费者并原样保留，不 purge，不启动 research/glm 消费者。通过后启动明示业务服务，观察 8000 health。
- `stop`：`down`（保留卷），不恢复云端隧道。
- `status`：服务状态、AUTHORITY.json、8000 归属。
- `install-autostart` / `uninstall-autostart`：安装 / 卸载 `~/Library/LaunchAgents/com.quantmind.local-primary.plist`（登录时执行 `start`）。模板放 `deploy/com.quantmind.local-primary.plist`。

local-dev.sh 的 `start` 在 `quantmind-local` 栈运行时必须拒绝（避免两个后端抢 8000 和同一份数据）。

### 云端最终停写窗口

`python3 scripts/dual_node_snapshot.py create --keep-writers-stopped` 是显式接管运维操作，不是日常备份。先停并禁用 `quantmind-snapshot.timer`，再按旧 create 相同的 `storage_lock → snapshots/.lock` 锁序互斥；锁内重查旧 snapshot service inactive，停 beat 后复核 active/reserved/scheduled 与研究 agent，只有空闲才停止明示业务 writers。记录各 writer 状态，设 restart=no 并 disable `quantmind-stack.service`，不执行整栈 stop，也不动其它应用、R01 或 Redis 参数。PG 保持运行；Redis 仅为冷卷复制短暂停后恢复。最终模式正常/异常退出都不恢复业务 writer，旧恢复点不 prune，失败 staging 原样保留。

快照生成后 `pull` 下载并核哈希；可用 `python3 scripts/dual_node_snapshot.py verify --root <snapshot_dir>` 独立复核。`COLD_BACKUP.json` 只证明采集窗口，不能代替 adopt 两次实时权威门控。云端异常后的恢复必须显式确认本地主节点未启用；不得以旧定时器或隧道自动回退成双主。

## 行情数据

`scripts/local_market_source.py`：当 `.local-primary/READY` 存在时进入 local-primary 模式——跳过所有向云端交付的步骤（不 ssh、不上传），把已校验的 QuantDB / BC 版本应用到 `quantmind-local` 栈（复用 `scripts/quantdb_refresh.py` 的本地应用逻辑，目标 compose 项目和运行目录换成 local-primary）。没有 READY 时行为不变。

## 回测

快速回测页的"A股真实撮合"开关默认打开（localStorage 无记录时为 ON）。

## 文档

通用开发规则以主仓现行 AGENTS 为准；不覆盖用户已更新的 AGENTS/CLAUDE。这里记录部署语义，实际源码、进程、数据截止日与验收证据另在本次 coordination 记录中标明。

## 不做

- 不修改共享 `.env.local` / `config/runtime.env`；云端停写只使用上述明确的接管操作。
- 不碰实盘与券商接口。
- 不新研究/择参，不替换唯一撮合引擎或另建账户平台；冻结观察账本接管使用已纳入的同一引擎。
