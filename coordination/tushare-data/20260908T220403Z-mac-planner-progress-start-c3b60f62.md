# 隔离规划游标修复候选开始
- remaining_markets / Mac；独立 codex/tushare-planner-progress 基线50ee715，worktree quantmind-tushare-other-markets；进行中。
- 仅拥有 backend/shared/tushare_pipeline.py 的 plan_extended 与紧邻规划helpers、新 scripts/test_tushare_planning_progress.py；不改publish/manifest、其他runtime或生产。父不占此块，text已释放。
- 接续 20260908T220226Z-mac-planner-global-reset-review-0b37f618.md。先做 family 依赖签名；复用现有 planning_state.signature TEXT 保存版本化有限发现快照，无SQLite schema迁移。未完扫不被单纯发现增长/跨日打断；完成后最新发现/日期启动补扫。recent独立于history完成，配置/合同真变更仍重规划；旧签名一次安全重扫，jobs幂等保留。
- 纯临时目录回退复现与回归测试，30分钟候选；不停止生产队列，不调用API、不读密钥。
