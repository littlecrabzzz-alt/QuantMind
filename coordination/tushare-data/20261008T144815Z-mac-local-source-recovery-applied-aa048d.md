# 本地数据源恢复：A股与BTC/ETH应用验收

- 状态：核心数据交付已恢复；Tushare后续发布版追平进行中。接续 [兼容修复记录](20261008T141634Z-cloud-local-source-recovery-fixes-8ace24.md)。
- 本次仍由Mac唯一采集，云端仅校验接收并更新派生数据；业务库、固定研究输入和实盘开关按原规则维护。
- A股源release market-fd1d7d9a239337dfb5a9182c7e1230159c980bfda1b49c9126bb9ca8045803cf，119736文件，云端22:37:04 applied。PG写入38990行、7个交易日、零失败批次；直接查询PG最大日、Qlib日历末日与市场分析快照均为2026-10-08。市场分析读取层有5个指数、80个申万板块、5209条全量股票资金流，板块及代表指数日期一致。
- BTC/ETH源release market-b263f3561812d7b43dbbb6315b6cbefdcb3754c127d46a57a8b44f761c5a9e3d，原始release binance-20261008T143725923368Z-39e3529bed；云端22:38:45 applied。两标的各3339条已收盘UTC日线，2017-08-17至2026-10-07，6678行，gaps/duplicates/unclosed均0；Qlib与两份H5完成。
- Tushare第一个研究缓存data-d96ae3c78968701e7327ee6422fdf8fd5ee02ae759b9fe28de1902a194626925补传235080个文件、2056255972字节，22:35:38 verified；读取逻辑有18个接口、upstream_calls=0。历史完整性及历史版本完整性仍为false。
- Tushare实际daily最大trade_date=20260930。已核实采集初始化窗口end=today-1；缓存trade_cal的20261001至20261007均is_open=0，本轮不计划20261008。与缓存发布于10月8日分别记录；下一日采集窗口才含10月8日，不将版本时间当行情截止日。
- 后续本地源data-99bed269d18aab55c3e395b66ec749a31295dab4e73fe96f645baeb91d4fdfb6已经准备研究子集data-e73852e72f56117dc338eed0f8b5e900ebcaa6ce478c6bb141633c0c50d4918c，私有供数返回source_lagged=false；正在用现有云端缓存服务追平该版。第二轮早先抓到准备中的旧子集，正确保留source_lagged=true，未把旧版冒充追平。
- 本地市场source/status.json中的retry_pending为开发沙盒后端停机，A与BC的cloud_release均已等于新source release；本地采集与云端交付并未失败，开发库下载保留待下次启动再应用。不为通过本地应用检查启动旧完整Compose或研究任务。
- bash scripts/dual-node.sh handoff --align-git cloud通过：7486个源码文件及全部content digest一致，两端HEAD=b471dee4，正式服务健康、云端端口与交易关闭约束通过。本地处于cloud-tunnel；旧完整快照无需为日常行情恢复强制下载。
- 安装后的Mac独立采集客户端Docker就绪检查在真实本机通过；既有15分钟补查及Tushare定时器保持启用。代码修复31项隔离用例通过，运行证据继续保存在云端data/maintenance/local-source-recovery-20261008。
- 下一步：确认新Tushare研究子集CURRENT与校验回执，登记最终状态并同步本次Git记录。
