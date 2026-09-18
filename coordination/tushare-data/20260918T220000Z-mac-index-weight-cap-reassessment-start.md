# index_weight 7000 行边界重评开始

- 时间、节点、任务：2026-09-18T22:00:00Z，Mac 全量归档唯一写入者，`index-weight-cap-reassessment-20260919`
- 状态：进行中；生产同步保持运行，代码在独立 worktree 开发，主工作树只追加协调记录
- 基线：master `f28a4ffb42d090afbeab5bf8f1e55c8d13b96827`。生产库现有 8208 个 `index_weight` 结果，其中 6 个恰好 7000 行且 `has_more=true`；1344 个原本因旧 1000 行本地阈值报警、但低于 7000 行且 `has_more=false`。91 个最终阻塞项均为单日请求，既有离线审计无重复自然键、权重和约为 100。
- 分工与文件：本任务负责 `backend/shared/tushare_market_contracts.py`、`backend/shared/tushare_intake.py`、对应测试和生产证据；不改当前未提交的 RRG、研究监控文件。
- 方案：把新任务的保守边界改为生产实测的 7000，并允许重评旧任务时使用当前合同边界；仍将 `has_more=true` 视为未完整。先离线测试，再等待生产周期自然结束，在唯一写锁下以零上游请求重评旧阻塞结果。

下一步：实现定向测试和完整 Tushare 回归；通过后合入 master、部署运行副本并生成只含汇总的重评收据。
