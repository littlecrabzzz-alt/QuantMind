# Tushare index_weight 精确批次准备开始

- 节点/分支：Mac，`codex/tushare-index-weight-batch`，独立 worktree，基线 `ca9fdaf3`。
- 分工：只读审计权威 `index_weight` 队列，并新增专项准备器、默认 plan-only 精确运行器、测试和说明；不读取 Token、不调用上游、不写生产、不发布。
- 当前事实：云端源码与 Mac master 对齐；`index_weight` 已观察为 available，但历史全集、known_at 和单日饱和闭包均未证明。
- 下一步：固定最多 360 个既有 pending 历史任务，完成离线测试和候选哈希后提交独立分支。
