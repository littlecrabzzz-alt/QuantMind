# 退出云端采集调度保护
- master6449494d已推送。Beat在启动时发现ARCHIVE_RELOCATED即移除Tushare continuation；执行真实schedule AST的测试验证authority未迁移仍派发、迁移后不派发、sandbox不派发，market-sync-dispatch/market-snapshot始终保留。没有提前重启Beat或停其他服务。
- Mac冻结数据库暂存中archive.sqlite与daily-quota.sqlite已逐项SHA256比对源清单通过；其余未传完不安装。prestage PID76276仍运行，precopy三原PID仍运行。
- 云checkpoint PID253095在完整文件清单阶段，inventory已增长至29.1MB（观察值），尚无COMPLETE。不要凭进程Result默认success认定结束。
- 继续等待三原任务。交接完成后再reload Beat并停止两个专用Tushare worker，保持QuantDB worker。未执行生产finalize，Mac无采集所有权，云全量仍保留。
