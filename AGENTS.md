# QuantMind 开发指南（AGENTS.md）

本文件为 AI 编码助手（Claude Code / Codex / QwenPaw 等）在此仓库中工作时提供指导。

## 当前双端开发约束（优先于下方通用 OSS 命令）

- 权威数据节点为 `lzy-vm:/root/code/QuantMind`，真实目录在 SSD `/root/data/disk/quantmind/project`。先读 `docs/dual-node-deployment.md` 与 `docs/development-data-contract.md`。
- Mac 的旧 `data/`、`results/`、数据库卷仅保留作迁移基线，禁止重启原完整 Compose 栈、调度器或回灌这些数据。默认联网前端连接 SSH 隧道 `127.0.0.1:8000/18080`；需要 Mac 本地算力时只用 `scripts/local-dev.sh` 启动 `.local-dev` 隔离沙盒，断网不得把它切成主库。
- 源码工作树和共享密钥由 Syncthing 双向同步；`.git` 独立。不要两端同时编辑同一文件、在共享运行目录切分支或批量 checkout。并行后端开发使用独立 worktree；测试不挂载权威数据可写，不携带生产凭据，不接生产网络。
- 开发前/发布前按下方宿主环境选择预检。Mac 离线可使用已初始化的固定快照沙盒或独立测试；联网后再做双端预检。任何 `.sync-conflict-*`、代码哈希/Git HEAD 不一致都必须先处理，不能自动覆盖。
- 后端发布只走 `scripts/dual-node.sh cloud-compose`；禁止裸 Compose 遗漏云端覆盖层。先确认没有训练/研究任务，核对同步与改动，明确提交路径（不要 `git add .`），再重启相关服务并验收。
- 正式数据写入只在云端由现有业务服务/作业完成；本地沙盒写入不参与 Syncthing，也不自动回灌。修改 schema 走版本化 SQL/迁移；重复请求必须幂等。离线研究结果不直接同步到权威 `results/`，应在云端以固定输入、代码版本、参数重跑验收。

## 开发原则：优先复用，避免膨胀

- 先找现有实现、文档和入口，能扩展就不另建同类工具；标准库和已有依赖优先，不为方便加一层抽象或依赖。
- 用能满足当前需求的最小改动，不建设尚未需要的通用框架、重复状态表或自动化系统。方案引用已有文档，进展只记增量；不复制大段日志、代码或研究结果。
- 简化不能省略数据隔离、输入校验、失败恢复及必要验证；验证与改动风险相称。

## 主题协作与换端接续

- 开始开发时先读取本机**共享主工作树**的 `coordination/README.md` 和对应主题记录，再确认方案、文件分工、未完成项；已有主题优先复用。
- 在任意 worktree 用 `git rev-parse --path-format=absolute --git-common-dir` 定位共同 `.git`，其父目录是本机主工作树。协作记录统一读写该主工作树的 `coordination/<主题>/`，不要写在独立 worktree 的旧副本里；旧 worktree 接续时还应重读共享主工作树的本文件。
- 开始、方案变化、重要阶段完成、阻塞、交接和结束时，各追加一条短记录，写清任务标识、节点、分支/提交、文件范围、验证和下一步。每条使用唯一文件名，引用已有方案和前序记录；不共同覆盖一个进度文件，不为微小步骤制造记录。
- 同主题并行采用独立 worktree/分支和不重叠的文件归属。同文件争用先协调，不能认为记录目录提供了分布式锁。离线不抢占新的共享文件范围；同步后发现重叠或冲突先保留双方内容并解决。
- `coordination/` 随主工作树双向同步；独立 worktree 和 `.git` 目前不双向同步。接续代码使用 Git 提交/分支或明确补丁，源代码与元数据核对复用下方 `handoff` 入口，不另建同步工具。

## 先识别环境，再执行开发命令

在当前终端先检查 `uname -s`、`uname -m`、`hostname`、`pwd -P`、`git status --short` 和 `docker context show`。操作系统、执行位置和数据角色要一起判断：Mac 上 Docker 容器也报告 Linux，不能仅凭 Linux 就使用云端命令；Docker context 可能指向别的机器，也不能仅凭本地终端就认定使用本地算力。

| 环境 | 判断依据 | 开发与数据规则 |
|---|---|---|
| Mac 宿主 | `Darwin`；当前主工作树 `/Users/lizeyu/Documents/ChatGPT/投资/QuantMind` | 默认优先本机全栈开发，用 `.local-dev/project` 和 `quantmind-dev_*` 独立卷；正式数据仍在云端 |
| Linux 云端宿主 | SSH `lzy-vm`；项目真实路径与 `deploy/dual-node.env` 一致，SSD UUID 和 `AUTHORITY` 标记核对通过 | 可以编辑与研究；共享路径被正式服务挂载，实验性代码先在独立 worktree 验证，正式写入走云端服务 |
| Docker 容器或其他 Linux/worktree | 容器内 `/app`、`/quantmind`，或不匹配上述宿主身份 | 先确认容器名、`QM_NODE_ROLE`、挂载源和 Docker context；不得推断为正式节点，也不得执行宿主迁移/启停脚本 |

