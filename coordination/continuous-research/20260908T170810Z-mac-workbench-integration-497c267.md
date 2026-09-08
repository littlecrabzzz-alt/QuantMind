# 研究工作台进入双端真实验收
- Mac；任务 01a08188-b391-7fd3-aa2a-d7c9eef2689d；进行中。
- 接续 20260908T162644Z-mac-workbench-implementation-f3715aee.md。实现提交 497c267，独立分支 codex/research-workbench 已合并当前 master。
- 文件归属沿用开始记录；新增运行说明 docs/research-workbench-operations.md 和持久化检查 scripts/test_research_persistence.py。不修改 Tushare 采集、队列或运行配置。
- 已验：前端 typecheck；15 项数值/合同/退避回归；临时 PostgreSQL 并发幂等、账户/节点隔离、租约恢复、暂停续开；真实隔离容器取消；实际后端镜像成功加载路由与专用队列。
- 本地冻结输入已准备在 .local-dev/project/data/research/inputs/frozen-controls-20260907-v3，node adb51708ac1281182ebe。
- 下一步：集成主树、双端核对与新增表迁移，启动专用 research-worker，真实页面/模型链路验收。仅重建含新增挂载的 API 容器及新研究 worker；保留现有采集 worker 与数据库任务。当前不能宣称产品端到端完成。
