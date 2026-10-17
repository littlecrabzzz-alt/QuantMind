# 研究工作台运行说明

用途：在本地 Mac 操作现有研究 Agent、准备固定输入，并在停止或恢复异常时找到实际状态。这里描述源码接口，不保证服务当前在线；主业务使用 Library 受管快照，Main 开发源码下的独立研究沙盒另有数据与启动边界。

## 使用与能力边界

入口 `/#/alpha-research`。填写研究问题、对象与限制，点击“建立课题并讨论”只建立会话，不启动计算。查看右侧“计划与决定 / 过程 / 文件 / 成果”，核对数据、方法、工具范围和缺项后，才审阅并批准当前计划版本。缺数据或执行器时停在准备阶段，不能把任意课题替换为八因子模板。

- 批准窗口默认 2 小时，最多 8 小时；作业预算默认 4 个，API 可选 1–20 个。该预算不是策略候选数。
- 普通消息在当前模型回合后处理，后台代码作业可继续。立即改变方向用“打断并发送”；“打断执行”撤销旧批准并停止所属计算。显示“正在确认停止”时仍须等待作业核验，不能当作已经停止。
- 打断后可继续讨论；再次执行要重新审阅并批准。关闭浏览器不停止服务端任务，Mac 休眠、关机或 Docker 退出不保证本地计算继续。
- 材料上传单文件最多 2 MB；上传后路径进入消息框，发送后才交给 Agent。文件页可预览或下载产物；成果页链接到真实因子候选、AI-IDE 策略草稿和冻结模板回测。未计算指标保持未知，候选/草稿不等于验证通过。
- 当前工具包括隔离 Python、后台代码作业、因子候选登记、策略草稿保存、固定模板训练及 CnExchange 回测。没有自动联网检索、任意策略正式执行器、独立留出准入或模拟/实盘工具；主业务与沙盒的课题、项目数据保持各自隔离。

研究区间用途与最近半年保留规则见[冻结研究合同](frozen-research-workflow.md)。执行与资金口径见[账务合同](execution-accounting.md)。沙盒文件隔离不等于最终测试数据已被强制访问控制隔离。

## 独立本地沙盒准备与启动

主业务由 [本地运行入口](部署指南.md)中的 `scripts/local-primary.sh` 管理，不自动启动研究 worker 或 Agent。以下命令只操作 Main 下已初始化的独立研究沙盒，不是给 Library 主业务启用研究的入口。须先按维护安排停止主业务、确认任务空闲，再启动沙盒 core；两者不能同时占用 8000。已有研究设置不要覆盖。

前置条件：已初始化 `.local-dev`；在 `.local-dev/project/results/<快照名>` 有完整冻结输入，且清单指定的镜像已存在。准备脚本从该位置复制输入，而不是现场提取正式数据库。创建快照的方法见[冻结研究入口](frozen-research-workflow.md)。

```bash
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local --frozen <快照名>
# 已有数据库启动后，首次迁移前按运行规范备份研究表：
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local --frozen <快照名> --apply-migration
bash scripts/local-dev.sh start-agent
```

`prepare_research_workbench.py` 当前参数为 `--project-root`、`--node`、`--frozen`、`--apply-migration`，没有 `--data-root`。它核验镜像/清单，在本地运行根写 `data/research/settings.json`，并拒绝同名不同内容的输入及不同设置；不要绕过拒绝去覆盖活跃课题。迁移新增 v1/v2 研究表；Agent 自身启动幂等创建原生检查点表。

模型配置是权限 `0600` 的私有 JSON，含 `api_key`、HTTPS `base_url` 和 `requested_models`（也支持 `models`）。本地 Compose 使用 `~/.config/quantmind/glm-research-api.json`，只读挂载；密钥不放进 Git、提示词、页面或课题目录。技术连通不证明套餐允许自建服务直连，供应商集成资格和计费须按当前条款核对，不伪装客户端身份。接口未返回金额时保持未知。

```bash
# 修改镜像内 Agent 代码后重新构建并启动：
bash scripts/local-dev.sh start-agent
# 只需重启已有镜像（先确认无活动任务）：
bash scripts/local-dev.sh restart-agent
# 仅主网关 Python 改动，确认相关任务空闲后：
bash scripts/local-dev.sh restart-backend
```

