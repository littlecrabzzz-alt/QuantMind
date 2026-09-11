# QuantMind 开发与协作指南（AGENTS.md）

供开发者和 AI 助手共同使用。以下双端规则优先于后面的通用 OSS 命令；详细部署与恢复步骤见 [双端部署说明](docs/dual-node-deployment.md)，数据约束见 [数据写入规范](docs/development-data-contract.md)。

## 当前双端开发约束

Mac 和云端都可以改代码、做研究。**正式业务数据由云端维护；Mac 默认使用本地沙盒，可以写自己的数据库和文件，但不会自动把这些写入送回云端。** “代码同步”不等于“数据库同步”，也不等于“程序已经发布”。

- **主工作树**：两端共享的源码目录。Mac 为 `/Users/lizeyu/Documents/ChatGPT/投资/QuantMind`；云端入口为 `lzy-vm:/root/code/QuantMind`，真实目录为 SSD 上的 `/root/data/disk/quantmind/project`。云端正式服务直接挂载这里的后端源码。
- **worktree**：同一个 Git 仓库的独立代码副本，用于隔离分支和未完成修改；它不会自动得到独立数据库、配置或运行环境。
- **快照**：某次已校验的数据副本。下载新快照不会改变正在使用的本地沙盒；一次研究应固定输入版本。

| 内容 | 实际同步方式 | 开发时怎么用 |
| --- | --- | --- |
| 主工作树源码、`coordination/`、共享配置 | Syncthing 双向同步，包含未提交文件 | 同一文件同一时刻由一人/一端负责；不要把未提交当成未上线的保护 |
| `.git`、分支和提交历史 | 不由 Syncthing 同步 | 用 Git push/fetch 传递提交；主工作树换端后用 `handoff` 核对并显式对齐元数据 |
| 独立 worktree | 不自动双向同步 | 在另一端取得提交后建立自己的 worktree；不能复制 worktree 的 `.git` 路径文件 |
| 云端 PostgreSQL、Redis、模型和结果 | 云端持续写入；通过完整快照单向提供本地副本 | 不用文件同步工具复制运行中的数据库，不把 Mac 的旧数据覆盖到云端 |
| QuantDB 基础数据 | 复用快照校验，每小时从云端发布/拉取限定 Parquet 版本；本地空闲时应用并补齐行情表和 Qlib | 以 `.local-dev/QUANTDB_SYNC.json` 的 `applied` 和实际数据日期验收；本地修改冲突、活动任务或失败时保留数据并报错，下轮重试 |
| Mac `.local-dev/project` 和 `quantmind-dev_*` 数据库卷 | 独立沙盒，不参与双向同步 | 本地测试可写；完整库基线记录于 `.local-dev/SNAPSHOT_ID`；QuantDB 更新另记 `QUANTDB_SYNC.json`，本地新增结果保留 |
| Mac Tushare 镜像 | 云端发布固定版本后，Mac 独立定时下载并校验 | 按 `release_id` 只读使用；不是 QuantDB 的替代品，不自动导入本地 PostgreSQL/沙盒 |
| 依赖、镜像、虚拟环境、构建产物 | 不双向同步 | 按平台安装/构建；Mac 当前后端镜像为 amd64，在 Apple Silicon 上有架构转换开销 |

`.env.local`、`config/runtime.env` 也是共享文件，只是不提交 Git。**数据隔离不等于所有配置都隔离**：本地服务可能写入共享的 `config/`，改配置前要确认文件去向。机器专属路径、节点角色放部署覆盖层或节点私有配置；密钥不写进协作记录、测试输出或 Git。

## 后续数据协作：按项目共享（已确认，待实现）

后续按“两端独立开发和计算 → 有价值的数据按项目汇总云端 → 两端取得共享版本”的规范实施。临时测试数据留在本节点，云端开发也要隔离；指定共享项目的方案版本和已完成成果将支持联网增量同步，正式基础数据仍由云端统一校验发布。

共享归档与正式验收分开：本地成果可先共享供查阅，不要求仅为上传而重跑；同步不自动授予已验证或可交易状态。共同修改必须检查版本并保留冲突，重传幂等，本地删除不删除云端历史，运行中实验不自动换输入；队列、租约、缓存、凭据及进程状态不跨节点同步。

