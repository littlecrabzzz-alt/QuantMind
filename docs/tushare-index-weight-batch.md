# Tushare `index_weight` 精确补采批次

`index_weight` 提供指数成分及权重，字段为 `index_code`、`con_code`、`trade_date` 和 `weight`。它可支持指数复现与成分研究，但供应商返回的 `trade_date` 不等于可验证的首次发布时间；当前数据没有 `known_at`，不能据此证明任一历史回测在当时已经知道这份权重。

2026-09-10T11:50Z 对云端 schema 6 权威队列做了只读审计。运行时 capability 为 `available`；当前 10100 积分下，分层限速把该常规接口解析为 500 次/分钟，仍受 500 次/分钟账户总闸门约束。真实队列状态如下：

| 范围 | empty | pending | split_pending | pending 指数数 | 请求边界 |
|---|---:|---:|---:|---:|---|
| 全部 epoch | 312 | 96,849 | 90 | 9,551 | 1990-01-01—2026-09-08 |
| `history` | 1 | 87,497 | 90 | 199 | 1990-01-01—2026-09-01 |
| `20260909` 近期 | 310 | 9,352 | 0 | 未作为本批分母 | 2026-09-02—2026-09-08 |

该次审计中，历史 planner 只为 145 个 `.SH` 和 54 个 `.CSI` 指数生成了历史队列；`.SZ` 等后缀目前只有近期任务。持续 planner 在 12:00Z 生成候选时又加入 1 个 CSI 指数，候选快照来源变为 87,870 项、200 个指数。这种增量正说明当前队列不是完整指数全集。9,551 个 pending 指数来自当前已发现记录，也不能证明供应商指数全集完整。1990-01-01 是配置请求起点，不是供应商可用历史下界。

已发生 402 次真实请求：312 次空响应，90 次 `possibly_truncated`。90 个饱和请求均为 `000001.SH` 的月区间，时间从 2019-03 至 2026-08，单次 1,493—2,251 行；它们已各生成两个日期子任务，但父分区仍为 `gap`。合同的 1000 行上限尚未实测确认为硬上限；一个指数的单日请求若仍饱和，因为接口没有 `con_code` 入参，不能继续按成分拆分，也不能宣称覆盖完整。

## 固定候选

`prepare_tushare_index_weight_batch.py` 在一个 SQLite 只读事务中只选择现有 `history`、`market`、`pending` 任务。它先给每个已规划指数取最新任务，再按供应商代码后缀交错选择第二轮，防止 SH 指数长期挤占 CSI 指数。它不创建任务、不读取凭据、不调用上游。

```bash
python3 scripts/prepare_tushare_index_weight_batch.py \
  --root /data/tushare \
  --output /tmp/tushare-index-weight-batch.json \
  --batch-jobs 360
```

本次真实权威清单包含 360 项、200 个指数：40 个指数各 1 项，160 个各 2 项；250 项为 SH，110 项为 CSI；请求窗口覆盖 2026-08-01 至 2026-09-01。清单 190,398 字节，SHA256 为 `526027196072ab9d51a6303de81cdfcdcadcb09d0b6c742ac0dda89fb00923c1`，任务集合 SHA256 为 `8342c8d55a5b642608d5316f99256297893a758d09b9b2759459c46f1c4ae784`。

`run_tushare_index_weight_batch.py` 默认只做离线清单校验，输出明确为 0 authority、0 凭据、0 网络。生产执行还要求显式固定任务集合、当前配置和运行器 SHA256；执行前核对 authority、schema 6、`ENABLED`、共享非阻塞锁与 100 GiB 磁盘余量。它复用 Pipeline 的分层账户/API 限速、原始响应留存、规范化、重试与日期二分，只运行固定 task ID，最多 360 次或 90 秒，不做全局 planner 扩展，不发布、不切换 `CURRENT`。

```bash
python3 scripts/run_tushare_index_weight_batch.py \
  --manifest /read-only/tushare-index-weight-batch.json \
  --manifest-sha256 526027196072ab9d51a6303de81cdfcdcadcb09d0b6c742ac0dda89fb00923c1
```

离线 plan-only 校验得到运行器 SHA256 `c210a1d1cc48e4607c82d880649bffa389dfe4cb713c77b2a36df3f2e7f758cf`。实际执行时还要固定当时的 authority 配置 SHA，且若普通 worker 已处理部分任务，执行器只处理仍为 pending 的成员，不会重放已完成请求。

按 500 次/分钟，360 次理论下限为 43.2 秒；近期三大财务表精确批次为 48.807 秒。指数权重响应更宽且可能触发日期二分，因此首次验收按 45—90 秒估算，以 90 秒硬边界为准。90 个既有非空样本的原始对象、观察和 Parquet 合计中位数约 167 KiB，P95 约 187 KiB；按 360 个非空响应外推约 59—66 MiB，连同 SQLite/WAL 和分区元数据按 100 MiB 预留。固定版本发布与 Mac 镜像不属于本批耗时或空间估算。

本候选只扩大可复核的原始指数权重数据。`known_at`、指数发现全集、历史下界和单日饱和闭包继续保持未验证，不能据此解除 PIT 或研究 `blocked_data`。
