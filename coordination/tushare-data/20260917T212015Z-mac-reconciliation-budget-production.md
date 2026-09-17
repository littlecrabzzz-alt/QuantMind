# Tushare：分区闭包巡检不再占满真实采集轮次

- 时间、节点、任务标识：2026-09-17T21:20:15Z，Mac，reconciliation-budget-production
- 状态：已合入、部署并通过真实生产吞吐验收
- 提交：`d84eb5648d91ae86efda61927cdd70e23391775a`
- 数据边界：Mac 继续作为完整 Tushare 归档唯一写入者；云端未启动完整归档 writer。

问题证据：部署前一轮 `acquire` 在 126.383 秒内完成 0 次上游请求。它不是 dry-run，而是无上游调用的本地分区闭包巡检；默认最多检查 1000 个父分区，耗尽了本轮采集窗口。此前相邻真实轮次分别完成 410 和 394 次请求，失败阶段为空。

修复：每个普通采集轮次的后台闭包巡检默认限制为 64 个父分区，仍保留原有持久游标、逐子任务闭包与完整证据检查；精确任务批次不执行该后台巡检。轮次报告新增 `partition_reconciliation`，可直接观察实际检查数和闭包数。示例配置加入 `reconciliation_parents_per_tick=64`，合法范围为 1..1000。

验证：pipeline 18 项、partition closure 14 项、tick timing 5 项、deferred split 15 项全部通过，共 52 项；Ruff、JSON 和 `git diff --check` 通过。源码与已安装运行副本 `backend/shared/tushare_pipeline.py` 的 SHA-256 均为 `80aba6aeaa134646f7a119d26d2bb336f803c76b9b87b211d27ec8beeb5913a1`。

部署后首个完整生产轮次：真实 Tushare 请求 375 次，闭包巡检检查 64 个父分区并闭包 55 个，采集阶段 100.209 秒；`done=236024`、`empty=211880`、`pending=2885828`、`blocked=874`、`permission_blocked=4694`、`quality=564`、`resolved=4253`、`split_pending=6489`。文档阶段 `status=ok`、处理 240 项，失败阶段为空，stderr 为 0。当前固定版仍为 `data-6466fd66bd816f503e0887b226a05be8fbe1095a585ba1d5404fa2b52723ac21`，下次正常六小时发布会纳入新增数据。

云端 GitHub 直连 fetch 超时后，使用只包含 `803a1f4d..d84eb564` 的 Git bundle 传递提交；云端逐文件验证三个目标文件与提交完全一致，再以精确 index blob 和 compare-and-swap 更新 `master`。云端其他并行修改未被暂存、覆盖或重置。
