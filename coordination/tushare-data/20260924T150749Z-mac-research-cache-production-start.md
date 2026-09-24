# Tushare 研究缓存生产可用性恢复开始

- 时间、节点、任务标识：2026-09-24 15:07 UTC，Mac，research-cache-production-20260924。
- 状态：进行中。分工仅 `scripts/tushare_research_cache.py`、其专用测试、供数说明及本主题新增记录；隔离分支 `codex/tushare-research-cache-production-20260924`。
- 基线：master `51c8f43c`；`dual-node.sh handoff` 通过。主工作树有其他研究者未提交文件，保持原样。

现状：Mac 全量 `CURRENT` 为 `data-525e814e…`，含 150245 个 12-API 分区；云端已启用研究缓存作为正式应用读源，但其 `CURRENT` 停在 2026-09-20，定时服务在供数 `/CURRENT.json` 等待阶段失败。Mac 供数每次新版同步准备会检查约 15 万分区，服务阻塞超过 SSH 稳定窗口。候选拟让供数入口先返回已验证的前一子集版本，同时在后台准备最新版并明确暴露源版本滞后；不得假称新版本已就绪。仅改供数读链路，不改全量采集、RRG 准入或交易服务。

验证待做：隔离单测、Mac 供数与云端定时真实拉取、固定版查询、源版本滞后和磁盘状态。生产服务只允许单独重启供数进程，不碰采集 worker 或其他服务。
