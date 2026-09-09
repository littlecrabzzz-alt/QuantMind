# 研究讨论、计划版本与显式执行
- 用户已要求按讨论方案实施；前一轮 process-ui-start 已暂停且未改业务代码，本条取代其执行范围。
- Mac 独立 worktree quantmind-glm-research-validation，codex/research-workbench。范围：research/drafts.py、planning.py、routers/research_drafts.py、现有研究路由/Store/tasks；新增版本化SQL及准备脚本；ResearchWorkbench 与新讨论/过程组件、请求客户端、测试/文档。
- 新问题/材料/已有结果均可建草稿；模型只产出回答/计划，程序核对可用数据工具，缺项明确阻塞。计划版本经明确确认才原子创建执行；讨论不执行，改计划先暂停已有任务，版本/执行幂等持久化。旧直接默认启动入口关闭，已有结果保留。
- 验收：隔离DB并发与权限/计划失效/暂停/审批/恢复；前端类型及真实交互；真实模型仅做讨论/规划验收，不因测试擅自重启被取消的课题。部署按现有双端入口，只重启相关研究服务。
