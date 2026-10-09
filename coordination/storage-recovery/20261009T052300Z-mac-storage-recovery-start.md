# 远端磁盘恢复与存储生命周期修复

- 用户已确认执行此前审查方案：清理失败备份、优化备份/接收/保留、日志与健康状态，并更新远端。
- 候选工作树：`/Users/lizeyu/.codex/worktrees/quantmind-storage-recovery-20261009`，分支 `codex/storage-recovery-20261009`，基线 `d87c01c0`。主树原有修改全部保留。
- 负责范围：`dual_node_snapshot.py`、`dual_node_inventory.py`、`local_market_source.py`、相关离线测试，以及日志失败退避、存储就绪检查、云端 Compose 日志配置和操作文档。
- 紧急操作：暂停完整快照 timer；在快照锁内仅移除缺少 COMPLETE、没有运行任务的 `.building`，保留 latest 和全部正式数据。记录保存在 VPS `/root/backups/quantmind-storage-recovery-20261009-1322/recovery.json`。
- 不恢复供应商云端采集，不启用研究、模拟或真实交易，不批量清理旧快照/数据库/其他应用文件。新保留规则只处理带新状态凭据的受管传输包；旧遗留版本另行核验。
- 验收：失败用例先行；隔离 Linux 数据复制与容量预检；发布前核对活动任务，按现有 cloud-compose 入口更新相关服务；验证数据、Redis 持久化、日志速率、磁盘与 HAPI。