Agent 使用独立镜像与 `scripts/requirements-research-agent.txt`；不要把其依赖装进主业务服务环境。`restart-agent` 本身不重建镜像。沙盒准备脚本的 `--node local` 只定位 `.local-dev/project/`，不准备或迁移主业务数据。

## API 与持久化定位

公开入口前缀 `/api/v1/research-agent`，经已认证网关转发到独立 Agent 服务；请求绑定用户、租户与节点。以下路径相对该前缀：

| 方法 / 路径 | 用途 |
| --- | --- |
| GET `/capabilities` | 当前节点、工具、固定输入与最长窗口 |
| GET/POST `/cases` | 列表 / 建立课题，不批准计算 |
| GET `/cases/{id}?after=<事件序号>` | 状态、文件/成果及增量事件 |
| POST `/cases/{id}/messages` | `key`、`content`、可选 `interrupt` |
| POST `/cases/{id}/approve` | `key`、当前 `version`、`reviewed=true`、`hours`、`max_jobs` |
| POST `/cases/{id}/stop` | 撤销批准并请求停止；核验最终作业状态 |
| GET `/cases/{id}/file?path=...` | 工作区普通文件，单次最多 20 MB |
| POST `/cases/{id}/files` | 文件名及 base64 小材料 |

重复批准同一 key/内容复用原结果，不延长截止；旧版本或准备缺项拒绝执行。内部 `/api/v1/research-agent-tools` 供受信任服务桥接，不是绕过认证的用户入口。

| 定位 | 文件或目录 |
| --- | --- |
| UI / 请求 | `electron/src/features/alpha-research/` 下 `AgentWorkspace.tsx`、`researchAgent.ts` |
| 网关 / 平台登记 | `backend/services/engine/routers/research_agent.py` |
| 会话、工具、停止与恢复 | `backend/services/research_agent/{app,runtime,store,sandbox,settings}.py` |
| 工作区 | 节点数据根 `data/research/agent/<课题ID>/workspace` |
| 固定回测原件 | 节点数据根 `data/research/cases/<课题ID>/experiments/<作业ID>` |
| 状态 | PostgreSQL `research_drafts`，`engine=deepagents`；框架检查点另表 |

节点 PG advisory lock 防止同节点多 Agent 进程。代码容器无网络、只读冻结输入，不持有模型密钥、数据库凭据或 Docker socket；每课题一个后台作业，尚无节点级统一重计算队列和磁盘配额。

## 故障处理与旧固定实验

1. 能力不可用：先确认当前本地实例、`settings.json` 的宿主路径、输入清单哈希、固定镜像、私有模型配置及数据库连接；不要用主业务或其他沙盒的输入冒充恢复。
2. 停止未确认：检查该课题记录的实际容器和作业状态，保留日志；不能仅凭 SSE 断开或模型回答结束判定停止。
3. 服务重启：已有后台作业按原名观察；模型响应不明时停止并等待决定，不自动重放可能产生副作用的工具。原生 pending tool call 标为中断后，先核对文件、作业及已登记成果再接续。
4. 429/5xx 按有上限退避处理，批准到期即停止；未知用量不填零。没有数小时可靠性、整机休眠/断电、磁盘故障或所有崩溃点均可恢复的承诺。

旧记录仍可从页面下方固定实验入口查看；它使用 `/api/v1/research-runs`、`/drafts` 计划确认、`research_cases/research_windows` 与独立 `research-worker`。只有需要运行该入口时才使用 `bash scripts/local-dev.sh start research`。旧直接创建窗口和 `continue-window` 接口返回 409，必须审阅计划后执行/继续；`completed` 仅表示受限工作流完成，不等于独立验证。它的候选预算、每节点串行调度与 Agent 的作业预算不是同一合同。

改动后的检查入口：`scripts/test_research_agent.py`、`scripts/test_research_agent_gateway.py`、Electron typecheck；旧固定流程另有 `test_research_workbench.py`、`test_research_drafts.py`、`test_research_persistence.py`。数据库/Docker 检查必须使用专门测试库和临时产物目录，不借验证恢复旧课题或调用真实模型。
