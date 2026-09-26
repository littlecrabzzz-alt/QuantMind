# 币安数据云端日更与验收完成

- 运行代码 `bd5f2782729a60db6210bc41e9b96d17a1f8df4f`，95项后端测试、2项前端调度测试、typecheck与生产构建通过。双端handoff已通过；后续仅补验收文档，无需再次重载服务。
- 云端BTC/ETH当前版本 `binance-20260926T052342682336Z-69ea91b2d8`，6654条UTC日线，2017-08-17至2026-09-25；manifest SHA256 `0793a67fdbb09c44e2e1f338057ccb607bb0320a9e52e645586a03649750ce15`。
- 08:15 Asia/Shanghai、days=5、daily_forward/instrument_detail、with_qlib=true 已通过认证API与页面保存；自然调度任务成功，数值合同全历史迁移成功，再次增量unchanged=true/revised_rows=0。其他市场配置未变。失败当日不自动重投。
- CURRENT、真实管理页与API、Qlib/H5和新固定数据任务版本一致；6654 H5行及14个真实Qlib样本通过。旧原始版本及旧固定任务保留。2236条数值差异全部归一化，原始十进制行情变化0，详见独立只读审计摘要。
- AAPLB仍为独立59行tokenized_equity_spot固定归档，未启用日更/研究；Mac沙盒保留首次固定版本，无Binance云端新版本自动回传。
- 云端API、通用market worker与web已更新，Mac后端已重载，最终健康检查通过。research-worker、research-agent、beat未重启。后端/前端crypto研究开关与实盘开关均关闭；未启动策略研究、回测或交易。
- 报告 `docs/binance-data-cloud-acceptance-20260926.md` / 同名JSON；操作和后续扩币/股票接入见 `docs/binance-data-operations.md`。云端运行证据 `/data/maintenance/binance-data-20260926/`，本机UI截图 `output/playwright/quantbc-*-20260926.png`。
- 本任务共享合并与服务发布窗口释放；保留其他任务的dirty worktree、配置和研究成果。
