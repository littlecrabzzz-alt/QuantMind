# Tushare：文档注册 20k 灰度开始
- 时间、节点、任务标识：2026-09-18，Mac，document-registration20k
- 状态：进行中
- 分工：仅调整 Mac 私有文档注册记录上限并观察真实周期，不改 Token、代码或其他数据链路
- 接续：`20260918T072717Z-mac-document-registration-catchup-production.md`、`20260918T083102Z-mac-document-parse2-stage1600-production.md`

现状：每轮 10,000 条注册最近约 3.57 秒，仍有 5 秒硬截止余量；游标 176307，注册积压仍在持续生成 pending 文档。代码已经测试允许 20,000，事务仍按 100 条分块并使用持久游标。

灰度只把 `document_registration_max_records` 从 10,000 改为 20,000，`document_registration_max_seconds=5`、观测上限 100 和所有采集/文档资源边界不变。若 5 秒先到，事务安全返回 `deferred_budget` 并从精确 offset 续跑；以真实注册条数、耗时、请求数和失败阶段决定保留。
