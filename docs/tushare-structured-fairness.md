# Structured 消费公平候选（schema 6）

本改动只影响 `next_job` 实际选中 structured 时的内部次序，含其他组没有可运行任务时的跨组 fallback。外层 family 权重、账户限速、API 限速/观测冷却，以及其他组的 priority/rowid 次序保持原规则。

- 按 **实际 pending 任务**中的 API 名称稳定循环，不依赖当前配置的 API 白名单。新发现 API 可进入下一圈；不删除 legacy/未知 API。缺失或非字符串 API 明确报错并保留队列。
- 每个 API 独立保留四阶段：近期、近期、近期、历史。`epoch == 'history'` 为历史，所有其他 epoch（含旧 probe）为近期。优先桶没有已到重试时间的 pending 任务时借用另一桶；API 冷却跳过，不消耗该 API 的阶段。
- 每桶继续按 priority、rowid 排序。API 之间不再由单一低 priority 数值无限占先；已授权的 priority 24 研究切片仍在自身 API/桶内优先。
- 机会在实际预留请求时计入；后续失败、重试或权限拒绝不会退还机会。两桶均持续就绪时，每 API 的每四次预留有一次历史机会。这保证消费机会，不能证明成功数据吞吐或完成日期，也不替代历史任务的完整规划。
- `scheduler_state` 的 `structured_api_turn:<api>` 保存选择序号，`structured_phase:<api>` 保存独立阶段。与 account/API gates、family_turn 在同一事务提交；失败回滚全部预留，重开进程继续原阶段。API 身份不依赖会被 VACUUM 改变的隐式 rowid。
- 无 `requests_per_minute` 的原离线/legacy 入口继续不建立 gate，但实际返回 structured 时也执行同一轮转并持久 checkpoint。生产入口仍须设置原账户限速。

schema 6 仅在版本化事务中新增一个 pending 部分表达式索引：

```sql
CREATE INDEX jobs_ready_api_history
ON jobs(group_name,json_extract(job,'$.api_name'),(epoch='history'),priority)
WHERE state='pending';
```

API seek 与桶首项查询均使用该索引；不做每次全队列 DISTINCT/API 枚举。只在小型 scheduler_state 命名空间选最后一个 API。大量逐任务 `retry_after` 尚未到期时，桶查询仍可能访问多个候选；本次不增加第二套重试索引或改任务排序。外层既有 fallback 和全冷却等待查询也未改写，不能将最优合成查询耗时当作生产最坏时延。

迁移不改任何 jobs 内容/状态/tries/result/identity/rowid，不改 planning_state、历史 offset、capability、attempts 或已有 gate/checkpoint。旧程序仅接受 schema 0–5，会明确拒绝 6；应协调消费者升级。部署前在既有单写者维护边界，用 SQLite backup API 保存一致的 v5 备份并记录源版本/哈希；不直接拷贝正在写入的 SQLite 文件。备份用于诊断和灾难恢复，不能用旧 DB 覆盖升级后的新增采集进度。不得仅将 PRAGMA 降回 5 伪装回滚。若必须回退代码，需停写维护方案、审查并保留全部新增状态/数据后进行专门兼容处理，本候选不实施回退或生产迁移。

验证入口：

```bash
UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb \
  python -m unittest scripts.test_tushare_structured_fairness \
  scripts.test_tushare_queue_indexes scripts.test_tushare_extended_pipeline \
  scripts.test_tushare_partition_closure
```

全部测试在临时目录执行，禁上游网络/凭据。专项覆盖 4 API 独立 3:1（避免 API 数为 4 的倍数时相位锁死）、重开恢复、失败消耗、同事务回滚、冷却跳过、两向借桶、旧/新增 API、3:1:1 外组份额、跨组 fallback、迁移中断与逐行哈希不变。400,000 条 pending 队列会输出真实索引建立耗时/占用、EXPLAIN、VM 步数和选择耗时；这是机器相关的隔离证据。

尚未改变：历史 planner 的 API 顺序、未完成历史 offset/signature、各 API 完整日期范围及近期采集频率。消费公平解决“已入队历史没有机会”，不会自动提前尚未枚举的 daily_basic 历史；定向小切片和后续版本化 planner 迁移仍是独立议题。

本机一次实测（2026-09-09，400,000 pending）：索引构建 244.8 ms、11,210,752 bytes（约 10.7 MiB）；API seek 23 VM steps、桶首项 48 steps，无临时排序。52 次 helper+checkpoint 约 0.90 ms /17,700 steps。400k 全部 job 行迁移前后 SHA256 同为 `c97fd422438bd0cc6da8dff62678d1e89241ab6d7943f3b22e946bd87cbc59d5`。实际生产表大小、I/O、SQLite 版本与重试分布不同，部署需要重新记录迁移耗时。
