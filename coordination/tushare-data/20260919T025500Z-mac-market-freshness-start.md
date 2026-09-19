# 近期市场日历请求优先入队

接续 20260919T025400Z-mac-sw-daily-freshness.md。负责 backend/shared/tushare_market_contracts.py、backend/shared/tushare_pipeline.py、scripts/test_tushare_planning_progress.py。隔离 worktree /private/tmp/quantmind-market-freshness-20260919。

双端 handoff 已通过。复用既有 market 日期合同，独立生成最多七天的按日期请求，在有限快照规划前入队并提升未完成请求的优先级；不修改现有迭代器顺序或历史游标、不绕过权限/限速、不重新启用关闭的接口。验证大标的集合导致近期游标落后时新日期仍进入队列，重复调用幂等，禁用配置有效。
