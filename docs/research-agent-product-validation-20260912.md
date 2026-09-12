# Research Agent 产品接入验收 · 2026-09-12

对应[持续研究 Plan 第 17 节](continuous-research-and-strategy-plan.md#17-2026-09-12-agent-产品实现与下一步)。本次完成有真实工具、文件、持久会话、人工控制和平台成果入口的第一版。测试对象是合成算例和已有冻结模板，**不是新投资策略的有效性结论**。

## 环境与可复查证据

候选分支 `codex/research-agent-product`，隔离 worktree `/private/tmp/quantmind-research-agent-product`。Python 3.11 独立 Agent Docker 镜像，Deep Agents 0.7.13 / LangGraph 1.2.11，真实 `glm-5.3-flash`；不变更主镜像的 Python 包。GLM-5.3 的基础兼容性沿用[前次框架验收](deepagents-validation-20260912.md)，本轮完整产品算例未重复在该模型上跑。

测试节点 `agent-product-isolated`，独立 PostgreSQL 15 容器及工作目录，输入是 Mac 已验证模板 `frozen-controls-20260907-v3` 的只读副本。页面运行于独立 3301 端口，专用网关测试账户。该测试页面没有使用正式登录；认证归属测试与公开网关拒绝未登录测试另外完成，发布后再核对实际入口。

持久证据在 Mac `/Users/lizeyu/.local/share/quantmind/validation/research-agent-product-20260912/`，包括案例状态、代码/结果原件、独立账务复算、PostgreSQL 自包含备份及 SHA256 清单。独立测试数据未回写主沙盒业务记录或云端权威数据。

## 实际执行结果

| 算例 | 实际执行 / 可查结果 |
| --- | --- |
| 合成因子 | 课题 `1ae3c6e4d206486dbd526cf82d51bde2`，Python 对 2/4/8 去均值，均值 14/3，中心化和为 0；保存 factor.py、result.json，并通过现有因子持久化登记候选 |
| 因子成果 | ID `research-db7928bcba280cf81972c75590074dc1`；代码 SHA256 `43e3b6e27d60d7d68e3d1ede45bd3176353f184feb930d0ca0e013314d126c37`。多次重试后数据库仍一条；浏览器打开实际因子详情、返回课题、查看 result.json |
| 策略草稿 | 课题 `359d9bef1a84484cacd7e0d1f7dc5d60`，实际 strategy.py 通过唯一 `StrategyStorageService` 保存；测试库 ID `1`、DRAFT、未验证；SHA256 `b6d5d5d9ad1aca05dadad73c02cfec85c6d7c20aa0d4eb9ca8abb787ec606db1`。链接在 AI-IDE 选中同名策略并有来源返回入口。未运行代码/策略 |
| 固定回测 | 课题 `3a998cb4c727421495818088677f524b`，作业 `98ee07320a80084d9a9cc784`，只有一次实际基线训练回测，2025-04-07 至 2025-06-30；实际对照为 20 日动量、同池等权 |
| 回测成果 | ID `research-135f4da351706b015727a551265f4e06`，状态 completed；实际净值曲线和元数据保存到 `qlib_backtest_runs`，浏览器可打开详情。年化/夏普/胜率/盈亏比未计算，不以 0 替代 |
| 独立账务 | 从保存的 CSV 再次独立复算 model/single_factor/equal_weight，现金误差均 0，资产误差最大 9.32e-9；文件 `independent-reconciliation.json`。这是冻结开发区间账务一致性，不是样本外有效性 |
| 背景运行与问答 | 课题 `da2f00e42b1f4f3a8de378b53694df38`，脚本先写 started.txt，sleep180，再写 finished.txt；实际后台运行时，页面普通消息收到模型回复，作业未被普通消息重启 |
| 实际打断 | 页面点击时间 06:17:07.384Z，服务记录请求 07.430Z，容器退出 08.182Z，确认停止 08.227Z，约 0.8 秒；started.txt 存在、finished.txt 不存在，退出码137。代码当前会把用户终止显示为 cancelled；该早期测试原记录保留 failed+137 |
| 模型中断与接续 | 模型处理期间点击“打断并发送”，旧消息变 interrupted，下一条得到“已收到中断”；没有恢复旧执行许可。证据 `model-interrupt-proof.json` |
| 重启恢复 | Agent 服务重启后，原对话、计划、文件、成果与原生检查点仍可读取，继续讨论并通过 inspect_research/ls/read_file 查回实际产物，没有重跑计算 |

## 接口、回归和页面验证

- 重复批准使用同一请求键不延长截止时间、不增加作业上限；跨用户/租户请求返回404，错节点409，未认证私有入口401；目录越界下载404。`api-boundaries.json`。
- `scripts/test_research_agent.py`：7项通过，包括讨论不能计算、过期许可不能入库、符号链接/父目录/FIFO保护、停止撤权与消息幂等、慢课题不拖住其他课题、完成状态纠正与通知去重、后台运行时可查询而不能改文件。
- `scripts/test_research_agent_gateway.py`：2项通过，未认证或伪造内部身份不能通过公开 Agent 网关；已认证身份沿用既有转发。
- 前端 `npm run typecheck` 通过；Python Ruff F/E9、脚本语法与 `git diff --check` 通过。页面测试实际操作了消息、停止、成果跳转、文件查看和来源返回。
- 测试中暴露并已修复：DockerClient 关闭方式；成果事件字段冲突；后台提交准备期间误判 missing；历史错误通知阻止完成入库；慢/错误课题阻塞其它消息；完成任务占用并发名额；普通回测历史清理不应删除研究记录；公开入口必须显式验证身份。

## 发布状态与限制

发布状态在本次集成后补充；独立测试 3301 页面不等于用户 3000/云端页面已加载新代码。

- 暂无数小时运行、429/5xx故障注入、所有进程崩溃点或跨节点恢复验收；8小时是硬截止配置，不是已通过8小时可靠性测试。
- 当前没有联网检索/PDF解析、任意策略正式回测、Agent 调用因子演化、独立留出集准入或模拟盘工具。任意 Python 可以探索冻结数据及用户小文件，不能被包装成已验证策略。
- 隔离页面只挂接本次所需路由，因此旧固定实验、IDE本地目录等无关请求会404；IDE Monaco在该隔离浏览器未完成加载。策略落库、详情API及选中状态有实际证据；完整编辑器使用仍依赖原平台运行环境。
- 隔离测试账户为 `1`，现有回测列表组件自动补零成 `00000001`，使列表请求被已有身份校验拒绝；结果详情按真实ID可读取。没有放宽身份校验来掩盖这个问题，实际用户入口需要再次核对。
- 同节点没有统一重计算排队和磁盘配额；单作业有资源限制，不能据此宣称多课题高负载已验证。
