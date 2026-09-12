# 风险事件两请求补证：v2 执行候选

- 时间、节点、任务标识：2026-09-12 07:36 UTC，Mac，`/root/queue_headroom_audit`
- 状态：完成，待 root 在已排空的 quota 部署窗口执行
- 更正：接续 `20260912T073200Z-risk2-official-sample-ready.md`；旧 manifest 保留，执行改用 v2
- 未修改：authority、服务、配置、registry、coverage ledger、progress；未调用上游或读取凭据

复审后仅收紧执行 helper 的观测范围，没有改变 dispatch、gate、capture、normalize、attempt 或归档路径：

- read-only SQLite schema introspection 使用 `timeout=2` 和 `PRAGMA busy_timeout=2000`。
- `Pipeline.run(task_ids=...)` 的实例级最终 `status()` hook 改为 `exact_task_scope JOIN jobs ON primary key` 后只聚合两个指定任务，避免原 `Pipeline.status()` 对生产全量 jobs 做 `GROUP BY`。
- 新 manifest 固定 quota 候选 `fda4655d085235bda19227ec0b3ebe2fdca4d921` 的 `tushare_rate_policy.py` SHA `83b9e6ad...95fa8`，并新增 `tushare_daily_quota.py` SHA `b3673104...6e75`。其它 registry、Pipeline、intake、risk contract 和 catalog pin 保持不变。

执行产物：

- v2 manifest：`coordination/tushare-data/20260912T073500Z-risk2-official-sample-plan-v2.json`
- manifest SHA256：`209f61621761aadf5674a65e1bcb09523ecaee853ce31d6bb6318ddd2387c096`
- 临时 helper：`/tmp/run_tushare_risk2_official_sample.py`
- helper SHA256：`609eb46aa881baf9f00ab0b351b7d61c6e9f4fd207c0b13dbda953be8b650330`

请求仍严格为：

1. `stk_alert(start_date=20260316,end_date=20260316)`，fields `end_date,name,start_date,ts_code,type`，row cap 1000。
2. `stk_high_shock(trade_date=20260312)`，fields `name,period,reason,trade_date,trade_market,ts_code`，row cap 1000。

旧空请求排除和 `source_consistency_gap` 边界不变：alert 旧窗口为 20260311 及带代码的 0310..0312，high-shock 旧窗口为 20260904；官方页面的示例请求与结果日期不一致。任何非空结果都只算这次 bounded observation，不自动 enable，也不证明 filter/history/revision/PIT。

部署版核对所有 manifest source pins、helper SHA、config SHA 和 CURRENT SHA 后，执行模板为：

```bash
export TUSHARE_CONTAINER='<ordinary-tushare-container>'
sudo -n docker cp /tmp/run_tushare_risk2_official_sample.py "$TUSHARE_CONTAINER:/tmp/run_tushare_risk2_official_sample.py"
sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /tmp/run_tushare_risk2_official_sample.py

config_sha=$(sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /data/tushare/pipeline-config.json | awk '{print $1}')
current_sha=$(sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /data/tushare/CURRENT.json | awk '{print $1}')

sudo -n docker exec -w /app "$TUSHARE_CONTAINER" python3 -B /tmp/run_tushare_risk2_official_sample.py \
  --manifest /app/coordination/tushare-data/20260912T073500Z-risk2-official-sample-plan-v2.json \
  --manifest-sha256 209f61621761aadf5674a65e1bcb09523ecaee853ce31d6bb6318ddd2387c096 \
  --execute \
  --root /data/tushare \
  --expected-config-sha256 "$config_sha" \
  --expected-current-sha256 "$current_sha" \
  --report /data/tushare/validation/risk2-official-sample-20260912.json \
  --receipt /data/tushare/validation/risk2-official-sample-20260912-receipt.json \
  --max-seconds 45
```

离线验证：在 `/private/tmp/quantmind-cyq-chips-daily-quota` 运行 helper 的 v2 plan-only；py_compile 通过，输出两项固定 job，且 authority/credentials/upstream/publish 四项均 false。
