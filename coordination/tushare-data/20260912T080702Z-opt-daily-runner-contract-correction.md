# opt_daily 单请求 runner 合同更正

- 时间、节点、任务：2026-09-12 08:07:02 UTC，Mac，`/root/queue_headroom_audit`
- 状态：更正并取代 `20260912T080238Z-opt-daily-one-call-runner-ready.md` 中“可复用 runner”的结论
- 结论：SHA-256 `abffa078fbd6c8ea25519c0a0e6c62cad98edb5cba2c5a4f40e1e6b39a1e9f7a` 的 `/tmp/run_tushare_opt_daily_one_call.py` **不得再次用于生产执行**；其配套测试 SHA-256 `29a950cc2265313677cfe53d1731e09c9a92e2f4f7c29ce17ac26f6d90f0a8d3` 也只作为本次历史执行材料保留，不能视为通用合同验收
- 本记录仅追加审计结论；未修改 runner/test，未访问 authority、凭据或上游，未改服务、配置、队列或发布状态

root 已报告本次请求返回 1 行。该事实只表示 bounded 请求完成；数据链与发布纳入仍由 `next_window` 的严格独立 closure 核验。在 closure 完成前，不从该 1 行推导历史完整、版本完整、PIT、期权全市场覆盖或可自动启用。

## 遗漏的三个实质合同

1. **跨 epoch 的 logical_key 去重不完整。** runner 只按候选 epoch、字面 `history` 和当前 `planning_epoch` 的确定主键查询，再辅以 `history` pending 索引与 de494 后 attempts rowid 尾部。候选本身要求“按 logical_key 比较所有 epoch”。因此，若相同 logical_key 存在于其它旧日期/自定义 epoch，且 attempt 位于 rowid 236094 之前或任务不是 `history` pending，runner 会漏检并可能重复调用。jobs.logical_key 没有可直接使用的前导索引，不能用这组有限查询声称完成了通用 cross-epoch duplicate gate。

2. **source manifest 与 intake 代码固定不完整。** runner 导入并使用 `backend/shared/tushare_intake.py` 的 `digest/json_bytes`，但 `CODE_SHA256` 没有固定该文件。它也只校验候选 JSON 的少数字段，没有逐项复核候选 `evidence.repository_pins`，没有验证 ce43 source manifest、opt_basic/opt_daily 的 observation/parquet 实体、官方归档 HTML，以及完整来源清单之间的 bytes/SHA/locator 关系。因此候选来源链不能仅凭 runner 的 candidate SHA 与部分生产文件 pin 视为完整复核。

3. **observation/result/parquet 证据链不完整。** runner 分别核验 raw object、observation 文件和可选 parquet 的物理 SHA，并读取 raw payload 检查 code/date/schema/key；但没有把 observation 内的 raw-object/result/parquet locator 与 `jobs.result` 做完整双向一致性核验，也没有从 raw response 独立重算并对账 result 的 status、HTTP、row_count、response_complete 等字段，且没有读取 parquet 实际内容核对 raw rows、列、行数、自然键及 observation 元数据。独立文件各自 hash 正确，不能替代整条 capture chain 的一致性证明。

## 后续边界

- `20260912T080238Z-opt-daily-one-call-runner-ready.md`、runner `abffa...` 和测试 `29a950...` 仅作为已发生执行的历史材料，不再作为下次执行模板或安全依据。
- 不用当前 runner 补跑或修复本次生产结果，也不发起新请求。
- `next_window` 应在只读、固定 CURRENT/config/code 和 exact task/attempt 身份下，从 canonical job 开始完整复核 raw object -> observation -> job/attempt result -> parquet 的 locator、bytes、SHA、内容与计数，并将本次结果纳入后续正常 fixed release 后再做 exact-reference 正控。
- 若未来需要通用 runner，应先提供覆盖所有 epoch 的可索引 logical_key 证据路径或固定库存，完整固定 intake/source manifests，并新增全链篡改负例；本记录不授权该实现或部署。
