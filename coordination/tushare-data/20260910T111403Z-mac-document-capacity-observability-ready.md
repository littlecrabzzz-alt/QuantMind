# Tushare 文档容量可观测性候选就绪

- 时间、节点、任务标识：2026-09-10，Mac，document-capacity-observability
- 状态：待交接
- 分支、worktree、提交：`codex/tushare-capacity-observability-20260910`，`/Users/lizeyu/.codex/worktrees/quantmind-tushare-capacity-observability`，`ea0623d0`
- 分工：只改文档 worker 既有状态回执、专项测试、运行说明和脱敏审计证据；未改生产或调用上游。
- 接续：本主题 `20260910T110608Z-mac-document-capacity-observability-start.md`

34个成功批次跨5个发布周期，0 database locked/任务失败/软硬超时；1956 stages中1059下载、897解析，只有2/34批在80秒内命中100上限，因此不提吞吐。候选在现有`document-worker-status.json`加入100GiB reserve、headroom、至少30分钟累计趋势、72小时预计触线与40GiB低余量warning；低于reserve继续沿用`blocked_disk_reserve`。不含路径、Token、URL、正文或订单信息。

验证：Python3.10.19全部`test_tushare_document*.py` 75项通过；Python3.13同75项通过；Ruff、JSON解析和`git diff --check`通过。证据`docs/tushare-document-capacity-observability.evidence.json`。下一步由集成人审查后合入master；部署只需等待文档任务自然排空并重启document worker，再观察首轮字段，30分钟后验证趋势warning。不要直接扩盘或修改生产队列。
