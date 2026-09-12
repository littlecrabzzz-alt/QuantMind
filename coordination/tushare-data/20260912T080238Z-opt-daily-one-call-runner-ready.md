# opt_daily 单请求固定样例 runner：待 drained window 执行

- 时间、节点、任务：2026-09-12 08:02:38 UTC，Mac，`/root/queue_headroom_audit`
- 状态：runner 与离线测试已完成；仅供 root 在已自然排空的服务窗口审查后执行
- 本轮未访问云端 authority、凭据或上游，未改服务、配置、registry、coverage ledger 或发布状态

## 固定输入与执行边界

- 已提交候选：`coordination/tushare-data/20260912T075159Z-opt-daily-fixed-row-sample-candidate.json`，7,828 bytes，SHA-256 `e1712d95174459913646f6a8f5b24241d88842a75e02ed865b5f8fa21be7560d`，提交 `21c49a2d842101f50646f79bd853b530a956f6b6`
- 请求：`opt_daily(ts_code=HO2609-C-2500.CFX, trade_date=20260911)`，fields `amount,close,exchange,high,low,oi,open,pre_close,pre_settle,settle,trade_date,ts_code,vol`，row cap 15,000
- 候选 epoch task ID：`1a19f7cd61271ffbfaa08476c742fab3e3fbf0d9cb31396d64e94cafe7ee6c93`
- history task ID：`3ac3e980258b60ed1df1c12805c0fde768f3e0ded33d7b66e6ee778476b1e63f`
- 代码固定：`d61e93d62380afcc221369ebc317a138d0e8cc9a`；runner 内逐文件固定 Pipeline、rate policy、daily quota、registry、other contract 和 catalog SHA
- CURRENT 固定：`data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0`；pointer SHA-256 `d47619bf57d327539914694cfdeb0724f7474cbdec02d953357f2a7c9a2ea0bc`
- attempts 下界：de494 已纳入的 cyq attempt rowid `236094`；runner 校验其 `(job_id,attempt)` 身份后只检查其后的至多 10,000 行
- 上游预算：最多 1 请求、30 秒；不自动 enable、不改配置、不发布；任何非空结果仍只证明该代码和日期的一次 observation，不证明历史完整、版本完整、PIT 或期权全市场覆盖

## Runner 和离线验证

- runner：`/tmp/run_tushare_opt_daily_one_call.py`，31,011 bytes，SHA-256 `abffa078fbd6c8ea25519c0a0e6c62cad98edb5cba2c5a4f40e1e6b39a1e9f7a`
- 测试：`/tmp/test_tushare_opt_daily_one_call.py`，4,467 bytes，SHA-256 `29a950cc2265313677cfe53d1731e09c9a92e2f4f7c29ce17ac26f6d90f0a8d3`
- `py_compile`、`ruff check`、`ruff format --check` 均通过；4 个 SQLite 合成测试通过：无重复时使用候选、history pristine 复用、watermark 后已有 attempt 零 HTTP 复用、合同漂移 pending 阻断
- plan-only 通过并确认 authority、凭据、上游、publish 四项均为 false

重复门不会对全量 jobs/attempts 做无索引扫描。它按候选/history/当前 planning epoch 的确定 task ID 走 jobs 主键，另以 `jobs_ready_api_history(api_name,state,priority,id)` 约束已有 history pending，并从 rowid 236094 后的小尾部连接 jobs 主键检查新 attempt。已有等价 attempt 只归档复用结果且调用数为 0；已有 pristine pending 复用该 task；多条、合同漂移、索引缺失、查询超时或 watermark 不一致都阻断。

`Pipeline.run` 只接收选中的单 task ID；实例级 `status()` 也只按该主键聚合。HTTP、账户/API gate、rate policy、daily quota、capture、normalize、attempt 与 immutable object/observation/parquet 路径仍使用正式 Pipeline。归档前复核 code/date、显式 schema、自然键唯一、response_complete 和物理文件 bytes/SHA。report/receipt 只能 create-only 写入 authority 的 `validation/`，互不重名，完整归档在独占 pipeline lock 内完成。

## 审查后执行模板

```bash
export TUSHARE_CONTAINER='<ordinary-tushare-container>'
sudo -n docker cp /tmp/run_tushare_opt_daily_one_call.py "$TUSHARE_CONTAINER:/tmp/run_tushare_opt_daily_one_call.py"
sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /tmp/run_tushare_opt_daily_one_call.py

config_sha=$(sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /data/tushare/pipeline-config.json | awk '{print $1}')

sudo -n docker exec -w /app "$TUSHARE_CONTAINER" python3 -B /tmp/run_tushare_opt_daily_one_call.py \
  --candidate /app/coordination/tushare-data/20260912T075159Z-opt-daily-fixed-row-sample-candidate.json \
  --candidate-sha256 e1712d95174459913646f6a8f5b24241d88842a75e02ed865b5f8fa21be7560d \
  --execute \
  --root /data/tushare \
  --expected-config-sha256 "$config_sha" \
  --expected-runner-sha256 abffa078fbd6c8ea25519c0a0e6c62cad98edb5cba2c5a4f40e1e6b39a1e9f7a \
  --report /data/tushare/validation/opt-daily-fixed-row-sample-20260912.json \
  --receipt /data/tushare/validation/opt-daily-fixed-row-sample-20260912-receipt.json \
  --max-seconds 30
```

执行前仍需由 root 确认普通 worker/Beat 保持自然退出、Redis queue/unacked 为空、没有活跃 writer，且 CURRENT 仍是 de494；runner 自身还会用独占非阻塞 pipeline lock、100 GiB 余量、config/CURRENT/code/helper SHA 再次硬门控。若此前等价 attempt 已存在，输出 `reuse_without_http` 的归档证据而不会再调用上游。