**当前尚未实现上述项目同步入口，继续使用现有沙盒和单向快照，不直接复制数据库或覆盖云端结果。** 第一版只做指定项目的方案、已完成实验和成果文件，复用现有 API/身份/任务机制。详细规则与验收统一维护在 [数据写入规范](docs/development-data-contract.md)，后续实现必须遵守，不另建一套同步规范。

## 开工前：认清节点、输入和协作者

1. 先读本机主工作树的 `coordination/README.md` 与对应主题记录，确认已有方案、负责文件和未完成项。已有主题优先复用。
2. 核对 `uname -s`、`uname -m`、`hostname`、`pwd -P`、`git status --short`、`docker context show`。Mac 上的容器也显示 Linux，不能仅凭系统名判断它是云端。
3. Mac 联网时在主工作树运行 `bash scripts/dual-node.sh handoff`。云端运行 `sudo -n python3 scripts/dual_node_check.py --node cloud`，只检查云端本身。Mac 离线时只继续已约定的文件范围和已准备的固定沙盒/隔离测试，联网后补双端核对。
4. 预检失败先看原因：源码尚在传输就等待后重试；Git 落后按下方交接流程处理；遇到 `.sync-conflict-*`、分支分叉、暂存修改或内容不一致，保留双方工作并解决，不能强制覆盖。

在 worktree 内可用 `git rev-parse --path-format=absolute --git-common-dir` 找到共同 `.git`，其父目录就是本机主工作树。协作记录始终写入这个主工作树的 `coordination/<主题>/`，不要写进 worktree 中的旧副本。

## 怎样开发

### Mac：默认本地沙盒

以下命令在 Mac 主工作树执行，按需要选择，**不是从上到下全部执行**：

```bash
bash scripts/local-dev.sh status          # 先看当前模式、服务与固定快照
bash scripts/local-dev.sh init            # 仅首次；已有沙盒/数据库卷时不要重复初始化
bash scripts/local-dev.sh start core      # 本地数据库、Redis、后端
# bash scripts/local-dev.sh start full    # 再加通用 worker、资讯和 QuantBot
# bash scripts/local-dev.sh start research  # 已准备研究模板/迁移后，启动专用研究 worker
# Vite 尚未运行时启动；不要重复占用 3000
npm run dev:react --workspace=electron -- --host 127.0.0.1
```

沙盒运行时，`127.0.0.1:8000` 指向本地 API，3000 的开发页面通常通过它访问本地数据库。后端普通源码挂载自主工作树，不是冻结在数据快照里的代码；Python 修改完成后，需要在相关任务空闲时执行 `bash scripts/local-dev.sh restart-backend`。研究 worker 的独立重启入口是 `restart-research-worker`。重复 `start` 不负责热加载新代码。

研究模式的模板准备、数据库迁移及页面用法见 [研究工作台说明](docs/research-workbench-operations.md)。本地不启动业务 `celery-beat` 或云端行情采集；研究 worker 自带的调度仅推进本节点研究队列。研究记录、输入与结果属于发起它的节点；切换节点不会自动搬走已有课题。

### Mac 页面连接云端：页面操作会写正式数据

先完成或停止本地活动任务，再执行 `bash scripts/local-dev.sh stop`。它保留本地数据卷，并恢复 8000/18080 的云端 SSH 隧道。随后刷新页面，重新确认后端节点；`http://127.0.0.1:18080` 是云端页面入口。**同一个 3000 页面，在切换前后可能连接不同数据库。** 不能凭“浏览器在我的 Mac 上”判断写入是本地测试。

`start` 会让出隧道端口给本地后端；`stop` 恢复隧道。启停检查本地 Docker Desktop、已有卷及活动子任务，启动失败有恢复保护。断网时本地可以停止，但恢复云端连接可能失败，要分别确认。Mac 的旧主库 `data/`、`results/` 和旧容器仅作迁移基线，禁止为恢复连接而启动旧完整 Compose 栈。

### 两端并行改代码：在独立 worktree 中完成候选

