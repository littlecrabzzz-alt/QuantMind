# QuantDB PG 修复验证通过，进入共享发布窗口
- 节点 Mac，候选提交 `7b5dcea5`，分支 `codex/quantdb-pg-memory-20260926`；本任务负责本次主分支合并及云端 quantmind / quantmind-celery 的相关加载更新。
- 未改 Qlib/RD/Binance 文件；已查 Binance 主题仍为独立候选开发，无重叠发布记录。其他研究 worker、Mac 研究任务不重启。
- 11 项离线检查通过：新旧数值一致、复权口径、幂等、跨读取块的标的边界、重复源行拒绝、第二页 PG 失败整批回滚。
- 实际固定输入 `snapshot-quantdb-20260925T211728455924Z`，只读挂载；隔离容器 network=none、memory=1536 MiB、swap=1536 MiB、CPU=1。处理 5572 标的、38966 输出行、7 交易日；每次 Pandas 最多 117 行。RSS 峰值 497.06 MiB，容器记录峰值 490409984 字节，229.64 秒完成。逐日行数及 5 个代表标的 close/ma60 独立比对通过。
- 详细本机证据：`/tmp/quantmind-pg-memory-20260926/real-input-validation.json`。测试没有写入业务数据库。
- 云端 active/reserved/scheduled 为空，daily_sync 锁空闲；Qlib 当前 9/23、348876546 字节。
- 恢复范围：先备份 `stock_daily_latest` 9/16–24 完整行及当前 Qlib 目录，再通过既有 fill_pg_from_parquet / update_qlib_cache 补派生数据。PG 使用批次事务，Qlib 复用校验后原子发布；固定研究输入保持原样。恢复期间持有既有 daily_sync 和 Qlib 构建锁。
