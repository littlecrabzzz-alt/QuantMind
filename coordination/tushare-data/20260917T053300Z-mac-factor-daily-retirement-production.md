# Mac factor_value 遗留日任务退役已生产验收

- 时间、节点、目标：2026-09-17T05:33Z，Mac 全量归档节点；只退役已被现有月范围任务明确覆盖的 `factor_value` history 日任务。本次队列迁移不访问 Tushare，不改近期 7 日增量，不改已完成结果、原始对象、attempt 账本或月任务。
- 官方合同：`https://tushare.pro/document/2?doc_id=490` 当前列出 `ts_code`、`trade_date`、`start_date`、`end_date`，单次上限 6000 行。生产既有真实证据包括 000001.SZ / 20260801–20260831 的 4340 行成功响应和 20260901–04 的 780 行成功响应；6000 行触顶继续使用已有合法日期二分。
- 范围核验：`cyq_perf`、`cyq_chips` 的 history 队列已经全部为按月范围任务，按日任务只属于近期增量，因此未改。`factor_value` 的遗留 history 日任务均落入现有同证券、同字段、同行数上限且状态可继续执行或已成功的范围任务；empty、blocked、permission/quality 状态不会被当作覆盖。
- 代码：master `b1a228ed873c6645c439fab221bc0a9ebd924114`，新增 `scripts/tushare_factor_daily_retirement.py`、专用离线测试及原生运行时安装清单。39 个 factor、calendar、range 相关测试在已部署依赖环境通过；Ruff、`git diff --check`、py_compile 通过。
- 一致副本验收：SQLite 在线备份 13,324,275,712 bytes；dry-run 与 apply 都识别 43,629 个旧日任务、166,868 个可用月任务、0 未覆盖、0 候选 attempt，保留 354,872 个 attempts 和 351,540 个带结果任务；副本应用后活动 split parent 指向退役任务为 0，`PRAGMA quick_check=ok`。
- 生产事务：worker 暂停后 48.69 秒原子提交；实际识别并 supersede 43,628 个旧 history 日任务，0 未覆盖，0 候选 attempt，保留 355,643 个 attempts 和 352,311 个带结果任务。回执 `/Users/lizeyu/Library/Application Support/QuantMind/tushare/factor-daily-retirement-v1.9e7655505404938c805faeecbada16d0726ba5c680a03f21aef43655051ee611.json`；`upstream_calls=0`。
- 提交后验证：一致 APFS 副本完整 `PRAGMA quick_check=ok`；生产 `factor_value` history pending 只剩 166,868 个范围任务、日任务为 0，活动 split parent 指向退役任务为 0。`cyq_perf`、`cyq_chips` history pending 分别只剩 56,901、56,908 个范围任务。
- 运行验收：仓库和原生运行时 helper SHA-256 都是 `4e6cdfe5cc2a8f48f60c6f233a985a48a0e26ba736f54c9391bab8fee28654ea`。LaunchAgent PID 87220 恢复运行；首个完整真实周期于 2026-09-17T05:32:30Z 完成，92.077 秒、249 次上游请求、failed_stage=null，账户门控 500 rpm，队列 pending 3,302,421。
- 存储与节点边界：完整 Tushare 数据继续只由 Mac 持有和抓取；云端仍只保留研究缓存，不部署全量 writer。全量历史尚未完成，worker 持续运行。
