# Tushare 文档容量可观测性开始

- 时间、节点、任务标识：2026-09-10，Mac，document-capacity-observability
- 状态：进行中
- 分支、worktree：`codex/tushare-capacity-observability-20260910`，`/Users/lizeyu/.codex/worktrees/quantmind-tushare-capacity-observability`，基于 `origin/master` `3615beba`
- 分工：只补文档 worker 现有状态回执中的 100 GiB 余量、长期趋势与告警；专项测试和文档证据。生产仅短时只读审计，不访问上游、不改生产。

当前状态文件与通用 health 均未暴露 Tushare 100 GiB 停采线、阈值 headroom 或可判断的容量趋势。候选复用 `document-worker-status.json`，不新建监控服务或通知通道。
