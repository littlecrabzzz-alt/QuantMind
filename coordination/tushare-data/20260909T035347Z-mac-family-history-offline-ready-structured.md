# Mac 历史公平队列 14 观察固定版离线验收

- 节点/任务：Mac，structured 子任务，完成；仅 `/tmp` helper/report 和本条记录，无 runtime 修改、HTTP、云端访问、同步触发、CURRENT 改写、旧数据库访问。
- 输入：`/tmp/tushare-family-fairness-after4-20260909.json`，标准 mirror exit0 报告 `/tmp/tushare-family-history-mirror.json`。固定 release `data-86aebb78840094da306bdb92aaa89876e199f55733c727a9e1068927869a63e4`，从 mirror 报告选择，未读取 CURRENT。
- 验证：14 observations + 14 raw + 2 Parquet 共30目标路径全部进入该 manifest，原证据/manifest/本地字节 SHA 和大小一致；12空响应保留。为多版本独立预期，额外仅读 CYQ 全部144相关parts及其原始观测，累计456文件校验，未扫描整个存储。
- `cyq_perf` 000001.SZ / 20180101–31：22源行，11源列；73固定parts共118行纳入独立latest-key预期。`cyq_chips` 同scope：3586源行，4源列；71固定parts共14066行纳入预期。每行原始字段/null、source_ts_code、SZ000001规范码、完整原行SHA identity均对账。两接口实际离线reader最新与观测时刻as_of均为22/3586行，早于目标观测1微秒均0行，与全相关parts独立去重预期一致。socket/DNS及SQLite connect阻断，upstream_calls=0。执行3.911秒。
- 报告 `/tmp/tushare-family-history-offline-verified.json` SHA256 `7e0b49a2fd62c230792d67a3f3b45df68b15c59184209fc1ecf323a8a8157be8`；helper `/tmp/tushare-family-history-offline-verify.py` SHA256 `eefdf5a31ebaf050fae6af31601c5f3d0fc4bf3b21f23a0f6479cbe3b018ec19`；源码HEAD/reader SHA写入报告。
- 重跑：`uv run --offline --no-project --python 3.10 --with httpx --with pyarrow --with duckdb python /tmp/tushare-family-history-offline-verify.py`，固定根为用户 Application Support/QuantMind/tushare，180秒硬限。
- 边界：verified_sample_only，不表示全历史/RRG/PIT完成；空响应不证明节假日或历史不存在，as_of只证明本系统观察时间；后续新增采集未在本轮声称已到Mac。无生产调用/启用，归属释放。
