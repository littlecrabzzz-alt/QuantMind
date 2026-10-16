# 接管中断恢复保护
- master4ec7c39a已推送。finalize先写migration_verified=false/activation_pending=true，再写ENABLED，最后提交verified=true；authority在中间状态拒绝采集。相同owner/checkpoint重跑会重新校验并完成，不允许覆盖已完成所有权。
- 新增真实异常注入测试，模拟ENABLED已写但最终所有权提交前中断，重试成功；8项相关测试通过，持久Mac迁移脚本已更新。
- 原checkpoint PID253095持续active，尚无COMPLETE、清单尚未写满缓冲；数据库I/O和内存状态已核实，不把Result=success默认值当完成。原precopy仍实际写入不同PDF临时文件（已从52前缀推进66前缀），不重启。
- 云Tushare迁移暂停保持；Mac尚无采集权。继续等待原任务，完成后sync-frozen/install-checkpoint/finalize/activate和真实吞吐验收；仍需生产应用读取切换及旧固定研究输入保留核验。
