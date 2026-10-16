# 云端旧 Tushare 数据库验证排队

- 节点/范围：Mac 发起；仅旧云端 Tushare 归档的 11 个 SQLite 来源及冻结副本，不涉及 QuantDB、业务 PostgreSQL 或已发布完整备份。
- 源码：master 3d0cf857；本次为私有运维证据脚本，无业务代码修改。双端 handoff 已通过，6689 文件内容相同。
- 原始负载清理 unit quantmind-tushare-prune-apply-20260917 仍运行，PID 704312；保持原任务。实际可用空间已到 298 GiB。
- 数据库验证 unit quantmind-tushare-database-verify-20260917 当前 PID 749404：先比对 Mac 11 个冻结数据库的 SHA 收据与原 inventory，再等待现有清理释放锁，逐个只读 SQLite backup（含 WAL）并与 Mac 冻结件 SHA 比对。报告 SOURCE_DATABASES_VERIFIED.json 在旧云端 .migration/checkpoint-2026-09-16T16-34-47.667824+00-00 下。没有删除数据库。
- 首次验证进程因已有清理锁占用明确退出 1；随后修正为等待锁，确认终态后才重启验证。两次短暂 SSH 断连未触发采集或清理重启。
- 本地采集 PID 15419 正常。一次 0 请求周期后，下一周期实际 360 请求/83 秒，pending 从 7757031 降到 7756671。未对暂态现象进行无证据改码。
- 下一步：确认负载清理 terminal success，确认全部 11 个数据库 fresh backup 匹配后再决定源库/检查点副本精确释放；完整备份等正常轮转，不改 COMPLETE 快照内部内容。