后端实验、分支切换、批量修改在同步范围外的独立 worktree 中进行，分支默认用 `codex/<主题>`。普通前端开发可在已分工的主工作树中进行。**在主工作树修改后端文件，即使未提交，也可能被云端进程延迟导入。**

worktree 中的候选代码不会自动成为正在运行的本地/云端服务代码。测试要明确挂载该候选源码，并使用临时数据、只读固定输入和独立输出；不要复制生产 `.env`、连生产数据库或挂载权威数据可写。受管训练/Agent/IDE 子容器还要核对挂载：`HOST_PROJECT_PATH` 定位源码，`HOST_RUNTIME_PATH` 定位节点自己的数据；拥有 Docker socket 本身不保证隔离。

需要远端算力时，也先在云端独立 worktree 测试；只有经过核对的正式作业才在权威项目入口运行。云端操作服务统一使用：

```bash
# SSH 登录 lzy-vm 后，在 /root/code/QuantMind 执行
sudo -n bash scripts/dual-node.sh cloud-compose ps
# 任务已包含发布、且相关任务空闲时，按实际修改选择服务，例如：
# sudo -n bash scripts/dual-node.sh cloud-compose restart quantmind
```

## 要写入数据时，先选目的地

| 目的 | 正确入口与写入位置 | 完成后如何使用 |
| --- | --- | --- |
| 调试页面、验证接口、试改数据库 | 确认当前是本地沙盒后，通过本地应用/API 写入 `quantmind-dev_*` 卷或 `.local-dev/project` | 仅影响本地；提交的是代码/迁移，不是整个本地数据库 |
| 独立脚本或 worktree 测试 | 显式指定临时输出目录/沙盒路径；读入固定快照 | 不依赖脚本默认的 `./data`、`./results`，避免误写旧主库或正式目录 |
| 新增/修改正式业务记录 | 通过已确认连接云端的认证页面/API，或现有云端业务作业 | 由云端服务写正式数据库；跨端开发不改变用户/租户权限 |
| 接入或补齐行情、财务等正式数据 | 先在隔离输入上验证采集/转换代码，再通过云端既有采集、导入、发布入口执行 | 原始对象、检查点与缺口留在云端；校验成功才发布可读版本 |
| 修改表结构或批量修复正式数据 | 编写版本化 SQL/迁移或复用既有迁移入口；沙盒验证后，在云端备份并执行有范围、可校验、可恢复的操作 | 使用事务、唯一键/upsert 或稳定请求 ID，重试不重复写；保留执行证据 |
| 共享本地研究成果或申请正式验收 | 保存方案、输入/代码版本、来源节点和产物；后续通过项目入口先归档共享，正式验收另按合同复核、必要时重跑 | 当前入口待实现；归档不等于正式验收，不整库回灌或直接覆盖云端 `results/` |

不要仅因代码在云端就默认允许写正式数据。运行前说清楚目标表/目录、影响范围、已有作业是否在写、失败如何恢复。已有任务授权覆盖的操作按范围执行；删除历史、覆盖正式数据、恢复备份等额外破坏性操作不能从“帮我开发”中推断授权。

本地/云端都可通过各自的研究工作台创建研究；输入与结果落在各自节点，正式行情采集仍只在云端。正式研究记录应包含输入快照或 `release_id`、数据截止时间、代码版本、参数与任务 ID。Qlib 是派生缓存，复用 `QlibDataBuilder.build_all` 的受限构建、完整校验和原子发布，不手工先替换日历。实盘开关保持关闭。

## 数据如何更新，什么时候会落后

