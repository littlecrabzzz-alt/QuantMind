# 基金净值历史精确批次

本批只处理已经存在于云端权威队列的 `fund_nav` 历史任务。它先处理已有拆分树的 pending 叶子，再处理未拆分历史根；不创建新任务，不按基金状态或生命周期裁剪请求窗口。净值修订、首次可知时间和基金全集仍是独立的数据质量边界。

## 只读生产快照

2026-09-10T11:42Z 从 schema 6 的 `/data/tushare/pipeline.sqlite` 读取到 52,570 个 `fund_nav` 任务，范围为 1990-01-01 至 2026-09-09：

| epoch | 状态 | 任务 | 基金代码 | 请求窗口 |
|---|---|---:|---:|---|
| `history` | done | 49 | 49 | 1990-01-01 至 2026-09-01 |
| `history` | pending | 22,207 | 22,156 | 1990-01-01 至 2026-09-01 |
| `history` | split_pending | 51 | 51 | 1990-01-01 至 2026-09-01 |
| `20260909` | done / empty / pending | 2 / 299 / 21,904 | 2 / 299 / 21,904 | 2026-09-02 至 2026-09-08 |
| `20260910` | pending | 8,057 | 8,057 | 2026-09-03 至 2026-09-09 |
| 权限探针 | done | 1 | 1 | 2026-09-02 至 2026-09-08 |

51 个历史根因单次达到 1,000 行上限而标记 `split_pending`，已经形成 102 个 `date_bisection` 子任务；父任务继续保留 `child_not_verified`，只有所有后代终态才能证明请求窗口闭合。本候选固定这 102 个 pending 子任务，并补充 258 个未拆分历史根，共 360 个任务、309 个基金代码。

当前 capability 为 `fund_nav:` / `available`，最近检查时间为 2026-09-10T11:39:22Z。真实回执有 52 次 `sample_ok`、51 次 `possibly_truncated` 和 299 次 `empty_unverified`；成功非空回执证明当前 Token 可以调用该接口，空响应不证明无历史。冻结的官方权限证据将它归为 2,000 积分可用的常规接口；10100 积分时为 500 次/分钟，2026-12-05 后预计 8100 积分时仍在 500 次/分钟档。生产配置为 `tiered_v1`、账户 500 次/分钟，配置 SHA256 为 `4ac7b38142097cda4af50dfadb00093fd635d5fd37859d68ee9632800d1e21d9`。

## 基金全集与生命周期边界

当前不可变 `fund_basic` 响应合并后有 22,216 个代码，其中场内 2,945、场外 19,271；`fund_nav` 已规划 22,205 个代码。两边并未闭合：

- `fund_basic` 有而 `fund_nav` 未规划的 13 个代码：`002211.OF`、`028715.OF`、`028716.OF`、`028760.OF`、`028761.OF`、`028891.OF`、`028892.OF`、`028893.OF`、`028894.OF`、`029016.OF`、`519324.OF`、`519325.OF`、`588490.SH`。
- `fund_nav` 已规划但当前 `fund_basic` 合并集没有的 2 个代码：`158038.OF`、`159070.OF`。
- 22,216 个基础记录中只有 2,778 个带 `list_date`、4,936 个带 `due_date`、626 个带 `delist_date`。生命周期字段缺失时不能推断请求窗口外为空，也不能从当前状态反推历史存续状态。

候选清单保存上述两个全集的计数与排序代码哈希，并为所选 309 个基金保存当次可见的生命周期上下文。任务中的 1990 起点和结束日期保持原样；上下文不参与筛选，因此不会把基金状态或缺日期误当成覆盖证明。

`fund_nav` 的唯一键含 `ts_code`、`nav_date`、可空的 `ann_date`。源端可能在相同键上修订数值；原始响应和观察标识必须继续不可变保存，下游研究需固定 `release_id` 和观察版本。`_fetched_at` 只证明系统抓取时间，`ann_date` 为空或有值都不能单独证明数据首次对市场可知的时间，因此本批不会把结果标为 PIT 完整。

## 固定候选与执行边界

候选文件为 `docs/tushare-fund-nav-batch-20260910.candidate.json`，大小 277,956 字节：

