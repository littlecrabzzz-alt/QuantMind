# Mac Tushare 文档登记连续扫描生产验收

- 时间、节点、任务标识：2026-09-18，Mac，document-registration-continuous-scan
- 状态：生产保留；Mac 继续作为 Tushare 完整归档的唯一写入者
- 代码：`master` / `origin/master` `6d716edd70badc2626dea0dda41c8b20b69ac4db`
- 接续：`20260918T120516Z-mac-document-registration-scan-start.md`

原实现每轮只读取 1,000 个连续 attempt。在附件观测稀疏的区间，即使 90 秒、200,000 行和 100 个观测的既有硬预算还有大量空间，登记也会提前结束。保留的修改在同一次 `register_documents` 中按 1,000 条分页继续扫描，直到命中现有时间、记录或观测预算。SQLite 单事务仍不超过 1,000 行，精确游标、部分 attempt offset、幂等引用和失败重放语义保持不变。

专项验证重跑 13 项全部通过。代码与本地运行时 `tushare_pipeline.py` SHA-256 均为 `edbe88e1b5d20b84c643b6660683dc4cc8a4355a37672350a4e9d1ceefd2d5d1`。生产 `pipeline-config.json` 保持 `document_registration_max_records=200000`、`document_registration_max_seconds=90`、`document_registration_max_observations=100`，文件 SHA-256 为 `9c5783305de8e22065eefefd9f9ff575645bbd1fe37c7e14081a2dcc0662aca5`、权限 0600。`ENABLED` SHA-256 为 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`、权限 0600；本记录不包含 Token 或其他凭据。

部署后 8 个真实采集周期共发出 3,128 次 Tushare 请求，登记 1,600,000 条记录和 310 个附件观测，同时处理 16,000 个文档阶段任务；8 轮 `failed_stage` 均为空。其间一个定时规划周期显示 `planning_only` / `requests=0`，该周期仅重建任务队列并继续处理 2,000 个文档任务，不是 dry-run，也没有替代正式采集。

真实高密度 `anns_d` 区间先按硬记录上限逐轮消化；进入稀疏区后，2026-09-18T12:32:35Z 开始的周期在 65.502 秒的登记阶段内扫描 2,369 个连续 attempt，登记 63 个观测并处理 200,000 条记录。该周期同时发出 420 次真实请求、处理 2,000 个文档任务，总耗时 168.935 秒，无失败阶段。这是生产库上跨过原 1,000 条单页限制的真实证据。

从部署前快照到本次验收，登记游标由 180269 前进到 183604，供应商 attempt 最大 rowid 由 699242 增到 702452；同期 attempt 差距由 518973 降到 518848，在新数据继续进入时仍净回收 125 条。待登记附件 attempt 由 10770 降到 10558，净减少 212；当前分项为 `anns_d=6663`、`idx_anns=1414`、`research_report=1185`、`npr=688`、`monetary_policy=608`。

完整范围审计同时确认 247 个已注册接口全部有运行时 reader，没有可操作的已注册未规划项。11 个历史 `api_error` 是已保留的供应商 40101 “接口名无效”证据，不循环重试；871 个 blocked 任务继续作为可审计缺口保留，不伪造分页或删除状态。

`com.quantmind.tushare-archive` 运行为 PID 71922，自部署后未退出；本地归档磁盘约 3.6 TiB，已用 1.4 TiB，可用 2.1 TiB。下一步保持 Mac 全量归档连续运行，云端只快进代码并保留受限研究缓存，不恢复云端全量 writer。
