# Mac Tushare 发布 attempt 文件校验并行化开始

- 当前唯一全量 worker PID 48264 正常运行，最近真实周期 778 次请求、2500 个文档任务，无失败阶段；本轮不触碰生产数据或运行配置。
- 上一次完整发布的 `scan_attempts_and_stat` 为 282.686 秒。当前约 74.6 万 attempt 对应约 190 万个 observation/object/parquet 元数据检查，路径几乎全部唯一，不能用简单去重省略。
- 候选保留全部文件 `stat`、确定性 manifest、缺文件失败和完整历史语义，只用有界批次及最多 8 个线程并行本地元数据检查。分支 `codex/tushare-publish-attempt-stat8-20260919`，独立 worktree 开发。
