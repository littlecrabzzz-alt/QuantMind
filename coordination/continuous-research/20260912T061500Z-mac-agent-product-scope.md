# Agent 接入范围增量
- 分支 codex/research-agent-product；仍在隔离 worktree 验收，未占共享服务发布窗口。
- 为成果联动补充负责文件：BacktestPersistence（研究记录不受普通10条历史清理影响）、AIIDEPage/BacktestHistoryModule/NewBacktestCenterPage/App.tsx/alpha-research types 与服务（成果深链接和返回课题）；docker-compose.yml、独立 Agent Dockerfile/依赖；local-dev.sh 增加 Agent 启停与子容器切换保护。
- 隔离输入为 frozen-controls-20260907-v3 的 APFS clone，输出 /private/tmp/qm-agent-product-acceptance/.local-dev/project；仅临时 PG/Agent/gateway 容器，无正式库写入。
- 原生工具文件与代码已实测；正在补齐因子回执幂等、回测核验落库、实际停止和页面验收。先前发现并修复 DockerClient 上下文和成果事件参数冲突；没有用模型文本充当成果成功证据。
