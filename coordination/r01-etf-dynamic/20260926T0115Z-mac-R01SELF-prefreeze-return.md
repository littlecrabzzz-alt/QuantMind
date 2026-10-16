# R01SELF：预冻结返工与本组平台身份

- 时间/节点：2026-09-26T01:15Z，Mac local-sandbox；Herdr `wN`。
- 状态：进行中；独立工作树 `../QuantMind.worktrees/r01-etf-dynamic-self` / `herdr/r01-etf-dynamic-self`；共享后端/H1源码未修改。
- 接续：本主题 `20260925T172534Z-mac-R01SELF-start.md`。

已收到四成员成果。主控退回方法和runner：基线独立理由不足，runner的safe资产/正动量门槛/低波语义与方法草案冲突，矩阵缺参数/2万覆盖。已派设计修订、代码对齐、新鲜上下文独立方法审查和平台bootstrap实现；**真实策略收益0次，未冻结未开跑**。

只写本组四个沙盒课题，case ID见主控run `case_ids.json`；没有写旧A/B或R01X-A，没有修改共享readiness。研究人类入口：`../投资学习与研究/研究/R01SELF-动态规则/README.md`。

核对：handoff passed，主树 `e23b6712`；Mac local-sandbox。包42/42哈希通过，H1相关109 tests passed（`-o addopts='' -p no:cacheprovider`，真实log在run/evidence）。H1代码c3746c3a无跟踪文件修改；依赖符号链接原样。H2-L仍只余AC01时间合同未通过，不阻塞H1。

证据/裁决/恢复：`~/.pi/agent/skills/herdr-controller/runs/r01-etf-dynamic-self/decisions/D02-pre-freeze-return.md` 和 `STATE.json`。下一步审查v2合同与修正代码，通过后冻结再分阶段连续账本执行；本组不占共享服务重启或发布窗口。
