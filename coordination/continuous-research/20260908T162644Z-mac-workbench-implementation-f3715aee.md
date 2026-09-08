# 研究工作台：按产品方案实施并双端真实验收

- 状态：进行中；任务 research-workbench，Mac 开发、云端/本地沙盒验收。
- 接续产品方案 2cb059a；分支 codex/research-workbench；worktree /Users/lizeyu/.codex/worktrees/quantmind-glm-research-validation，已合并主分支 0a5b890。
- 文件归属：新增 backend/services/engine/research/ 模块与 routers/research_runs.py、研究 worker 与 SQL 迁移；现有 engine/main.py 与 API 网关注册入口；Alpha Research 首页/任务视图/API；scripts 下冻结研究扩展与验收脚本；独立研究 worker 的 Compose 服务及 local-dev 入口。保留现有 Tushare acquisition 任务、调度与未提交 RRG/研究监控文件。

先持久化课题/窗口/阶段、幂等和恢复，再接策略实验与新因子计算，最后页面和实际双端验收。部署前再次核对活动训练/采集；不重启采集 worker，不改其 Celery 注册。采用已有 Celery/Redis 的独立研究队列，避免长研究占用行情/采集队列。全部真实结果在各自数据角色的独立研究目录；研究不发布信号或修改活跃策略。
