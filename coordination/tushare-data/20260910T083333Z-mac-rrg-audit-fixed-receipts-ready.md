# Tushare：RRG 固定版审计命名空间与回执修复待交接

- 时间、节点、任务标识：2026-09-10 08:33:33 UTC，Mac，rrg-audit-fixed-receipts
- 状态：待交接
- 分支、worktree、提交：`codex/rrg-audit-fixed-receipts`；`/Users/lizeyu/.codex/worktrees/quantmind-rrg-audit-fixed-receipts`；提交见本记录后续 Git 历史
- 分工：本分支只修改 RRG 固定版审计、回归测试、审计说明和脱敏证据；不修改采集 worker、生产数据或主工作树未提交文件
- 接续：更正旧审计对 `etf_limit` 为零及固定版无 `fund_div` 空回执的判断

本次完成：严格核对 `etf_limit` 的 `FUND:<source_ts_code>` 命名空间，转换为 RRG 前缀代码后比较；从固定 manifest 的逐任务状态和精确参数计算 `fund_div` 空回执，只为缺少事件和空回执的 ETF 生成候选任务。

验证：固定版 `data-d42bf11af1d9654c16e9a3382c17aae352f3c18b5d97b615bba6cedc32973aa5` 离线重跑仍为 `blocked_data`；19 项相邻单测、Ruff 检查和 `git diff --check` 通过。审计没有调用上游、读取凭据、写生产或自动入队。完整指标和哈希见 `docs/tushare-rrg-etf-window-audit-d42bf.evidence.json`。

下一步：集成人审查并合入主分支；本提交不能解除 PIT `known_at`、历史 ETF 行业映射、可交易性/开盘语义和 PCF 证据缺口。
