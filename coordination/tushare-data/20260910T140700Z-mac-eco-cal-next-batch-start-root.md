# Tushare：经济日历饱和拆分与下一生产批次启动
- 时间、节点、任务标识：2026-09-10 14:07Z，Mac/云端，root-eco-cal-next-batch
- 状态：进行中
- 基线：`master@e57d3da3`
- 接续：`20260910T140000Z-mac-fund-share-cursor-fix-root.md`

范围：在独立worktree实现`eco_cal`单日100行饱和后的合法country+date后代，只使用权威库已观察国家并保留`coverage_unverified`；并行只读固定第六个财务三表360-call候选，以及复核一小时发布、Mac镜像和扩盘前容量。不访问新的公共family，不把观察国家当完整历史全集。

生产边界：代码候选不读凭据、不调用上游、不写权威库。财务批次只有在任务集合、配置、runner SHA和100GiB余量重新固定后才执行；执行前让Beat和Tushare worker自然停止，批次不发布、不切换CURRENT，之后仅恢复原服务。文档worker继续暂停等待扩盘。
