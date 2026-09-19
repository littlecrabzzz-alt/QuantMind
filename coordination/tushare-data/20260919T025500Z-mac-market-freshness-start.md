# 近期市场日历请求优先入队

接续 20260919T025400Z-mac-sw-daily-freshness.md。负责 backend/shared/tushare_market_contracts.py、backend/shared/tushare_pipeline.py、scripts/test_tushare_planning_progress.py。隔离 worktree /private/tmp/quantmind-market-freshness-20260919。

双端 handoff 已通过。复用既有 market 日期合同，独立生成最多七天的按日期请求，在有限快照规划前入队并提升未完成请求的优先级；不修改现有迭代器顺序或历史游标、不绕过权限/限速、不重新启用关闭的接口。验证大标的集合导致近期游标落后时新日期仍进入队列，重复调用幂等，禁用配置有效。

## 已部署

实现 cc667ec0，93 项相关测试通过；两端 handoff 已通过 a2e3730c。旧 worker 自然完成后部署，恢复为 PID 45320。真实规划 161 项近期日期请求，新建 154 项；全部未完成规划游标无回退，market offset 6000→6500。

真实采集已取得 20260918 的基金份额、申万日线、可转债日线、期货日线/主力映射/结算参数/仓单数据；读取原始对象逐行核对 trade_date，无不匹配。完整证据见 docs/tushare-market-freshness-production-20260919.json。部分日期/交易所任务尚在队列，不声明七类全量已完成；既有历史及附件补采继续。
