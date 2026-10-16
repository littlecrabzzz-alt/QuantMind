# 冻结数据库安装就绪
- master 106b7022，保留并合并了并发任务的QuantDB恢复记录d3dd329c，无覆盖其工作。
- 新增install-checkpoint：校验SQLite备份哈希、占本地写锁、空间保留线、同文件复用、不同数据库或活跃SQLite边车文件拒绝覆盖。空state.sqlite3也纳入检查点。安装不发布CURRENT，不授予采集权。
- 本地worker对blocked/disabled/already_running不再误报完成。4项迁移/权限/worker测试通过；持久runtime两脚本已更新但未激活采集。
- 云现有pipeline-config核对保留10100分期限、独立权限、tiered_v1、500rpm、全队列配置；海外财报原先关闭未擅自打开。
- precopy PID61325/61364/61393仍在工作，lsof确认接收器正在写archives中的临时清单文件。尚未完成全文件复制，云采集保留，未冻结或清理数据。
- 下一步在precopy完成后执行最终停写、冻结检查点、补传/安装、完整校验与唯一采集节点切换。
