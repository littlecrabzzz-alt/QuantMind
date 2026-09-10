# RRG ETF 正式采集批次准备

`prepare_tushare_rrg_acquisition_batch.py` 把已核验的 ETF 全窗口审计转换为确定性、可分片的 Tushare Pipeline 任务，但不连接上游、不读取 Token、不打开正式 `pipeline.sqlite`，也不入队或发布数据。

入口要求显式传入 `report.json` 及 SHA256，并复核同目录 `manifest.json` 中的 `collection-plan.jsonl` 哈希。每一行先经过本批次策略及接口参数校验，再在临时隔离的 `backend.shared.tushare_pipeline.Pipeline` 中调用 `enqueue` 生成正式合同字段、`logical_key` 和 `task_id`。临时 SQLite 随运行结束删除，不会复制成正式采集状态。

默认只准备：

- `fund_div`：逐个窗口内 ETF 的 `ts_code` 请求，固定 `history` epoch。Pipeline 的 `empty` 只证明该任务完成并返回 0 行；不能解释成历史上从未分红，也不能排除后续修订。
- `etf_limit`：2022-09-01 至 2026-09-01 的 49 个自然月窗，固定 `history` epoch。接口行或空结果都是价格上下限采集证据，不证明停牌、开盘竞价可成交或 PIT。

1,888 个 `fund_daily` 缺价诊断范围默认排除；只有显式传入 `--include-price-diagnostics` 才会生成低优先级任务，且 0 行仍保持未分类、禁止补价。5,774 个 PCF 任务无论是否打开诊断开关都拒绝进入批次，因为当前 ETF 行业映射不是权威历史 PIT 映射。

```bash
UV_OFFLINE=1 uv run --offline --no-project \
  --with httpx --with pyarrow --with duckdb \
  python -B scripts/prepare_tushare_rrg_acquisition_batch.py \
  --audit-report /tmp/quantmind-rrg-etf-window-audit-20260910T0445Z/report.json \
  --report-sha256 74d6798cab10c1ead48eca23927a511bd7192c882c8855c20b1df8f4737e1fe6 \
  --output /tmp/quantmind-rrg-acquisition-prep-new \
  --shard-size 250
```

输出的 `batch-manifest.json` 固定原 release、报告/计划哈希、选择与排除数量、空结果语义和每个分片哈希。`shards/*.jsonl` 每行包含原 API 参数、Pipeline 任务标识、epoch、优先级、分组和完整 job；分片大小限制为 1—1,000。

正式执行时不能把这些行直接写入 SQLite。经另行授权后，云端 authority 入口应逐分片调用同一 `Pipeline.enqueue`，核对返回的 `task_id`，再由现有 worker 使用共享限流、权限门、不可变原文和失败恢复机制处理。重复导入相同合同、参数和 epoch 会得到相同任务 ID。全部终态及分区缺口核对后才能通过现有 publisher 产生新固定 release；旧固定输入不自动切换。当前实现刻意没有 authority-side apply 开关。

## 2026-09-10 实际准备结果

基于 `data-03885aef45ce7be5ce812f4305734a7c8852646a09cfa567383215d10e5f6d22` 的审计计划，默认批次生成 1,767 个任务：1,718 个 `fund_div` 和 49 个 `etf_limit`。250 行分片得到 7 个分红分片和 1 个涨跌停分片，总计约 1.18 MB。

批次位于 `/tmp/quantmind-rrg-acquisition-prep-20260910T0540Z`，`batch-manifest.json` SHA256 为 `3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81`。用相同输入在独立目录重跑，清单和全部分片逐字节一致。9 个相关专项测试及 Ruff 通过。机器摘要见 `tushare-rrg-acquisition-preparation.evidence.json`。
