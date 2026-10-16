# GLM 五小时研究方案实施
用户已确认上一轮方案：官方五小时至少50%、目标60%，取消的Codex小时巡检保持删除。
分支 codex/glm-continuous-research，worktree QuantMind.worktrees/glm-continuous-research，起点03dae6d8，开工clean。
分工：主控负责continuous_research router/state、窄证据接续、集成/测试/仅本组空闲服务上线/首批派发；glm_capacity_now负责controller.py中的Pi max、调用追踪与额度曲线及相关独立helper/tests；glm_deep_topics_now只在仓库外准备A/B/C研究输入、预注册与幂等派发请求，不自行调用模型/派发/重启。各自文件边界不重叠，完成后主控明确暂存提交push。
维持stock_scope_hold、既有间接暴露事实和2026-03-24 ETF开发截止；不读取旧污染股票评价，不训练/恢复股票，不改A账户、保留期、晋级、交易或云服务。
本机desktop-linux Docker，本组仅18084 Engine/专用worker/controller；新模型调用起点单独记T0，未达50%不得称达标。复用原队列、API、Pi与证据工具，不新增框架。
完整方案位于仓库外 GLM持续研究/trace-review-20260929/五小时研究与额度方案.md。