- manifest SHA256：`ce4f8bbfca7be9e8ea9a7ab028b77286acec7eb61586ad9da70dff3b961fcbc8`
- 任务集合 SHA256：`7fc790ecc6f8975f5820c974dd8a9d7ae4e0d5d1c4b1e6a54c9ecb074a26c1be`
- 准备器 SHA256：`a4a4320a361cb710fb8fe6d91b0d4f6075d1a01e8c3dd8df2adbebccc27ba26e`
- 执行器 SHA256：`5fa32b52871722d8ab6c74e999f442d201a4cbef2b7f081228697148c7f7fe89`
- 来源固定版本：`data-4c12ba6d74691859358234f6aa34c7202eb3b2c90f3b04aa89eb64bac763bfe3`

准备器以 SQLite 只读模式运行，输出必须位于 authority 外；默认运行器只验证 manifest，离线计划结果明确为 0 authority、0 凭据、0 上游、0 发布。生产执行额外要求任务、配置、准备器和执行器 SHA256 全部匹配，所有任务仍为 pending，并通过 authority、schema 6、`ENABLED`、非阻塞 `pipeline.lock` 和 100 GiB 空闲空间检查。它复用现有账户/API 限速、不可变原始响应、标准化和拆分逻辑，最多 360 次请求或 90 秒；exact scope 不运行全局扩展和发布，执行前后还会核对 `CURRENT` 未改变。

```bash
python3 scripts/run_tushare_fund_nav_batch.py \
  --manifest docs/tushare-fund-nav-batch-20260910.candidate.json \
  --manifest-sha256 ce4f8bbfca7be9e8ea9a7ab028b77286acec7eb61586ad9da70dff3b961fcbc8
```

审核通过并自然排空相关 worker 后，生产执行还需显式提供：

```bash
python3 scripts/run_tushare_fund_nav_batch.py \
  --manifest docs/tushare-fund-nav-batch-20260910.candidate.json \
  --manifest-sha256 ce4f8bbfca7be9e8ea9a7ab028b77286acec7eb61586ad9da70dff3b961fcbc8 \
  --expected-task-ids-sha256 7fc790ecc6f8975f5820c974dd8a9d7ae4e0d5d1c4b1e6a54c9ecb074a26c1be \
  --expected-config-sha256 4ac7b38142097cda4af50dfadb00093fd635d5fd37859d68ee9632800d1e21d9 \
  --expected-helper-sha256 5fa32b52871722d8ab6c74e999f442d201a4cbef2b7f081228697148c7f7fe89 \
  --expected-preparation-sha256 a4a4320a361cb710fb8fe6d91b0d4f6075d1a01e8c3dd8df2adbebccc27ba26e \
  --root /data/tushare \
  --max-requests 360 \
  --max-seconds 90 \
  --execute
```

500 次/分钟下 360 次的限速理论下限为 43.2 秒，生产验收保留 90 秒硬上限。现有 51 次饱和样本的原始 JSON 加 Parquet 平均约 186 KiB，按 360 次估算约 67 MiB；按观测单次最大值外推约 136 MiB，首批连同 SQLite 与拆分元数据按 200 MiB 预留。审计时云端空闲 153,100,898,304 字节，超过 100 GiB 停采线。全量历史仍会继续递归拆分，22,207 个当前 pending 只是调用下界，不能据此给出最终时长或容量承诺。

## 生产执行

2026-09-10 第一次执行在任何上游请求前拒绝旧候选，因为候选冻结后常驻 worker 已完成其中少量任务。该拒绝记录为 `/data/tushare/validation/fund-nav-batch-20260910/acceptance.json`，上游调用0，SHA256 `21a0e6d8ac6f5fd5cc4a21cab76b5a4c8ca57371836e57cd8dd67c63db04469c`。

排空后从权威库重新固定360项当前任务，新清单 SHA256 `05b263c19d15f73494a08452966332a38734b18baaf7719301ead8949cdd3016`，任务集合 SHA256 `f8918c3373c87cced86c5aadb64a38e5f171a6fc1c9788c2fabf27854c48755e`。真实执行在49.349秒内完成360次 `fund_nav` 请求：165个 `done`、53个 `empty`、142个 `split_pending`。执行中 `CURRENT` 和生产配置均不变；有效收据 `acceptance-v2.json` SHA256 为 `d41683b40e8c4b9482f72c44e3da2e7bb80cffb4d0680e21571458966bb5d564`。该结果同样已进入 `data-3eee75afb22ae4bea72b9ac5826e6bea6b7d98f0f2e600adfd1b04f11677c2e1` 并追平 Mac。