### Mac：优先使用本地资源

以下命令在项目根目录的 Mac 宿主执行：

```bash
bash scripts/local-dev.sh status
# 仅首次且不存在 .local-dev 时初始化；已初始化不重复执行
bash scripts/local-dev.sh init
# 按需选一个：core 为 DB/Redis/后端，full 再含 worker/资讯/QuantBot
bash scripts/local-dev.sh start core
# bash scripts/local-dev.sh start full
# Vite 未运行时启动；不要重复占用 3000
npm run dev:react --workspace=electron -- --host 127.0.0.1
```

`start` 会卸载原先承载 8000/18080 的云端隧道，8000 改为本地 API；`stop` 停本地容器、保留沙盒数据并恢复云端隧道。因此同一个 Vite 3000 页面在切换后可能写入不同数据库：切换前停止交互和任务，切换后刷新页面、重新确认后端角色再写入。重复 `start` 对满足所选模式且健康的沙盒不做改动；切换 core/full 或修复部分启动状态时先检查再 `stop`。启停会验证本地 Docker Desktop endpoint 并串行加锁；首次启动失败会停掉本次启动的服务并恢复此前存在的隧道。停止命令为 `bash scripts/local-dev.sh stop`，断网时其恢复隧道检查可能失败，要分别确认本地容器确已停止和云端连接状态。

沙盒数据固定在 `.local-dev/SNAPSHOT_ID`；离线可使用本地已有数据与依赖，外部 LLM/行情源需要网络。`.env.local`、`config/runtime.env` 仍是共享配置，不要写入机器专属路径/角色；本地角色配置放 `deploy/compose.local-dev.yml`。涉及 Docker 子容器的训练/Agent 作业，要核对其实际挂载也指向沙盒后才启动：训练、AI-IDE 和 RD-Agent 的受管子容器通过 `HOST_RUNTIME_PATH` 映射沙盒数据，`HOST_PROJECT_PATH` 仅定位源码；任意持有 Docker socket 的命令仍须核对挂载。Mac 当前复用的后端镜像是 `linux/amd64`，Apple Silicon 上使用本机算力但存在架构转换开销；依赖、虚拟环境和构建产物按平台分别安装，不双向复制。

### Linux：云端开发与发布

在 `lzy-vm` 宿主项目目录操作服务统一用 `sudo -n bash scripts/dual-node.sh cloud-compose <参数>`；例如 `ps` 查看状态。该入口检查 SSD，不能用裸 Compose 替代。Linux 不运行 Mac 的 `local-dev.sh`、`launchctl` 或 APFS `cp -c` 命令。

Linux 预检：`sudo -n python3 scripts/dual_node_check.py --node cloud`，它只检查云端。Mac 联网时执行 `python3 scripts/dual_node_check.py` 才同时核对两端 Git、工作树内容、快照与服务；不要在 Linux 直接运行无参数版本，它默认从 Mac 发起。Linux 独立 worktree 的测试使用明确隔离的数据与输出目录；正式部署始终回到已验证的权威项目入口。

### 交接与提交

换端开发时先结束当前任务，等待 Syncthing 完成，在 Mac 执行 `bash scripts/dual-node.sh handoff` 核对冲突、工作树和 Git 分支/HEAD。只有 HEAD 落后且源码哈希一致时，显式指定 `handoff --align-git mac` 或 `handoff --align-git cloud`，以指定端为提交来源快进另一端的 Git 元数据；分支不一致、非快进、有暂存改动或 Git 操作进行中均拒绝。它保留工作文件，不做 checkout，不自动提交研究改动，也不推送 GitHub。源码和共享配置双向同步，`.git` 独立传递；活跃数据库、`.local-dev`、模型输出与运行数据不双向合并。即使平时只有一端开发，也保留这些检查。

仅暂存本次明确文件，保留已有未提交工作。修改文档或提交代码不等于授权重启服务；只有任务包含发布时才构建/重启，并选择没有活动研究任务的窗口。源码同步可能影响云端延迟导入的 Python 文件，高风险改动先在共享树之外测试。`AGENTS.md` 是环境规则主入口，`CLAUDE.md` 引用本节，详细数据规则统一维护在 `docs/development-data-contract.md`。

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
- **后端修改规则**：先在当前开发环境验证；任务包含发布时才同步部署和重启云端对应服务。文档变更无需重启。

```bash
# 1. 明确列出本次变更路径，勿混入他人工作/密钥/产物
git add <本次修改的文件>
git commit -m "descriptive message"
git push origin HEAD

# 2. 同步并重启后端服务（服务名见 docker compose config --services）
# 以下仅用于任务已包含云端发布时；当前目标记录在 deploy/dual-node.env。
# 当前 lzy-vm 拓扑：Syncthing 同步工作树后核对 HEAD/内容，不在共享目录盲目 git pull。
python3 scripts/dual_node_check.py
ssh lzy-vm 'sudo -n bash -c "cd /root/code/QuantMind && bash scripts/dual-node.sh cloud-compose restart quantmind celery-worker celery-beat"'
```

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
