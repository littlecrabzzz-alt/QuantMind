# Tushare：基金份额追加游标生产修复
- 时间、节点、任务标识：2026-09-10 14:00Z，Mac/云端，root-fund-share-cursor-fix
- 状态：修复完成，持续采集
- 提交：`master@4302970a`
- 接续：`20260910T134200Z-mac-next-closure-production-root.md`

发现：首版追加planner把显式`market_apis=['fund_share']`与生产默认值计入不同策略签名，正常worker恢复后曾将规划状态重置到offset12495/done0。任务主键幂等，已有任务、终态和原始结果未丢失或重复。

修复：固定family的签名只保留真正影响任务集合的`history_start`，新增默认值/显式值等价回归。Mac相关45项、Ruff及云端生产镜像断网4项通过；GitHub、Mac和云端代码先对齐再执行生产修复。

验收：v3断网规划确认26788个任务与原集合SHA完全一致、offset26788/done1、上游和凭据访问为0；收据SHA `604cf883…`。恢复Beat/worker后的正常周期133.442秒成功，周期后仍为offset26788/done1，任务5 done、26783 pending、0 error。文档worker继续暂停等待扩盘，结构化采集和固定版发布照常。
