# GLM 12:48 巡检：公共计算双槽试运行

用户已授权持续优化额度利用。本轮 worktree `codex/glm-continuous-research`，起点 `a6702129`；主树 handoff 通过，主树仍 `215f89c8`。仅负责 `scripts/start_r01_platform_candidate.py` 和两份 continuous-research 文档，不修改主树业务源码。

官方额度 99% 剩余，重置提示 16:31:20 北京时间；公共队列积压 8。现有 Celery worker 单槽，Docker VM 18 CPU/31.29 GiB；通过 Celery 自带 pool_grow 对本组唯一 worker 加一个进程，未重启服务。04:53Z 观测两个不同真实回测同时运行，新增进程的任务已完成。模型维持 glm-5.3/max、3 槽；股票重计算的每节点单容器限流保留。

计划把新建 worker 默认计算槽写为 2，原 A worker 已为 2，不改变其行为。现有容器 Cmd 仍为 1，live pool=2；普通容器重启会恢复 Cmd 的 1，巡检按实际进程检查，不能盲目重复 pool_grow。仅在未来空闲重建本组 worker 时启动参数才永久采用 2。

证据位于仓库外 `投资学习与研究/研究/GLM持续研究/巡检/20260927T0448-evidence/`。不修改 A、不触碰保留段、不晋级候选、不发布云端。
