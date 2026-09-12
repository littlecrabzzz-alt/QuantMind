# 研究工作台运行说明

2026-09-12 起主入口使用 **Deep Agents / LangGraph 研究 Agent**；完整目标与缺口统一在[持续研究 Plan 第 17 节](continuous-research-and-strategy-plan.md#17-2026-09-12-agent-产品实现与下一步)。后文“旧版固定实验”说明保留用于历史课题，不代表新 Agent 的能力边界。

## Agent 入口与操作

打开 `/#/alpha-research`，选择“策略链路”或“新因子与方法”起点，编辑问题、对象及限制，点击“建立课题并讨论”。只建立会话，不会执行计算。Agent 会检查现有输入，讨论或提交计划；不是每个问题都会立即生成可执行计划。

右侧分为“计划与决定 / 过程 / 文件 / 成果”。确认当前计划和允许操作，勾选后才运行；每次窗口至多 8 小时。缺少实际数据或工具时先讨论解决缺口，不能用已有模板强行代替课题。

普通消息会在当前模型回合结束后处理，后台代码作业可继续运行。需要立即改变方向用“打断并发送”；“打断执行”停止模型响应和本课题实际计算。页面先显示“正在确认停止”，仅在作业状态核验后显示停止。打断撤销旧窗口，继续执行需要重新查看并确认计划；讨论不需要再次批准。

文件页能查看代码、文本/JSON、常用图片和下载文件；材料按钮上传小文件后把路径放入消息框，用户发送后才交给 Agent 讨论。成果页打开真实因子、AI-IDE 策略草稿、平台回测详情，且可以返回来源课题。未计算指标显示“未计算”，候选不会显示为已验证。

## Agent 代码与持久化

| 层 | 入口 | 职责 |
| --- | --- | --- |
| UI | `AgentWorkspace.tsx`、`researchAgent.ts` | 课题、审批、持续消息、动作、文件与成果 |
| 认证入口 | `api/routers/engine_proxy.py` → `engine/routers/research_agent.py` | 必须是已认证账户；内部签名身份转发、用户/租户/节点归属检查 |
| Agent 服务 | `services/research_agent/app.py`、`runtime.py` | 原生 Agent、工具、检查点、消息接续、停止、429/5xx 退避 |
| 状态 | `services/research_agent/store.py` | 复用 `research_drafts`，`engine=deepagents`；原生 checkpoint 表由框架维护 |
| 代码作业 | `services/research_agent/sandbox.py` | 标准 BaseSandbox 适配，Docker 实际进程、绝对截止、工作区文件隔离 |
| 平台工具 | `engine/routers/research_agent.py` | 现有因子/策略持久化与固定训练回测、独立账务复算 |

工作区：节点数据目录 `data/research/agent/<课题ID>/workspace`。固定回测原件沿用 `data/research/cases/<课题ID>/experiments/<作业ID>`。引用和哈希入库；本地验收数据不回灌云端。模型密钥只读挂载，工具代码容器不持有密钥、Docker socket 或网络。内部 Agent 服务不向宿主发布端口。

主服务使用原有 Python 环境，Agent 单独镜像使用 `scripts/requirements-research-agent.txt` 及冻结框架依赖；不能把这些依赖直接 pip 安装进旧主服务。一个节点的 PG advisory lock 只允许一个 Agent 进程。上限 4 个模型回合、每课题一个后台作业；不同课题的慢核验独立推进，短期还没有统一资源排队与磁盘配额。

## Agent 启动与恢复

先按后文“准备与启动”建立节点专属 `data/research/settings.json`、冻结输入及私有模型配置；已有模板不重新覆盖。单独服务启动时幂等创建业务表/原生检查点表，保留旧研究数据。正式库首次执行前应按现有迁移规范留备份。

```bash
# Mac 主工作树：本地 core 已在线、相关任务空闲
bash scripts/local-dev.sh start-agent
# 修改 Agent 代码后的单独重启
bash scripts/local-dev.sh restart-agent
# 主网关纯 Python 改动，确认任务空闲后加载
bash scripts/local-dev.sh restart-backend

# 云端按独占发布窗口操作；不会启动业务 Beat 或旧研究队列
sudo -n bash scripts/dual-node.sh cloud-compose build research-agent
sudo -n bash scripts/dual-node.sh cloud-compose up -d --no-deps research-agent
sudo -n bash scripts/dual-node.sh cloud-compose restart quantmind
```

`start-agent` 使用独立 Docker 镜像；Mac 的 `stop` 将包含 Agent 服务，保留数据卷。关闭浏览器不会停止 Agent。Mac 睡眠或 Docker 退出不能维持本地运行；云端启动仍须独立验证节点和模型连接。页面通过能力接口确认当前节点，不凭浏览器所在电脑判断数据目的地。

服务重启后：等待中的后台作业按原名观察；响应不明的模型回合停止并等待用户决定，不自动重放可能产生副作用的工具。原生检查点中的未返回工具调用被标为中断，接续先核对现有文件、作业及成果。429/5xx 使用有上限退避，超过批准窗口停止；未确认用量保持未知。

短验收证据与尚未验证的故障场景见[产品验收记录](research-agent-product-validation-20260912.md)。当前实现不包含自动联网、任意策略正式执行器、自动模拟交易或数小时可靠性承诺。

## 旧版固定实验：历史实现索引

以下为 2026-09-09 旧版实现，入口折叠在新工作台下方。不要以此表代替上方 Agent 状态。

| 职责 | 代码入口 | 实际行为 |
| --- | --- | --- |
| 研究页面 | [ResearchWorkbench.tsx](../electron/src/features/alpha-research/pages-v2/ResearchWorkbench.tsx) | 讨论与计划入口、执行记录/详情/净值、控制与下载；显式打开记录后加载并滚动/聚焦，后台轮询不抢位置 |
| 讨论与计划页面 | [ResearchDiscussion.tsx](../electron/src/features/alpha-research/pages-v2/ResearchDiscussion.tsx) | 原始问题/对象/材料、聊天、准备检查、历史计划版本、确认执行与继续 |
| 草稿与计划 | [drafts.py](../backend/services/engine/research/drafts.py)、[planning.py](../backend/services/engine/research/planning.py)、[v2 SQL](../scripts/research_workbench_v2.sql) | 持久化消息/计划/模型任务、租约、版本冲突和资源准入 |
| 计划 API | [research_drafts.py](../backend/services/engine/routers/research_drafts.py) | 归属检查、修改先暂停、计划确认与执行在同一事务内写入 |
| 页面请求 | [researchRuns.ts](../electron/src/features/alpha-research/services-v2/researchRuns.ts) | 固定请求节点与认证连接，拒绝切换后迟到结果 |
| 认证 API | [research_runs.py](../backend/services/engine/routers/research_runs.py) | 合同校验、归属、因子引用、曲线/下载完整性核验 |
| 持久化 | [store.py](../backend/services/engine/research/store.py)、[迁移 SQL](../scripts/research_workbench_v1.sql) | 课题/窗口、幂等与排他租约、最新窗口继续及累计检查点 |
| 专用调度 | [tasks.py](../backend/services/engine/research/tasks.py) | 独立 research 队列，执行 Beat 每 5 秒、讨论每 10 秒触发，任务软/硬期限 220/240 秒；不是实验总时长 |
| 阶段协调 | [coordinator.py](../backend/services/engine/research/coordinator.py) | baseline → propose → select → finish；模型提案/修正、候选门槛、压力与核验 |
| 隔离运行 | [runtime.py](../backend/services/engine/research/runtime.py) | 宿主角色、私有凭据、冻结输入/代码、Docker 运行与截止控制 |
| 因子与计算 | [research_expression.py](../scripts/research_expression.py)、[frozen_research_worker.py](../scripts/frozen_research_worker.py) | 受限 AST 因果公式、实际因子值、训练/逐日推理与回测 |
| 独立账务 | [verify_agent_research.py](../scripts/verify_agent_research.py) | 从 CSV 独立复算资金、资产、费用、收益与回撤 |
| 准备及部署 | [prepare_research_workbench.py](../scripts/prepare_research_workbench.py)、[本地入口](../scripts/local-dev.sh)、[双端入口](../scripts/dual-node.sh) | 模板复制、迁移与角色检查；复用现有部署入口 |

当前持久化窗口状态为 queued、running、pause_requested、paused、cancel_requested、cancelled、expired、completed、blocked、failed。窗口生命周期与结果的 `needs_independent_validation` 不同：completed 表示受限工作流完成，不是策略准入。

`case_id` 固定课题合同，`run_id` 标识一次窗口。继续仅允许最新的暂停/到期/取消/失败/阻塞窗口，沿用合同及累计候选数；不能以“继续”修改已冻结候选上限。列表当前返回最近 100 个窗口，因此一个课题的失败与继续记录可能同名，不是重复提交。跨节点/所有历史记录分页及更清晰的课题分组尚待扩展。

## 已有 API 与页面用法

统一前缀 `/api/v1/research-runs`，所有请求要求认证。页面携带 `X-Research-Node`，服务端核对当前节点及租户/用户；节点不符返回 409，无权限的课题不暴露详情。

| 方法 / 相对路径 | 用途 |
| --- | --- |
| GET `/capabilities` | 节点身份、模板、模型和执行服务可用性；不可用显示原因 |
| POST 空路径 | 旧直接启动入口，返回 409，防止旧页面绕过计划确认 |
| GET/POST `/drafts`、GET `/drafts/{id}` | 列出、建立、读取课题；创建和阅读不启动模型或实验 |
| POST `/drafts/{id}/messages` | ask 仅回答；plan/revise 生成新计划并申请暂停旧执行；消息 key 与 revision 防重复/冲突 |
| POST `/drafts/{id}/messages/cancel` | 停止本次讨论，迟到响应不改变课题 |
| POST `/drafts/{id}/execute` | reviewed=true、当前 version、资源检查通过后原子创建一次执行；action=resume 明确开新窗口 |
| GET 空路径、GET `/{run_id}` | 当前账户/节点的窗口列表和详情 |
| POST `/{run_id}/controls/pause`、`/controls/cancel` | 请求暂停后续或取消当前研究 |
| POST `/{run_id}/continue-window` | 旧直接继续入口，返回 409；改用计划确认页 |
| GET `/{run_id}/report/download` | 已完成且哈希匹配的 Markdown 报告 |
| GET `/{run_id}/artifacts/{experiment_id}/{name}` | 清单内已完成/失败实验的已核验产物或日志 |

先核对页面的本地/云端标签，再填写想弄清的问题。对象可以暂不确定；材料只能粘贴已有正文或公式，目前不自动打开网址。

1. **保存课题，进入讨论**仅写草稿。相同账户、节点、原始输入及数据/工具版本重复保存会打开原课题。
2. **发送讨论**请求模型回答，既不执行实验也不修改计划。**整理第一版计划 / 暂停并提出修改**生成完整新版本；缺数据、工具或待决定事项会列出来，不能启动。
3. 计划展示问题、对象、方法、对照、步骤、产物、判断标准、限制和资源检查。当前模板与代码不是任意课题的替代品：例如黄金ETF历史研究应停在对应数据/工具准备，不能悄悄变成A股八因子实验。
4. **审阅并确认执行**打开确认页，核对节点、版本、候选上限与最长时限；勾选审阅后才提交。每版本只启动一次，即使不同请求键并发提交也不会多开。候选上限写入计划，更改要产生新版本。
5. 已执行计划可提问、暂停或取消；计划修改先申请暂停，当前实验允许收尾，旧计划不再获准启动。新版本确认时若旧窗口仍活动会被拒绝。已完成的计划和结果保留，不覆盖；新版本重新跑基线，没有隐含缓存复用。
6. **审阅并继续此计划**仅继续该计划最新的可恢复窗口，沿用原合同及累计尝试；不会把新修改套进旧结果。旧记录可“基于此结果建立课题”，先讨论再决定。记录名称只打开详情。

草稿消息、版本和待处理调用都在 PostgreSQL。每次讨论请求期限 15 分钟；HTTP/429 使用既有适配器退避，格式最多修正 3 次；租约到期后恢复。取消不保证中止供应商已经收到的请求，但迟到内容不会重新写成有效计划；用量无法确认时保留未知。单课题最多 40 轮消息，列表最多最近 100 个课题/窗口；跨节点同步、任意代码开发和自动接数据未实现。

讨论和执行复用一个研究 worker，模型调用期间推进任务可能等待当前调用结束（单调用至多约 180 秒，任务软/硬期限 220/240 秒）。控制意图先写数据库；计算绝对截止由原执行器约束。页面分别显示讨论排队/处理/退避/失败与实际执行状态，不显示编造的进度百分比。

## 准备与启动

先遵守仓库 `AGENTS.md` 的节点检查。研究复用现有 PostgreSQL、Redis 和计算镜像；独立 `research-worker` 只消费研究队列，不复制业务定时任务。输入复制到节点自己的 `data/research/inputs`，结果与合同位于 `data/research/cases`，生命周期保存在 `research_cases/research_windows`。

模型配置为私有 JSON，权限 `0600`，包含 `api_key`、HTTPS `base_url` 和 `requested_models`。Mac 使用 `~/.config/quantmind/glm-research-api.json`，云端使用 SSD 下 `secrets/glm-research-api.json`。Compose 只读挂载该文件。密钥不写入请求合同、Git 或页面。执行器使用供应商真实提供的 Chat Completion 接口；提供商工具使用资格仍须遵守 [GLM 验收记录](glm-research-validation-20260908.md)，技术连通不代表套餐长期接入资格。

准备已有且核验过的冻结模板（不是从正式数据库现场提取）：

```bash
# Mac 主工作树：已初始化 .local-dev 后
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local
bash scripts/local-dev.sh start research
python3 scripts/prepare_research_workbench.py --project-root "$PWD" --node local --apply-migration

# 云端权威宿主：使用实际权威路径
sudo -n python3 scripts/prepare_research_workbench.py --project-root /root/data/disk/quantmind/project --node cloud --apply-migration
sudo -n bash scripts/dual-node.sh cloud-compose up -d --no-deps quantmind research-worker
```

首次迁移前 worker 不会宣称就绪；迁移是可重复的新增表操作。没有新增依赖时无需重建镜像。云端部署须避开活动研究；不重启 Tushare 或其他业务 worker。前端沿用现有 Vite 入口，进入 Alpha Research 的“研究工作台”。能力接口就绪后可直接点击两张卡片发起。

## 生命周期与证据

- 每个窗口最长八小时，默认两小时、最多两个候选。候选累计计数随课题保留；单课题最多十二次实际计算尝试。每节点同时一个重型计算，多个课题公平排队。
- 创建请求使用幂等键；继续同样幂等，只允许从课题最新的暂停/到期/取消/失败窗口续开。已完成课题可另建研究，方法产物可直接创建关联策略课题。
- 暂停完成当前实验后不再启动下一阶段；取消与到期必须观察到所属容器停止。容器内按绝对截止时间执行 TERM/KILL，即使队列服务暂时离线也有计算期限。
- Worker 重启后按数据库租约和固定容器名核对原执行。容器提交意图已存在而容器消失时保留证据、要求检查；不静默重跑。Docker 暂时不可达会重试；模型 429/5xx 按 Retry-After 退避。纯模型提案的超时或崩溃重试保留未知用量，并等待退避/原请求期限后再发起；提案只有经本地合同校验、持久化与幂等容器提交才会启动实验。不能虚记成功或零费用，不能把模型请求重试变成重复实验。
- API 和页面均绑定认证用户及当前节点。切换节点重新查询能力与列表；不同节点不自动导入课题。关闭页面不停止研究；本机休眠/关机不保证本地持续计算。
- 公式由受限 AST 解释，只有历史窗口、横截面 rank 和算术，无任意代码执行。保存真实因子值、分期 IC/Rank IC/覆盖、分层与相关性诊断，逐日仅用当日以前数据重算并对照批量推理。
- 三组组合使用同一股票池、资金、执行与费用规则；逐笔资金/费用/持仓独立复核。候选必须通过固定增量与稳定性门槛才能入选；双倍费用压力实验不得改变模型或信号。报告与下载核验文件哈希。

当前冻结测试区间已经用于开发比较；所有结果标记 `needs_independent_validation`，不称为独立样本外发现或真实收益。Token 可据接口统计，接口没有返回的货币账单保持未知。

## 验证入口

```bash
PYTHONPATH=.:scripts python3 -m unittest scripts/test_research_workbench.py scripts/test_agent_research_tool.py scripts/test_glm_research_runner.py
npm run typecheck --workspace=electron
# 单独创建名为 research_test 的临时 PostgreSQL，应用新增表 SQL 后：
DATABASE_URL=postgresql://.../research_test PYTHONPATH=.:scripts python3 scripts/test_research_persistence.py
DATABASE_URL=postgresql://.../research_test PYTHONPATH=.:scripts python3 scripts/test_research_drafts.py
```

第三项包含真实数据库并发幂等/归属/租约/恢复和真实 Docker 取消，拒绝使用其他数据库名。它不调用模型或正式数据。产品页面与真实模型的双端验收见 [2026-09-09 验收记录](research-workbench-validation-20260909.md)，以上检查不能替代端到端完成证据。
