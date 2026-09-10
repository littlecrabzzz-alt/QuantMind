# 基金份额历史追加范围

`fund_share` 合同和固定版 reader 已存在，但生产 `history:market` 被更大的基金净值、指数权重等枚举挡在中途，权威库此前只有 11 个 `done`、4 个 `empty`，没有历史 pending。新增 `history:fund_share_history` 只枚举原市场 planner 的 `fund_share` 历史任务，继续使用日×SH/SZ、`epoch=history`、原任务 ID、market 公平调度、分层限频、原始响应留存、不可变发布和 Mac 镜像。

该追加范围不修改 `history:market` 的签名、offset 或任务，已存在 ID 幂等跳过并且不消耗每轮500个新任务的预算。它受既有 `enable_market` 和 `market_apis` 门控，不增加生产配置键。

2026-09-10 部署 `8a9e5dfb5e44a436d82b1321cc1fe435b95a8652` 后，断网、共享锁内的有界规划覆盖 1990-01-01 至 2026-09-02，沪深各13,394项，共26,788个历史任务。第一次 helper 成功提交500项后因读取不存在的报告字段退出；v2从offset 500幂等继续53轮，最终 `offset=26788/done=1`，任务集合 SHA256 `44088911b86a7b59a72b230cb4c3eb06a73a8c50dae230d42fbbee9070409243`。全程上游调用0、凭据访问0、无发布或 `CURRENT` 切换。

恢复常驻 worker 后发现首版签名把 `market_apis` 的显式 `['fund_share']` 和生产配置的默认值视为不同策略，正常规划一度把游标重置到 `offset=12495/done=0`；任务主键保持幂等，已生成任务和原始结果没有丢失或重复。`4302970a8ef993bfd506397245aa04c3efc01dda` 将追加范围的签名缩为真正影响任务集合的 `history_start`。修复后 v3 在断网、禁凭据条件下一轮确认 `offset=26788/done=1`，随后正常 Beat/worker 周期用133.442秒完成且游标仍为 `26788/done=1`。当时任务为5 done、26,783 pending、0 error；v3收据 SHA256 `604cf8835dad7ff8df7fc8b174e8cb742370a10826bcbfafdca40ed668b71ed0`。

生产常驻 worker 恢复后已开始消费。1990-01-01 是请求范围，不证明供应商当时已有 ETF 或已经返回完整历史；非交易日空响应、修订和历史可见时点继续按原合同保留，不能从规划完成推断数据完整。
