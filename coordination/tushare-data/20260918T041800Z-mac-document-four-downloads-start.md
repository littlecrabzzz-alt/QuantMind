# Mac Tushare 附件四路下载开始

- 时间、节点、任务：2026-09-18T04:18:00Z，Mac 全量归档所有者，document-four-downloads。
- 前置结论：登记游标后的已购文本/附件 attempt 共约 14256687 条 records，按 5000/轮约 3.6 天，可在结构化队列约 5 天的时间量级内追上；不再扩大登记预算。附件 pending 仍超过 148 万，三路真实周期约完成 192 至 261 下载/100 秒，成为最终本地化瓶颈。
- 变更：只把公开附件下载合法并发从 3 扩至 4；每轮 600 阶段、100 秒全局截止、单下载 20 秒、失败退避、来源挑战分类、SQLite durable claim 和 Tushare API 频率不变。同时让原生 worker 严格拒绝布尔/越界配置，并把保留的 Celery 入口边界与当前 600/100 配置对齐。
- 验收：观察真实 acquisition 的 API 请求、附件下载/解析、source_challenge、timeout/retry 和 failed stage。若出现持续 API 回退、来源挑战新增或可重复错误，恢复三路；不会绕过挑战或提高单来源请求时限。
- 隔离：候选在 `/private/tmp/quantmind-tushare-document-four-downloads` 的 `codex/tushare-document-four-downloads` 分支完成；生产需在完整周期边界安装。
