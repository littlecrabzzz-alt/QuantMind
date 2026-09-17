# Tushare stk_rewards 终止标记复核
- 时间、节点、任务标识：2026-09-17 UTC，Mac，stk-rewards-terminal
- 状态：进行中
- 分支、worktree、提交：计划使用 codex/tushare-stk-rewards-terminal 和隔离 worktree；主工作树已有 RRG/研究未提交文件不触碰。
- 分工：仅负责 stk_rewards 的供应商终止标记契约、对应测试、已留存响应的零上游重判和生产验收。
- 接续：20260917T160739Z-mac-ths-member-terminal-production.md

官方 doc 194 仅提供必填 ts_code 与可选报告期 end_date，未公布分页/行上限。生产 6 个 blocked 响应均为单股票、HTTP 200、完整字段，1018–1428 行、has_more=false、主键无重复且对象哈希通过；本地 1000 行未验证阈值造成误报。

验证计划：隔离 worktree 增加限定契约标记与回归测试；通过后合入 master，等待归档 worker 自然周期边界，再以原始对象重判，确保 attempts 不变、上游请求为 0、对象/观察/Parquet 不变。
