# Tushare equity announcement append planning start

- 时间、节点、任务标识：2026-09-10 UTC，Mac，coverage_gap_audit
- 状态：进行中
- 分支、worktree：`codex/tushare-equity-announcement-append`，`/tmp/QuantMind-equity-announcement-append`
- 分工：只读审计并补 `stk_holdernumber`、`stk_holdertrade`、`repurchase` 的独立历史追加规划；不修改 index_weight/fund_nav，不访问凭据或上游，不写生产数据。

只读生产证据显示 `history:equity_event` 已推进到 offset 175000，但三个全市场公告月窗接口各仅约 17 个任务；同一枚举流前置的两类逐股十大股东任务已各约 9 万。候选复用现有合同和任务身份，在独立 append scope 中公平交错三个公告月窗，旧 scope/cursor/signature 保持不变。
