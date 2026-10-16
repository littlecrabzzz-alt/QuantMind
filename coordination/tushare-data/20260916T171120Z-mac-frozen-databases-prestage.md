# 数据库检查通过，先行传输冻结副本
- 原checkpoint PID253095已完成全部SQLite backup/integrity_check，流式inventory前31条中确认archive.sqlite74592256、daily-quota.sqlite20480、documents.sqlite2204909568、pipeline.sqlite11355754496、state.sqlite3=0均有通过哈希记录。清单增长至66168字节，正在扫描归档文件，尚无COMPLETE。
- 启动com.quantmind.tushare-checkpoint-prestage，PID76276，将上述已冻结且通过检查的备份文件从源checkpoint/databases/传到Mac同名.migration暂存目录。不是复制活跃源SQLite，不安装到本地根目录、不发布CURRENT、不授予采集权限。
- 本地全量precopy原PID61325/61364/61393仍运行，.migration被它排除，暂存不与它重叠；最终sync-frozen会复用这些已传数据库文件。
- 后续必须同时确认precopy、checkpoint-prestage两个launchd任务终止成功，以及云checkpoint整体COMPLETE完成，再启动sync-frozen；避免同时向相同暂存文件启动重复传输。
- 源端仅Tushare暂停，QuantDB与服务继续运行。所有权和ENABLED在Mac仍未启用，云源全量未删除。
