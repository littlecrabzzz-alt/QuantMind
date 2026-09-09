# Realtime10 bounded tools 仓库化开始
- owner remaining_markets；独立 branch codex/tushare-realtime-probe-tools，worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-realtime-probe-tools，base master eed2c88。
- 仅新增 scripts/tushare_realtime_probe.py、scripts/verify_tushare_realtime_fixed.py、scripts/test_tushare_realtime_tools.py、docs/tushare-realtime-probe.md；不改 core/runtime/config/ledger 或其他用户文件。
- 复用已审 /tmp realtime10；改为当前 tiered_v1 resolved_api_rate+rollout account ceiling，持久 request_gates 与 pipeline.lock；默认 dry-run，15 calls/120s，无自动启用。
- 无源API、token读取、生产DB/config/队列改动、发布或重启；只隔离测试。父持有生产操作与共享handoff窗口，本任务不另发handoff。
