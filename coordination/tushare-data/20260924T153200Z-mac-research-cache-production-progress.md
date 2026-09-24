# Tushare 研究缓存恢复进展

- 时间、节点、任务标识：2026-09-24 15:32 UTC，Mac，research-cache-production-20260924。
- 状态：云端增量拉取进行中；接续 `20260924T150749Z-mac-research-cache-production-start.md`。
- 代码：master `af7df927` 已 push、双端 handoff/Git 对齐通过。仅改研究供数脚本、专用测试和供数说明。

Mac `com.quantmind.tushare-source` 已单独重启并可在约 2.5 秒返回上一份校验子集及 `source_lagged=true`；全量采集 worker 未动。云端定时缓存拉取曾被旧 64 MiB 清单上限阻断，新版采用 512 MiB 有界上限，源清单实测 81.69 MiB。云端正在校验和下载 83678 个缺失文件，预算内约 851 MB，旧 `CURRENT` 保持不变。

验证：研究缓存专用测试 5 项、Ruff 和 diff check 通过；云端正式容器专用数据 API 测试 8 项通过。正式容器从 `/data/tushare-research` 的旧固定版读取 `trade_cal`、`daily` 各 2 行，`upstream_calls=0`；后者耗时 25.47 秒。RRG 仍 `blocked_data`，历史覆盖和 PIT 不因读通而改变。下一步等增量校验及原子切换，复核最新云端固定版本、查询与源版本滞后。