- **QuantDB 日常更新**：云端 A 股配置每天北京时间 03:00 采集，错过时间可当日补派；市场同步走现有 worker 的独立队列，失败任务不会无限重投。Mac 原 `com.quantmind.snapshot-pull` 每 3600 秒先发布/拉取限定 QuantDB Parquet，再在沙盒空闲时应用；复用文件哈希、增量传输和既有 PG/Qlib 入口，不依赖完整快照成功，也不停止云端整套服务。手动同一路径为 `python3 scripts/quantdb_refresh.py refresh`。
- **应用与保护**：本地已有行情修改发生冲突则拒绝覆盖；旧 QuantDB 留在 `.local-dev/quantdb-before-*`，只向本地行情表补新增日期，不恢复或覆盖业务库。任务运行或后端未启动时保留下载、延后应用。研究固定输入目录保持原样；查看 `.local-dev/QUANTDB_SYNC.json`、应用真实最新日与代表标的数据，不能用下载成功替代验收。旧版保留，空间不足时先报告，不自动删除本地成果。
- **页面派生结果也要跟随更新**：QuantDB 采集/本地应用后复用市场分析计算入口刷新 JSON 与标签库；同日来源修订也重算，计算失败保留旧版并报错，不把旧版当“最新”。已有 QuantDB 应用成功也要独立补查市场分析结果；验收包括真实市场分析页面的日期、指数/资金流/板块内容，而非仅查行情文件或 Qlib。显式历史日期和固定研究输入保持原版本。
- **更新范围要说清楚**：当前日常采集覆盖股票/指数日线、因子、估值等现有 23 个数据集。分钟线、Tick 仍属按需数据，旧 `4_bond_etf/etf_kline` 也不在这条采集链路；不能把“QuantDB 日线追平”说成全部数据都已更新。融资融券及财报按各自上游可用日验收，不伪造统一日期。
- **完整数据库快照**：仍是独立恢复基线，包含业务数据库等；整项目快照容量不足时可以暂停，但不能连带关闭上述 QuantDB 日常更新。下载区仍为 `~/Library/Application Support/QuantMind/cloud-snapshots`，其中 `quantdb/` 保存限定基础数据版本。
- **忙时不会强行做完整快照**：存在活动任务时退出 75、保留旧版，当前计划等下一次 07:00 再试，没有保证当天一定出新快照的补跑机制。Mac 拉取成功可能只是确认“仍是旧的已校验版本”；检查快照 ID 与日期，不能只看任务已安装或退出码为 0。
- **Tushare**：云端持续采集并按既有节奏发布固定版本，Mac 每 900 秒校验下载到 `~/Library/Application Support/QuantMind/tushare`。下载区更新 `CURRENT.json` 后，正在进行的研究仍应使用原先固定的 `release_id`。镜像成功不代表所有历史、权限、字段或时间点数据已经齐全；读取和安装说明见 [Tushare 镜像说明](docs/tushare-mirror-installation.md)。
- **完整快照的下载与切换输入是两件事**：完整快照下载不自动修改 `.local-dev/SNAPSHOT_ID`、沙盒数据库或研究模板。需要换沙盒基线时先保存本地成果、结束任务并停沙盒，再按恢复流程重建；当前没有一键合并/无损升级两套数据库的入口，不要为了通过 `init` 的检查随手删除旧卷。
- **手动刷新**：只拉已发布完整快照用 `python3 scripts/dual_node_snapshot.py pull`；`bash scripts/dual-node.sh snapshot-refresh` 还会在云端创建完整快照，需要协调停写窗口。Mac 离线/休眠时无法拉取，云端作业继续；恢复后再补拉。定时客户端是独立安装副本，修改客户端代码后须按对应安装说明更新，Git 同步不会自动升级它。

## 交接、合并和发布：按这个顺序完成

