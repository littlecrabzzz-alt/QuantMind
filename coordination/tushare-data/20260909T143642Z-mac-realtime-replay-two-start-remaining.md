# 相邻实时回放 2 API 纯候选

Mac remaining_markets，基线2233d3d，branch codex/tushare-realtime-replay，独立worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-realtime-replay。只新建 backend/shared/tushare_realtime_replay_contracts.py、scripts/test_tushare_realtime_replay_contracts.py、docs/tushare-realtime-replay-intake.md。

已读已存官方420/340：rt_idx_min_daily只有单指数当日开盘以来；rt_fut_min_daily独立输入表允许单合约ts_code/freq及可选date_str YYYY-MM-DD，原文“交易当日，支持回溯一天”，不能用today-1推断上一交易日/夜盘。复用已有18列共享输出及_source_codes/_epoch；默认off和当前快照，无历史回填。前一交易日必须另有当期实际来源与边界验证，否则保持gap。无registry/pipeline/store/mirror/生产修改、无上游请求。
