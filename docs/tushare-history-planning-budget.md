# 历史规划预算与绝对游标

`Pipeline.plan_extended` 继续按冻结 signature 中的配置、标的、anchor 重建原生成器。历史 `offset` 仍为完整源序列的绝对位置，包括已略过的近期任务；没有迁移、重置或改变任务 identity。已有近期、历史 job 的 state、tries、result 通过原 enqueue 幂等语义保留。

历史每批 `plan_jobs_per_tick` 只计经过的 `epoch=history` 候选，包括已存在的候选。略过近期前缀仍增加 `planned`/offset，但不占历史候选预算；近期预算语义不变。`new_jobs + existing_jobs = planned - skipped_recent`。扫描停止不会置 done；只有实际到达源尾部才完成本次冻结枚举。缺依赖的有限空枚举仍保留 validation gap，不能据 done 声称数据完整。

每个历史 family 批次同时限制新经过源项：`history_plan_scan_limit` 默认 100000、允许 1–100000；`history_plan_seconds` 默认 1 秒、允许大于 0 且不超过 5 秒。返回 `stop_reason` 为 job_budget、scan_limit、time_limit 或 stream_end。这些吞吐参数不进入历史签名，也不修改 scope。每次候选前检查时间；这是协作式边界，不能中断同步生成器的单次 next、SQLite enqueue 或原有 islice 重放。旧 offset 重放仍为 O(offset)，深层游标的实际耗时上界并未解决，不宣称硬时限或生产 worker 加速。

专项测试复用旧 version1 冻结状态，从前缀前、前缀中、历史中及非零 offset 恢复；覆盖扫描/时间饱和、事务中断、已存结果保留、标的增长待下一快照、缺依赖、近期预算，以及 legacy 标量签名既有安全重放。两个旧测试改为同时核对源 offset 和目标预算，保留原唯一性与跨连接恢复断言。

隔离实测：6194 个合成合法证券代码（含 T600018.SH），原 technical_extra 生成器近期前缀 86737 项。冻结历史 offset=4000，一批经过其余 82737 项前缀并规划 500 条历史，offset=87237，约 0.10–0.12 秒；API/params 与原序列逐项相等，SHA256 `d13dc7f008d95cc7a05f9d78b446c0f488ac3252d1aa09c439cf8082c5728ecf`。旧预算该批只略过 500 项、产生 0 条历史。这是本地临时目录证据，不是线上容量估计。消费者优先级、组公平、PIT 及完整历史采集义务均未改变。

复跑（离线缓存已有依赖）：

```sh
PYTHONPATH=scripts UV_OFFLINE=1 uv run --python 3.10 --no-project --with httpx --with pyarrow --with duckdb python -m unittest scripts.test_tushare_history_budget scripts.test_tushare_planning_progress scripts.test_tushare_extended_pipeline scripts.test_tushare_technical_extra_pipeline scripts.test_tushare_global_pipeline scripts.test_tushare_risk_event_pipeline scripts.test_tushare_publish_interval
```
