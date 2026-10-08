# 本地数据源恢复：空间保护解除与代码兼容修复

- 状态：进行中；接续 [恢复开工记录](20261008T134033Z-cloud-local-source-recovery-start.md)。
- 分支与候选：codex/data-sync-recovery-20261008，/root/data/disk/quantmind/worktrees/data-sync-recovery-20261008。本次修复已快进合入主工作树；相邻未提交文件未改动。
- 提交：15a340b1 修复QuantDB→PG缺失特征列；487be8c5 修复市场分析读取同类缺字段；84316ad1 本地采集前启动Docker并等待就绪。
- 缺失的历史 return_* 投影为NULL，保留现有字段映射，绝不使用 future_return_* 训练标签替代。历史分区有值时仍保留。
- 清理前完成最老登记回滚副本与完整快照的119692文件逐一SHA-256核验；按既有保留两版策略释放77,445,976,064字节。完整快照、原始归档、固定研究输入与两版登记备份保留。证据位于 data/maintenance/local-source-recovery-20261008/{redundant-backup-verification,backup-rotation}.json。
- Mac与云端本次三项源码SHA-256一致；Mac独立定时客户端仅更新已测Docker启动函数，保留已安装采集行为。原客户端备份于Mac ~/Library/Application Support/QuantMind/maintenance/local-source-recovery-20261008/local_market_source.py.before-docker-autostart。
- 隔离测试：PG流式/结果用例8项通过；市场快照schema/refresh与本地调度用例23项通过。临时代码位于Mac /tmp/quantmind-data-sync-recovery-tests-20261008，TMPDIR=/private/tmp/quantmind-recovery-test-tmp 避免macOS默认临时路径的symlink触发校验拒绝；未弱化安全规则，未连接供应商或业务数据库。
- 采集完成：10月8日本地QuantDB 17个数据集更新、6个已最新、0错误、5222文件下载。新源release market-fd1d7d9a239337dfb5a9182c7e1230159c980bfda1b49c9126bb9ca8045803cf，日线/technical/features目录截止10月8日，正在传送云端。
- 云端旧待应用release已成功补PG/Qlib到9月29日，继续补市场分析；新版本尚未宣称applied。Qlib原有除权事件缺行及factor回退警告继续保留，不代表历史/PIT齐全。
- Tushare云端缓存服务恢复运行，正在校验/下载 data-d96ae3c78968701e7327ee6422fdf8fd5ee02ae759b9fe28de1902a194626925；235080个缺失文件约2.06GB，不超过50GiB缓存预算，尚未切换CURRENT。
- 下一步：等待新版云端QuantDB回执与真实PG/Qlib/市场分析日期一致，核对BTC/ETH与Tushare完成和后续调度。本地沙盒后端当前停机，按既有规范延后应用，不为行情恢复启动研究或交易。