1. 在主题记录中约定负责人和文件范围。开始、方案变化、重要阶段、交接及完成各追加一条短记录，使用唯一文件名；不要共同覆盖一个 `CURRENT.md`。记录方案、分支/提交、输入版本、验证和下一步即可，不复制大段日志。
2. 候选验证完成后，只暂存本次文件、提交并 push。另一端接续候选用 fetch 和独立 worktree；**主工作树的 `handoff` 不负责传输未合入的 worktree 分支**。交接时给出确切分支/提交，不能只说“文件已同步”。
3. 由一名集成人将候选合入主分支，保留已有研究与他人的未提交修改；不在共享运行目录切分支、执行批量 checkout 或强制 reset。合并前核对两端分工，不能认为协作记录能自动阻止 Git 冲突。
4. 等 Syncthing 完成，在 Mac 主工作树运行 `bash scripts/dual-node.sh handoff`。若只是另一端 Git 落后且工作文件相同，用 `handoff --align-git mac`（以 Mac 提交为准）或 `handoff --align-git cloud`（以云端为准）。入口只快进元数据、保留工作文件，不替人提交、不推 GitHub；有分叉/暂存修改/内容差异则拒绝。
5. **需要发布时另占共享服务窗口**：同一时刻只有一个任务负责主工作树合并发布和共享服务重启；其他任务继续独立 worktree 工作。提前告知涉及的服务与窗口，确认没有相关训练/研究及不可中断作业；现有在途采集先自然排空，不能为一个修复把所有 worker 一起重启。纯文档更新无需重启。
6. 后端纯 Python 变更按上述 `cloud-compose` 入口重启相关服务，无新增依赖就不重建镜像；本地前端用 Vite 验证，云端前端正式发布复用 `bash scripts/dual-node.sh web-publish`。最后检查相关服务健康和实际读写/产物，再写完成记录：源码同步、Git 对齐、进程加载、数据验收分别说明。

## 开发原则：优先复用，避免膨胀

先找已有实现、文档、脚本和主题，能扩展就不另建同类工具。标准库和已有依赖优先；只做当前需要的最小改动，不建设重复状态表、通用框架或第二套同步系统。简化不能省略隔离、输入校验、失败恢复与必要验证；记录写增量，详细内容链接已有文档。

## 项目概述

QuantMind 是一个量化交易平台，后端为 Python（FastAPI），前端为 Electron/React/TypeScript。开源版（OSS）采用单容器部署，所有后端服务运行在同一个容器中。

## 后端服务（统一入口 `backend/main_oss.py`）

| 服务 | 端口 | 职责 |
|------|------|------|
| api | 8000 | 用户认证、策略管理、社区 |
| engine | 8001 | Qlib 回测、AI 策略生成、模型推理 |
| trade | 8002 | 订单管理、持仓、风控 |
| stream | 8003 | 实时行情、WebSocket 推送 |

## 常用命令

### 后端
```bash
# Mac 沙盒启动（Linux 宿主用上方 cloud-compose 入口）
bash scripts/local-dev.sh start core

# 仅在数据库、Redis、输出和凭据均隔离的测试环境运行单个服务
SERVICE_MODE=api python backend/main_oss.py

# 测试（在项目根目录执行）
python backend/run_tests.py unit        # 单元测试
python backend/run_tests.py integration # 集成测试
python backend/run_tests.py all         # 全部测试
python backend/run_tests.py trade-long-short  # QMT MVP 链路测试

# 代码检查与格式化
ruff check backend/
ruff format backend/
```

### 前端（Electron 应用，位于 `electron/`）
```bash
npm install              # 安装依赖
npm run dev              # 开发模式（Electron 桌面端）
npm run dev:web          # 开发模式（Web 浏览器）
npm run typecheck        # 类型检查
npm run dashboard:build  # 生产环境构建
```

## 架构要点

- **特征工程**：48 维特征由外部服务写入 `market_data_daily` 表
- **交易服务**：外部报单前强制「本地优先」落库持久化
- **Redis 库分配**：0=通用，1=认证，2=交易，3=行情，4=回测，5=缓存
- **共享模块**：`backend/shared/` 存放跨服务代码（DB 管理器、Redis 客户端、配置、日志）
- **策略存储**：`backend/shared/strategy_storage.py` 是所有策略增删改查的唯一入口

## 股票代码标准化（重要）

- **强制格式**：前缀式（如 `SH600036`）。**所有内部 Redis 键、数据库字段、API 参数必须使用此格式。**
- **禁止格式**：后缀式（如 `600036.SH`）。**任何新代码和配置中不得使用此格式。**
- **标准化工具**：
  - 后端：`backend/shared/stock_utils.py` → `StockCodeUtil.to_prefix(code)`
  - 前端：`electron/src/utils/portfolioUtils.ts` → `normalizeStockCode(code)`
- **Redis 键格式**：
  - 快照：`market:snapshot:sh600036`（快照键用小写前缀）
  - 序列：`market:series:SH600036`（序列用标准前缀式）
