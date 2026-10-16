# 冻结补传入口与研究子集扩展
- master5acec2a2已推送，sync-frozen先通过SSH验证暂停和COMPLETE，复用不可变文件补传，再传检查点/采集配置；保留CURRENT，无采集激活。8项迁移/worker/权限/安装测试通过。
- 云checkpoint PID253095仍活跃。实测主机31GiB内存、可用20.7GiB；原检查点2GiB上限顶满，经systemctl set-property --runtime将MemoryMax调为8GiB，PID不变、不重启任何服务。数据库副本仍处校验，COMPLETE尚未出现。
- 本地precopy PID61325/61364/61393从archives进入attachments阶段，仍实际写入PDF临时文件。
- Mac已预先校验12 API研究子集3a47d505：43145文件、1300651559字节、清单12369446字节；涵盖daily/index_daily/fund_daily/adj_factor/daily_basic/index_weight/ci_daily/sw_daily/stock_basic/index_basic/fund_basic/trade_cal。
- 等云缓存unit空闲后更新Mac source LaunchAgent为12 API，保持SSH隧道；启动同一受管cache service，PID282224（Type=oneshot activating是执行中）。需新增15692文件/722936377字节，已观察1100文件下载进度，尚未完成切换。
- 源端Tushare暂停标记保留，QuantDB及其他容器未停；Mac未接管采集。下一步继续观察原checkpoint/precopy/cache三个句柄，COMPLETE与文件复制成功后才能最终补传、安装、finalize、启动native worker并实测吞吐。
