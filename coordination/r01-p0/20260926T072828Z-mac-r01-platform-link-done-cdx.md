# R01 历史回测入口接通：本地完成
- 节点：Mac；任务：r01-platform-link；状态：完成（持续虚拟盘仍受阻）。
- 分支：codex/r01-platform-link；worktree：QuantMind.worktrees/r01-platform-link；提交：9011e9b3b013fa72cf90f4ad0e13b3d09e63ef49。
- 分工范围：统一策略服务状态透传、CloudStrategyManagement 配置与研究链接、外部课题历史账本面板、复用 LedgerDetailView 的曲线/日期明细及初始本金收益口径。未改 H2 原修复组工作树。
- 当前 13001 前端从本次工作树运行；H1 后端、已签署准入、冻结输入与研究原件不变。不把新前端改动冒称原 c3746c3a 全部源码。共享主分支未合入，云端未发布。
- 策略 61 parameters 已关联 A 课题与 E1/E2 文件哈希、独立审查摘要；原 code/权重/调度开关不变，draft/stopped 读回。研究原件 37 份未改。
- 验证：同提交 typecheck 0、3 项收益口径测试通过、build 0；真实浏览器完成 E1/E2 切换、首日订单费用核对、策略双向跳转与刷新。
- 证据：投资学习与研究/研究/R01-平台接通/20260926/接通记录.md、api-verification.json、ui-verification.json、source-verification.json。
- 待原修复组：公共合法卖出申报与目标数量；H2 数据可得时刻与执行窗口。关闭后重跑历史并独立复验，再冻结候选和未来真实验证起日。不可把现有历史改称盲测；当前未启用调度或虚拟成交。
