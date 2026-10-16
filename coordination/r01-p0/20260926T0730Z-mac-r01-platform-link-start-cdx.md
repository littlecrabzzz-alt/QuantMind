# R01 历史研究与策略入口接通
- 节点：Mac；任务：r01-platform-link；状态：进行中。
- 独立工作树：QuantMind.worktrees/r01-platform-link；基于已验收 H1 c3746c3a。
- 分工：前端 CloudStrategyManagement、研究 AgentWorkspace、复用 LedgerDetailView；本地 13001 前端运行配置；策略 61 参数/关联与独立审查材料。
- 不修改 r01-p0 / r01x-fixed-alloc 工作树及其冻结结果；H2 执行时点/整手修复仍由原组负责，本次不重启研究后端、不开启真实交易。
- 发现：13001 前端已停止；A 课题已有 E1/E2 全量证据和视图，但策略 61 没有入口关联，研究 UI 未直达账本。
- 验证：先通过真实文件 GET 和现有前端公共适配器接通，再进行浏览器核对，保留旧结果的执行规则复核标记。