- **市场自动识别**：
  - `SH`：6xxxxx、9xxxxx
  - `SZ`：0xxxxx、3xxxxx、2xxxxx
  - `BJ`：4xxxxx、8xxxxx

## 环境变量

必需的 `.env` 键（默认值见 `docker-compose.yml`）：
- `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`
- `REDIS_HOST`、`REDIS_PORT`
- `SECRET_KEY`、`JWT_SECRET_KEY`
- `STORAGE_MODE=local`（OSS 版必需）

## 代码风格

- Python：行宽 88，使用 ruff 做检查与格式化
- TypeScript：提交前端改动前必须运行 `npm run typecheck`

## 开发与部署工作流

### 1. 前端开发（NPM 模式）
- **本地开发模式**：前端统一使用本地 `npm run dev`（Electron 桌面端 / Vite Web 模式，自带 HMR 热重载）。
- **前端修改规则**：**修改前端（electron/src）代码后，不需要每次重新构建或重启服务器上的 `web` 容器**，本地可实时热重载预览调试。提交前运行 `npm run typecheck` 保证类型安全即可。

### 2. 后端同步与部署

统一按上文“交接、合并和发布”执行：候选验证、明确路径提交、源码/Git 对齐、协调服务窗口、选择相关服务发布、实际验收。不要另用一组默认命令批量重启所有 worker；文档变更无需重启。

### 3. 镜像构建规则（是否需重新打包）
- **后端代码走 bind mount**（`./backend:/app/backend` 等挂载进容器），镜像只含 Python 依赖环境。
- **纯代码改动（未新增 pip 依赖、未改 Dockerfile/构建参数）**：发布时先核对源码与 Git，再通过对应环境入口重启；无需重新打包镜像，不在同步工作树盲目 `git pull`。
- **需要重build 的场景**：①新增了 `requirements.txt` 未收录的 Python 依赖；②升级 torch/qlib/duckdb 等底层库；③全新服务器首次部署无现成镜像。
- **云端重build 方式**：在已授权的发布任务中执行 `sudo -n bash scripts/dual-node.sh cloud-compose build quantmind`，然后用同一入口 `up -d --no-deps quantmind`。
- 跨 Mac/Linux 构建时核对镜像架构与依赖；不能把 Mac 的虚拟环境、node_modules 或数据库物理卷当作 Linux 可移植产物。

### 4. QwenPaw（QuantBot）技能更新
- **统一入口**：`bash scripts/quantbot_init.sh`（在服务器上、项目根目录执行）。一次完成：本地 `skills/` 全部技能经 API 导入技能池 → 广播到 `default` 工作区并启用 → 写入量化人格（SOUL/PROFILE/AGENTS）。
- **禁止手工拷贝技能目录**（如直接 `rsync`/`docker cp` 到 `skill_pool/` 或 `workspaces/default/skills/`）：磁盘文件与 `skill.json` 清单会漂移，导致后续上传冲突（31 个技能全量 conflict）且无法经 API 删除，只能逐个手工清理。
- 只更新技能：`--skills-only`；只写人格：`--persona-only`。
- 技能更新后需 `docker restart qwenpaw` 使其生效；验证用 `docker exec qwenpaw qwenpaw skills list`（技能数与启用数应一致）和 `docker exec qwenpaw qwenpaw skills test <name>`。
- QwenPaw 镜像自带 reportlab 与中文字体（`docker/Dockerfile.qwenpaw`），报告 PDF 转换优先在 qwenpaw 容器内直接执行 `python3 /app/backend/scripts/md_to_pdf_report.py`（backend 为 bind mount，共享 `/data` 卷），无需 `docker exec quantmind`。

## 关键文件

- `backend/main_oss.py` - 全部后端服务的统一入口
- `backend/run_tests.py` - 多模式测试运行器
- `backend/shared/` - 跨服务共享模块
- `docker-compose.yml` - 本地部署配置
- `scripts/quantbot_init.sh` - QwenPaw 技能/人格一键初始化（技能更新唯一入口）
- `docker/Dockerfile.qwenpaw` - QwenPaw 扩展镜像（reportlab + docker CLI）
