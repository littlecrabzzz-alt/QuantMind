# 薪酬追加 scope 优先提交

- Root生产首轮planning160秒在普通family enqueue超时，追加scope末尾尚无执行保证。新候选从master4e4b58d建立独立分支codex/tushare-rewards-append-first；只改pipeline规划器枚举顺序（stock_rewards_periods优先，其他相对次序保持）、原追加专项test和短doc。
- 验证后续普通family耗时/异常时追加job+checkpoint已独立提交，原family游标未重置；不更改预算/快照/任务身份/配置/生产。没有上游请求或服务操作。
