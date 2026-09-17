# Mac 股票上市日期边界已生产验收

- 时间、节点、目标：2026-09-17T06:18Z，Mac 全量归档节点；使用已保存的 `stock_basic.list_date` 裁剪 `factor_value`、`cyq_perf`、`cyq_chips` 的上市前请求。没有可靠上市日期的证券继续按原完整范围规划，不因元数据缺失缩小覆盖；不使用存在重上市歧义的 `delist_date`。
- 合同依据：Tushare `stock_basic` 文档 `https://tushare.pro/document/2?doc_id=25` 明确返回上市日期；`factor_value` 文档 `https://tushare.pro/document/2?doc_id=490` 支持 `trade_date` 和 `start_date`/`end_date`。本地保留响应得到 5,904 个有效上市日期；其余证券保持无边界。
- 代码：master `eead423260c98080b312949a0d827c4010f49d85`。planner 将上市日期加入 factor/cyq planning policy，完全在上市前的日/月跳过，跨上市日月份从 `list_date` 开始；标识符缓存升级到版本 2。新增原子、可回滚且无上游调用的队列迁移器及回执。
- 验证：61 个 factor、technical、discovery、planning 与迁移离线测试通过；Ruff、`git diff --check` 和 compileall 通过。13,324,275,712-byte 一致副本 dry-run/apply 均识别 200,765 个候选和 190 个跨界替代，保留 358,096 个 attempts 与 354,764 个带结果任务；提交后副本 `PRAGMA quick_check=ok`。
- 生产事务：worker 暂停后 211.93 秒原子提交；实际 supersede 201,005 个 pending 上市前/跨界任务，先建立 190 个跨界替代，保留 360,369 个 attempts 与 357,037 个带结果任务，候选 attempts 为 0，`upstream_calls=0`。回执 `/Users/lizeyu/Library/Application Support/QuantMind/tushare/stock-lifecycle-migration-v1.6532fc5c139545b32187b92b753988f2c554e683f66e3e8bdb7564845eba2d49.json`。
- 无遗漏边界：`factor_value` 保留 12,904 个未知生命周期 pending；`cyq_perf`、`cyq_chips` 各保留 6,392 个。迁移后及新版规划后，三个 API 的已知上市日期证券中，pending/split_pending 上市前或跨界旧任务均为 0；已完成、empty、quality、permission、raw object、Parquet、附件和调用证据不改。
- 规划与运行：identifier cache v2 已建立，四个 factor/cyq planning checkpoint 都冻结 `stock_lifecycles`；首次新版规划 118.71 秒、failed_stage=null。LaunchAgent PID 99274 运行；真实采集周期完成 322 次请求/89.97 秒、failed_stage=null，当前 pending 3,121,709。
- 存储与节点边界：本地卷 3.6TiB，已用 1.3TiB，可用 2.3TiB。完整 Tushare 归档仍只由 Mac 持有和采集；云端只保留研究子集，完整 writer 继续停用。全量历史仍未完成，worker 持续补采。
