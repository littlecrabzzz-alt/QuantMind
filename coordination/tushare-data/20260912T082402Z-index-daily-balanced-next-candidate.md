# index_daily 下一批平衡候选：离线准备完成

- 时间、节点、任务：2026-09-12 08:24:02 UTC，Mac，`/root/queue_headroom_audit`
- 分支/worktree：`codex/tushare-index-daily-next-20260912`，`/private/tmp/quantmind-index-daily-next`
- 基线/提交：master `9fe4c38773b2710367ed25a532fdfe33fa83ca1e`；候选 `bb34cad7a97119ac3e84298d9215168fce607d52`
- 状态：纯离线代码、测试、固定发现证据和 blocked plan 已完成；没有 authority pristine 库存，因此没有生成、猜造或执行 360 个任务 ID
- 非动作：未读 token/凭据，未访问生产 DB 或上游，未改 authority、服务、队列、配置或发布状态

## 候选文件

- `scripts/prepare_tushare_index_daily_balanced_candidate.py`：18,965 bytes，SHA-256 `601eb3172e4c45c6bd667f976ddce483b4d4573ae9e7d85700b8a091723dff16`
- `scripts/test_tushare_index_daily_balanced_candidate.py`：8,928 bytes，SHA-256 `3e6eaa3b6b4e2d4748264e188add0c26dff447faaccd9e3fb3fc45910a38d5b5`
- `docs/tushare-index-daily-balanced-discovery-de494-20260912.json`：149,648 bytes，SHA-256 `83fed9546c91bb6a50478dbccac6fada230d11b1cca2efa8ff7488f8967fdc41`
- `docs/tushare-index-daily-balanced-next-plan-20260912.json`：3,273 bytes，SHA-256 `ba6a3bc489d23bf20f4bfe81ebb34eb3b3c734db2ebcbde3294d18aac2a3e031`

固定 Mac 镜像 `data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0` 的 manifest、CURRENT pointer 及每个引用 Parquet bytes/SHA 均在生成发现证据时复核。`index_basic` 的唯一供应商代码为 SSE 208、SZSE 485、CSI 8,011；CSI 源叶达到 8,000 行上限，全集仍不完整。固定版 `fut_basic` 另实证 720 个 CFFEX `.CFX` 代码；CFFEX 是 futures family，绝不进入 `index_daily`。CICC 没有固定非空证据，也不纳入。

离线选择器只接受 hash-pinned 的发现证据和 root 导出的 authority inventory。inventory 必须来自共享 pipeline lock 内的 query-only snapshot，固定 CURRENT/config/schema 6，且每条任务为 `history/structured/pending/tries=0/result=null/attempt_count=0`；完整 prior-plan reservation 清单也必须随库存提供。选择器重算 canonical job、logical_key 和 task ID，只选固定发现集合中的代码，并用 release-seeded 的三市场轮转生成最多 360 项；360 项必须 SSE/SZSE/CSI 各 120。输出固定 release、CURRENT pointer、config、发现/authority inventory、完整执行相关代码、reservation 和全部 task IDs，且保持 `publish=false`、`implicit_queue_allowed=false`。

## 验证

- 新增 6 个测试通过：三市场平衡、CFFEX 排除、reservation/attempt 拒绝、缺市场失败、输入/hash/task 身份与 360 上限、确定性/自校验、无网络/凭据/authority 路径。
- 既有 `scripts/test_tushare_index_daily_batch.py` 5 个测试继续通过。
- `py_compile`、`ruff check`、`ruff format --check`、`git diff --check` 均通过。

## root blocker 与下一步

root 需在不调用上游的共享锁窗口，create-only 导出 `docs/tushare-index-daily-balanced-next-plan-20260912.json` 所列 authority inventory 合同，至少提供每市场 120 个未保留 pristine 精确任务，并固定当前 config/CURRENT/task identities。若 CURRENT 已不再是 de494，停止使用本证据并从新固定版重建发现库存。

得到库存后，先在 authority 外运行纯离线构建：

```bash
python3 scripts/prepare_tushare_index_daily_balanced_candidate.py \
  --discovery docs/tushare-index-daily-balanced-discovery-de494-20260912.json \
  --discovery-sha256 83fed9546c91bb6a50478dbccac6fada230d11b1cca2efa8ff7488f8967fdc41 \
  --authority-inventory /tmp/index-daily-balanced-pristine-inventory.json \
  --authority-inventory-sha256 '<ROOT_REVIEWED_SHA256>' \
  --output /tmp/index-daily-balanced-next-candidate.json \
  --jobs 360
```

生成物仍是 `prepared_not_authorized_for_execution` 的候选 schema，不能直接交给现有 runner，也不授权采集。后续需独立复核 exact task 库存、代码/config/CURRENT pins 和新 schema 到正式 exact runner 的适配，再由 root 决定是否进入排空执行窗口。
