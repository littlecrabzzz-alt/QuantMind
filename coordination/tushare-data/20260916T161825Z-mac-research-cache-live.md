# Mac 供数与云缓存真实验收
- master 8b7270d1 已推送；本轮新增 guarded installer、本地解析器运行环境、8并发对象下载和15分钟定时器。6项相关测试通过。
- Mac 持久 runtime 已 prepare 成功，pypdf6.17.0与云端一致；独立0600凭据文件已准备，只含Tushare凭据，不在Git或日志。未激活采集，无所有权标记。
- 首次云端拉取于2026-09-17 00:16:29 CST成功：27453文件，585576737字节，来源d5c9b5、子集ca34d0。5个API：fund_daily/index_basic/index_daily/stock_basic/trade_cal。
- 临时unit成功退出后，安装启用tushare-research-cache.timer，实际再次运行成功，downloaded_files=0，upstream_calls=0。cloud quantmind容器用tushare_store.read_dataset从/data/tushare-research成功读stock_basic两行。
- Mac precopy PID61325/rsync61364仍存活，未冻结云端采集。全归档完整性尚未验证。
- Git已双端快进；整体handoff后续本地HTTP探针Connection refused，不把Git对齐当全服务通过。未改停本地业务服务或QuantDB。
- 剩余：应用Tushare读取入口切换、全量预复制完成后的冻结检查点/最终传输/完整校验、唯一采集节点切换及持续历史采集。云全量文件尚不清理。
