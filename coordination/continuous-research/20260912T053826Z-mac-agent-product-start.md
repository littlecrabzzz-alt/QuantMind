# Research Agent 产品接入开工
- 节点：Mac；分支 codex/research-agent-product；隔离 worktree /private/tmp/quantmind-research-agent-product。
- 接续 53407008、docs/deepagents-validation-20260912.md；状态：进行中。
- 分工：新增 backend/services/research_agent/，engine/routers/research_agent.py 与 main.py 注册、research/drafts.py 旧入口隔离；alpha-research 下 Agent 工作区、成果跳转；独立 Agent Dockerfile/Compose/本地启动入口；必要测试及现有持续研究文档。
- 重用 Deep Agents、LangGraph、research_drafts、既有认证/因子库/策略存储/回测入口。讨论、审批、可见工具、文件、打断与消息形成实际闭环。
- 当前只占候选文件，未占共享服务发布窗口。其他数据采集/研究文件保持原状。云端预检存在 celery-beat 停止，不为接入启动业务调度器。
- 验收先用隔离数据库和目录，真实 GLM 有限运行；不恢复旧取消研究，不向云端回灌本地成果。
