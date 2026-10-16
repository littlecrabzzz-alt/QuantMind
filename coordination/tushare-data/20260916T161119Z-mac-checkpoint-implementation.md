# 迁移校验实现进展
- master fa292c86 已推送，新增冻结检查点/完整文件哈希验收，4 项相关测试通过。云端新增脚本哈希已核对一致；整体 handoff 曾因其他源码差异拒绝对齐，未强制覆盖。
- 首轮 precopy 明确退出码30（120秒空闲超时），修复为不做预复制全盘 checksum、600秒超时，最终仍逐文件 SHA-256 验收。更新持久客户端后恢复，PID 61325，rsync 61364。
- 旧 com.quantmind.tushare-mirror 已 launchctl disable，防止下次登录重新并发写；QuantDB 定时器未改。
- 云研究缓存拉取 PID192662 仍 active，缓存由121M增长至231M，尚无完成标记。
- 尚未执行冻结、数据库检查点生产迁移或所有权切换。云 ENABLED 保留；Mac 不具备 ARCHIVE_AUTHORITY。下一步保持预复制，完成可重复部署、研究缓存调度/读取及最终停写迁移验收。
