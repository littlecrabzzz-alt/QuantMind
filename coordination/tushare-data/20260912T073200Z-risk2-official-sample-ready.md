# 风险事件两请求补证：执行候选

- 时间、节点、任务标识：2026-09-12 07:32 UTC，Mac，`/root/queue_headroom_audit`
- 状态：plan-only 候选完成；未执行上游，待 root 在自然排空窗口核准执行
- 输入：`backend/shared/tushare_risk_event_contracts.py`、registry、Pipeline/capture/rate policy、旧 `risk-event-probe` 台账、官方 452/453 页面
- 产物：`coordination/tushare-data/20260912T073100Z-risk2-official-sample-plan.json`；本机临时 helper `/tmp/run_tushare_risk2_official_sample.py`
- 未修改：authority、服务、配置、registry、coverage ledger、progress

## 固定请求

| API | params | fields | row cap | task ID |
|---|---|---|---:|---|
| `stk_alert` | `start_date=20260316,end_date=20260316` | `end_date,name,start_date,ts_code,type` | 1000 | `c4ef2d954567137de1c1b5431359ae03d5d0a32376f8a3750f7a827a6d78e81d` |
| `stk_high_shock` | `trade_date=20260312` | `name,period,reason,trade_date,trade_market,ts_code` | 1000 | `5c1f28116cbfff6104a8f2a997021e8b06f76b7b678398bdb540a58afbcd25dd` |

两项 required/nullable/positive 字段、row cap、group 和任务身份均由当前 `Pipeline.enqueue` 在隔离临时库实际生成并与 registry 核对。两页都要求 6000 积分、单次最多 1000 行；当前积分超过门槛，但不把积分门槛当账户授权。

旧证据不是同一窗口：`stk_alert` 旧三次为空，参数分别为 `trade_date=20260311`、同日加 `301373.SZ`、以及该代码 `20260310..20260312`；新请求是不带代码的 `20260316..20260316`。`stk_high_shock` 旧空请求为 `trade_date=20260904`，新请求为 `20260312`。旧报告 SHA256 为 `03335b6d...55f38`，固定版 `data-cc8ed219...db55`。

官方文档存在明确 `source_consistency_gap`：452 的代码示例请求 20260312，但展示行是其它日期；453 的代码示例请求 20260311，展示行同时含 20260316、20260313、20260311 等起始日。因此 20260316/20260312 只是官方样例种子。非空结果也不能自动启用，必须先逐行对账请求过滤和返回日期；空结果继续是 `empty_unverified`；权限错误才记 `permission_denied`。两者都不提升历史、修订或 PIT 状态。

## 执行门与命令模板

Manifest SHA256：`0b9f0fe197a70a90462aba30dc02da86ecbbba1d84a8bd59b1aa18eb725dc565`。Helper SHA256：`fa2f660bbdc5fc4722b6590ce0941f12f3c8e2f7ea37f0d87521334afb1d7c25`。Helper 默认只做断网 plan；`--execute` 才访问 authority/凭据/上游。

下列模板中的 `TUSHARE_CONTAINER` 由 root 填为已部署普通 Tushare 业务容器。先确认普通 worker/Beat 已自然排空、publisher 已成功、代码同步完成；把 helper 复制到容器后再次核对其 SHA。部署版只要与 manifest 中任一源码 SHA 不同，helper 会拒绝，必须基于部署版重新生成或明确复核，不能删掉 hash 门。

```bash
export TUSHARE_CONTAINER='<ordinary-tushare-container>'
sudo -n docker cp /tmp/run_tushare_risk2_official_sample.py "$TUSHARE_CONTAINER:/tmp/run_tushare_risk2_official_sample.py"
sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /tmp/run_tushare_risk2_official_sample.py

config_sha=$(sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /data/tushare/pipeline-config.json | awk '{print $1}')
current_sha=$(sudo -n docker exec "$TUSHARE_CONTAINER" sha256sum /data/tushare/CURRENT.json | awk '{print $1}')

sudo -n docker exec -w /app "$TUSHARE_CONTAINER" python3 -B /tmp/run_tushare_risk2_official_sample.py \
  --manifest /app/coordination/tushare-data/20260912T073100Z-risk2-official-sample-plan.json \
  --manifest-sha256 0b9f0fe197a70a90462aba30dc02da86ecbbba1d84a8bd59b1aa18eb725dc565 \
  --execute \
  --root /data/tushare \
  --expected-config-sha256 "$config_sha" \
  --expected-current-sha256 "$current_sha" \
  --report /data/tushare/validation/risk2-official-sample-20260912.json \
  --receipt /data/tushare/validation/risk2-official-sample-20260912-receipt.json \
  --max-seconds 45
```

执行路径仅调用 `Pipeline.enqueue` 和 `Pipeline.run(task_ids=...)`：共享 account/API gate、tiered rate 解析、已观察 quota cooldown、`capture_sample`、normalize、attempt、不可变 object/observation/Parquet 都走现有语义；最多两个 upstream calls，不改配置、不发布、不自动启用。它还要求 exclusive `pipeline.lock`、schema v6、100 GiB 余量、固定 config/CURRENT、全新或 pristine 的两个任务及 create-only 报告/receipt。

## 离线验证

```bash
python3 -m py_compile /tmp/run_tushare_risk2_official_sample.py
python3 -B /tmp/run_tushare_risk2_official_sample.py \
  --manifest coordination/tushare-data/20260912T073100Z-risk2-official-sample-plan.json \
  --manifest-sha256 0b9f0fe197a70a90462aba30dc02da86ecbbba1d84a8bd59b1aa18eb725dc565
```

结果：通过；输出 `status=plan_only`、两个固定 job，且 `would_access_authority/credentials/call_upstream/publish` 全为 false。
