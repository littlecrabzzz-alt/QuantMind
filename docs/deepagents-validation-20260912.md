# Deep Agents / GLM 框架基础验证

日期：2026-09-12；执行节点：Mac 隔离环境。对应 [Plan 第 11.3 节](continuous-research-and-strategy-plan.md#113-开发前的短验证关卡)。

## 结论与边界

**Deep Agents + LangGraph 可在所测版本上接入真实 GLM，完成工具循环、代码/文件、持久会话、人工确认和中断接续。** 保留该选型。框架基础验证通过；第 11.3 节中的量化成果登记及端到端产品验收仍未完成，不能把本次测试叫研究工作台上线。

使用官方 `create_deep_agent`、`TodoListMiddleware`、`AsyncPostgresSaver`、流式事件及 `Command(resume=...)`。仅为现有 Docker 做了标准 BaseSandbox 协议的临时适配；没有自研 Agent 循环、消息模型、文件工具或检查点引擎。主服务、原研究 worker、前端与正式数据均未修改或重启。

## 固定环境

| 项目 | 实测版本/配置 |
| --- | --- |
| Python | uv 独立 CPython 3.12.12，未修改系统/主服务依赖 |
| Deep Agents | 0.7.13 |
| LangGraph | 1.2.11 |
| langchain-openai / langchain-core | 1.6.2 / 1.6.3 |
| PostgreSQL checkpointer / psycopg | 3.1.2 / 3.3.5 |
| 模型 | `glm-5.3-flash`、`glm-5.3`，现有私有 GLM coding endpoint |
| 模型适配 | 显式 `use_responses_api=False`，low reasoning、12000 输出上限、streaming/usage、90 秒请求超时、最多 2 次 SDK 重试 |
| 临时状态库 | 独立 `agent_validation` 数据库，独立 PostgreSQL 容器，随机 localhost 端口；无业务库连接 |
| 执行沙盒 | 固定本地 Python 镜像 ID，128 MiB、0.5 CPU、32 pids、无网络、只读根文件系统、非 root 用户，仅挂载课题目录 |
| 子 Agent | 通过官方 HarnessProfile 关闭默认 general-purpose 子 Agent，实际工具清单确认无 task |

依赖完整冻结在 [requirements-deepagents-validation.lock](../scripts/requirements-deepagents-validation.lock)。具体 Python 镜像 ID 在证据 `versions.json`，复跑时应使用相同可取得镜像并核对版本。框架 profile API 属于 beta，锁版本后再升级验证。

## 实测结果

| 场景 | 结果与证据 |
| --- | --- |
| Flash 工具闭环 | 实际调用仓库 `research_expression.validate`，拒绝未来 lag 后修正为合法表达式；读取合成输入，写 Python，容器执行，读取 JSON，数值断言通过 |
| GLM-5.3 工具闭环 | 同样完成校验、纠错、代码/文件/计算；另实际调用任务清单工具。两次均得到 count=3、sum=14、mean=14/3，并保留随机 marker |
| 新进程恢复会话 | 独立 Python 进程从 PG 加载原 Flash 会话；不重新读取文件即回忆原随机 marker 和总和，接收新方向消息 |
| 人工确认后恢复 | native interrupt 持久化待确认的 validate_factor；第一进程退出时尚未调用该工具；新进程用 Command 审批，执行工具后完成 |
| 执行中打断与改方向 | Agent 实际启动写标记后睡眠的容器；检测已开始后取消框架任务，适配器删除准确所属容器。测试确认容器不存在、迟到文件不存在；向原会话补正常 ToolMessage 中断结果，再发送新指令，生成 steered.txt，未重启旧任务 |
| 模型输出中打断 | 已收到真实流式文字后取消正在运行的框架任务，随后同会话接受“不要继续，只确认停止”；供应商端是否立即停止计费未知 |
| 后台工作时普通问答 | 原会话提交一个异步测试作业后，再收到普通问题；Agent 调用实际状态工具并回答，回答结束时原容器仍在运行，作业只创建一个 |
| 任务清单 | 显式加入官方 TodoListMiddleware 后，GLM 和 Flash 均实际调用 write_todos，清单进入框架状态 |
| 沙盒隔离 | 非 root UID 65534；容器看不到宿主测试文件、Docker socket、API/DB 凭据，网络连接被阻止 |

这些是框架/工具验证，用合成数字和短测试作业，没有使用行情数据做新策略搜索，也没有创建平台因子/策略/回测记录。既有表达式校验器的接入不等于量化整链路已接入。

本次取消实测：代码容器取消并确认消失约 0.081 秒；模型流客户端取消约 0.002 秒。这是单次本机小作业测量，不是生产控制延迟保证，也不是停止真实训练/远端计费的证明。

## 发现并处理的问题

1. 首次初始化受本机 SOCKS 代理影响，缺少 socksio，尚未进入 API 调用。只在隔离环境补该依赖，已列入锁文件。
2. 当前所选框架版本对 GLM 默认未暴露 write_todos；第一轮后台问答成功，但“必须有原生任务清单”的断言失败。通过官方 TodoListMiddleware 补配置后，在新会话重测通过；未自写计划工具。初次失败证据保留在 background 目录。
3. 停止 asyncio/模型流本身不负责停止外部 Docker。验证适配器的 finally 负责实际删除所属容器，再核验不存在；旧 pending tool call 要记录中断 ToolMessage 后才按用户新消息继续。
4. 不把断流或一轮消息结束视为业务任务完成。后台实验测试使用独立 job_id，回答消息时可保持外部作业继续。

## 用量与证据

完成并返回用量的模型响应共 28 次，供应商经适配器报告 input=93,863、output=1,732、total=95,595 tokens，包括第一次任务清单断言失败的调用。被主动中断的那次模型请求没有最终用量，记为 unknown，未计入上述已知总量。没有据此估计金额或比较两个模型的普遍速度/质量。

持久证据位置（本机，不进 Git，不回灌云端）：

`/Users/lizeyu/.local/share/quantmind/validation/deepagents-20260912/`

包含 `summary.json`、各场景的工具/文字/状态事件与结果、生成的 Python/JSON 文件、hash 清单、PG checkpoint 逻辑导出。记录可见文字和工具，不记录提示词或私有推理字段；用实际 API key 对全部证据和 PG 导出做了泄漏扫描，结果为未检出。PG 导出权限 0600。

临时 PostgreSQL 和所有带 `quantmind.purpose=deepagents-validation` 标签的代码容器均已移除。独立依赖环境与原始证据仍在 `/private/tmp/qm-deepagents-spike-20260912`，可供调试；持久副本不依赖临时目录存活。

## 可复跑入口

[验证脚本](../scripts/validate_deepagents.py) 是带实际断言的隔离验收工具，不作为生产研究 runner。单场景绝对超时 600 秒，普通代码命令最多 60 秒，输入仅为脚本生成的合成数据。使用独立 worktree 和临时数据库，不使用正式运行配置。

```bash
uv venv /tmp/qm-agent-check-venv --python 3.12
uv pip sync --python /tmp/qm-agent-check-venv/bin/python scripts/requirements-deepagents-validation.lock
docker run --rm -d --name qm-agent-check-db \
  --memory 256m --cpus 0.5 -p 127.0.0.1::5432 \
  -e POSTGRES_PASSWORD=spike-local-only -e POSTGRES_DB=agent_validation postgres:15-alpine
docker port qm-agent-check-db 5432
```

取得该临时端口后，使用下面参数模式。凭据文件沿用本节点私有配置，不提交、不传给沙盒。合成文件输出选择本次专属临时目录。

```bash
/tmp/qm-agent-check-venv/bin/python scripts/validate_deepagents.py \
  --credentials /path/to/private/glm-research-api.json \
  --database postgresql://postgres:spike-local-only@127.0.0.1:PORT/agent_validation \
  --output /tmp/qm-agent-check-results/flash \
  --thread unique-flash-session --phase smoke --model glm-5.3-flash
```

smoke → resume 必须分进程并使用同一 thread/output；approval → approve_restart 同理。interrupt、model_interrupt、background_message 各用新的 thread/output。GLM-5.3 smoke 另用独立 thread/output。跑完导出所需证据，再停止**本次命名**的测试数据库容器；不要用批量清理所有容器的命令。

## 尚未验证，下一阶段必须补齐

- 产品 API/页面的消息回执、实时事件补读、停止按钮和权限隔离。
- 实际平台因子/策略/回测对象登记与双向跳转，以及真实重型作业取消。
- 无预设候选的新方法研究、资料检索和数据准备。
- 硬杀进程/宿主中断期间的外部作业重接、提交回执丢失、跨节点恢复。
- 数小时且 ≤8h 的无人值守、连续 429 退避、截止与累计预算。

因此保留设计选型，下一步进入真实平台工具接入，不再仅扩写报告/计划界面。正式依赖安装、数据库迁移和发布仍须独立验证及协调服务窗口。
