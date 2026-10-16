# 标识发现索引已部署
- 3d0cf857 已合入 master 并 push；云端 Git 元数据已快进。最后完整 handoff 只因本地 API 恰在 QuantDB 自动刷新停机窗口而失败，待刷新结束再核对。
- 只在 backend/shared/tushare_pipeline.py 增加两项事务索引 jobs_discovery_api / attempts_discovery_api，不改表/记录/user_version=6，批处理 v6 检查保持兼容。测试及 docs/tushare-mac-source.md 同步更新。
- 冻结库 APFS 隔离副本上，索引前后 stocks 的 94 条、dc_indices 的 9045 条 SQL 结果逐字节哈希一致。查询计划由 SCAN 改为 SEARCH；时间含缓存差异，不用作整轮速度倍数承诺。
- 70 项队列/发现/分区/兼容测试 + 32 项批处理兼容测试通过。测试包括失败回滚、重启幂等、历史尝试保留及低 VM 步数索引查询。
- 排空旧采集 PID 12142 后升级到 PID 15419；pipeline 代码 SHA256 e8a5f45ba9bdb38f5cb2c1b32affed1c6c1e7692de643ab5a3b67d485ed3a7ca，ENABLED 恢复。
- 实际生产库两项索引存在，schema=6；stocks 105 条/0.001409 秒，dc_indices 9290 条/0.119644 秒，均实际走索引。首轮含一次性建索引，共 100.897 秒 / 331 请求，completed_cycle，无错误。
- 本地报告：tushare-discovery-index-benchmark-20260917.json、tushare-discovery-index-live-20260917.json，位于 ~/Library/Application Support/QuantMind。
- 本地 QuantDB 自动刷新 PID 6859 正在将 snapshot-quantdb-20260916T195141891018Z 应用到沙盒，校验复制子进程 PID 16046 活跃；本地 API/research-worker 由该流程停用，不要提前启动或重跑刷新。业务 DB/Redis 保持运行。等待 PG/Qlib/派生结果完成并自动恢复后重新 handoff。
- 云端清理预检 unit quantmind-tushare-prune-check-20260917.service / PID 632645 仍运行，最近 1200000 文件 / 161929259711 逻辑字节，尚未 --apply。继续等待同一进程完成，不因暂时无输出重启。
