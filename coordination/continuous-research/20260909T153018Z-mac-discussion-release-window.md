# 讨论计划改版：发布窗口
- Mac codex/research-workbench 独立候选；范围沿用 research-discussion-start，另含 coordinator.py 将完整已确认计划传入候选提示（不改变原数值计算）。
- 隔离 PostgreSQL HTTP/并发/回滚/暂停/版本/旧入口/继续重放测试通过；原真实 Docker 取消及17项合同单测通过；前端类型检查通过。真实模型仅做规划验收，尚未执行新研究。
- 当前本地窗口：completed1/cancelled9/paused1/blocked1；云端 completed1/blocked2，均无活动研究。占用 API quantmind 与专用 research-worker 的短发布窗口，不重启 Tushare 或通用worker。
- 将备份现有 research_cases/research_windows；仅新增 research_drafts 表和索引，迁移可重入，不修改/删除旧研究；原取消状态保持。候选提交合入后按 handoff 核验、重启相关服务、web-publish，最后真实页面与API读写验收。
