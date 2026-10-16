# 归档硬链接保持与版本范围核对
- master509f6dba已推送；已确认云archives/1a593ee...json与对应releases/data-.../manifest.json同inode/nlink2，约60MB单例。原rsync -a不保留此关系，最终补传改-aHz，避免本地将清单别名重复占空间。
- 实际本地rsync夹具先造两份独立副本，再运行生产传输参数，验证恢复同inode；6项迁移/authority测试通过。持久迁移客户端已更新，正在运行的原传输不重启，最终sync-frozen应用-H。
- 云checkpoint PID253095持续active，inventory约213MB（观察值），无COMPLETE；原precopy与DB prestage任务仍运行。采集库暂存曾观察4.35GB/11.36GB，非完整。
- 离线对照Mac d5清单与冻结源58ed：已完成分区128495→147199，pending5708154→7331919，两者history_complete=false。范围扩大，不能把文件迁移成功当上游历史已采齐；旧版本完整保留。
- 旧完整项目快照不能拆删Tushare文件，否则破坏manifest。后续源清理后，现有delta快照会移除building中的消失路径并保留最新完整恢复点；本轮未触发会停写的整项目快照，没有改变QuantDB服务。
- 继续等三个原任务完成，补传/安装/验证/接管/本地采集，再完成生产缓存入口与旧研究固定输入核验。
