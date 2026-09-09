# schema3及八接口发布开始

- 父候选f2cd52e已push，364tests/Ruff通过；主线1fba0bf双端handoff passed（4521files，8564a44ed3dbadad6a27abc91a13d3538deda26ef48e63617e271903c0767a69）。
- 只暂停tushare_acquire/documents消费者，自然排空后准备合并发布；没有训练/research活动。普通US同步88fe98db-f897-42a9-932c-cc1a84860e10仍活动，独立run_market_sync->quantus_daily_sync不重启该worker。
- 备份snapshot422770此前已终止75，不重试。父负责API新reader、文档DB备份/meta1到3迁移、全行hash、8API有界样本及云端/Mac验收，最后必恢复两专属队列并核验真实任务。
- remaining limit_extra纯合同、text附件原响应诊断独立继续。
