# Mac 全量归档迁移继续
- 分支 codex/mac-data-source，worktree /tmp/quantmind-mac-data-source，已推送 master 93bad491。
- 负责 scripts/tushare_archive_migrate.py、相关迁移测试与 docs/tushare-mac-source.md。继续补一致检查点和逐文件验收。
- 实际在运行：Mac com.quantmind.tushare-precopy PID 57300/rsync 57304；云 quantmind-mac-research-pull PID 192662。尚未完成迁移验收，无 ARCHIVE_AUTHORITY，云 ENABLED 保留。
- 保持 QuantDB、业务库、研究任务不变；预复制不复制活跃 SQLite，不删除源数据。
- 下一步：冻结窗口的数据库 backup、全文件清单校验与唯一采集者切换；未验收不清理云归档。
