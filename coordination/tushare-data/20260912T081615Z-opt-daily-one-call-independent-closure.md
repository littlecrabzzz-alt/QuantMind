# opt_daily 单请求独立闭包

- 闭包时间：2026-09-12T08:14:16Z
- 审查时序：真实执行完成后进行的独立审查。
- 结论：严格只读闭包通过。共享锁内仅按精确 task PK 查询 job 和 attempts，SQLite 使用 `mode=ro`/`query_only`，持锁 0.000580 秒后关闭连接并释放锁。
- 任务：`4781e3570f46c97fd5afc0463a556eb1ee11f28845157d6d052a9f686f234f0b`，`epoch=20260912`，`state=done`，`tries=1`，唯一 attempt 为 1（rowid 241054）。
- 结果：HTTP 200、response complete、`sample_ok`、1 行；raw object、observation、assessment/result 和 Parquet 链路一致，Parquet 文件名哈希与文件 SHA 一致，13 个显式源字段逐值通过。本记录不复制原始行内容。
- 待下次正常发布的新引用：3 个（object、observation、Parquet），合计 7,538 bytes；它们均不在固定版 `data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0` 的 active files 中。
- 固定来源证据：候选中 opt_basic/opt_daily 共 6 个直接引用的物理大小、SHA、observation-object 链和 de494 manifest 包含关系均通过。

Authority create-only 证据：

- `validation/opt-daily-fixed-row-sample-independent-20260912T081416183184Z/independent-closure.json`：7,801 bytes，SHA-256 `c3ae6b8524e44547a98d2d495fc3486077229c98ed04910665e7c1010bab9ba0`
- `validation/opt-daily-fixed-row-sample-independent-20260912T081416183184Z/exact-refs-pending-next-release.json`：1,573 bytes，SHA-256 `d8c72d2eb0ef02f9ecb66d3cdb9aca4a3b3e4f222753f5118ddd5b5cd41bd71f`

`/tmp/run_tushare_opt_daily_one_call.py` SHA-256 `abffa078fbd6c8ea25519c0a0e6c62cad98edb5cba2c5a4f40e1e6b39a1e9f7a` 不可复用。其重复门未证明全 epoch 等价任务/旧 attempt 不存在，来源 pin 和执行前物理链校验不完整，且缺少硬截止时间。本闭包只证明选中 PK 当前有且仅有一个 attempt；不声称其他 epoch 中没有等价任务或 attempt。本次实际为 1 次 HTTP，未发生 `reuse_without_http`。

范围限制：`history_complete=false`、`historical_versions_complete=false`、`pit_verified=false`、`option_universe_complete=false`。
