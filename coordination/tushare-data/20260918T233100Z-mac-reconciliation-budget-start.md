# Tushare：本地分片复核预算与计划指纹修正
- 时间、节点、任务标识：2026-09-18T23:31Z，Mac，reconciliation-budget
- 状态：进行中
- 分支、worktree、提交：计划从 master 465969c8 建立 `codex/tushare-reconcile-fingerprint-20260919`；候选位于同步范围外的独立 worktree。
- 分工：仅修改本地分片复核运行控制、对应回归测试、生产验收证据和本记录；保留主工作树现有 RRG/研究修改。
- 接续：`20260918T225929Z-mac-wz-scoped-planning-complete.md`。

发现 `reconciliation_parents_per_tick` 只控制无上游请求的本地分片闭合扫描，但当前被纳入采集规划指纹；生产默认每轮只扫 64 个，而 split_pending 已约 10,610。先修正指纹语义并测试，再在自然周期边界原子提高本地复核预算，记录真实周期耗时、闭合数和请求边界。Tushare 采集和文档处理在候选开发期间继续运行。
