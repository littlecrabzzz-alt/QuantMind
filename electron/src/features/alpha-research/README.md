# 研究工作台的历史账本入口

外部课题通过 `components-v2/ResearchLedgerPanel.tsx` 选择已登记的 evidence/view JSON。沿用研究文件 API、SHA256 与公共 ledgerAdapter，不复制账本、不写虚拟成交，不把工程样例当作真实交易。

`LedgerDetailView` 的 `showCurve` 展示权益及回撤；收益从 session.initial_cash 计算，包含首日损益与费用。缺少初始本金或逐日净值时不生成完整区间收益；原件哈希不符时拒绝渲染。`ledgerPerformance.test.ts` 覆盖首日亏损、缺净值、缺费用。

策略关联来自统一策略 API 的 `parameters.research_case_id`；`historical_results` 可提供文件说明，`research_review.summary` 展示独立复核结果。此 UI 变更不授予运行准入，不启动调度。
