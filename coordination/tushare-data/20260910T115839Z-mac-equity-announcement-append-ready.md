# Tushare equity announcement append candidate ready

- 时间、节点、任务标识：20260910T115839Z，Mac，coverage_gap_audit
- 状态：待交接
- 分支、worktree：`codex/tushare-equity-announcement-append`，`/tmp/QuantMind-equity-announcement-append`
- 分工：补全市场三类公告历史追加规划；未修改/调用 index_weight、fund_nav、生产配置、权威数据或上游。

只读生产核对：249 命名能力、243 运行时任务 API、177 个当前启用 API。`history:equity_event` offset 175500/done0；`stk_holdernumber`、`stk_holdertrade`、`repurchase` 各 17 个任务。新 scope 精确计划 1323 个历史任务 identity，42 已存在，预计幂等新增 1281；每 API 最终 441 个窗口。旧 cursor/signature、任务行、限频/消费 group 均不变。

验证：Python3.10 专项及相邻 42 项通过；完整 `test_tushare*.py` 973 项通过、skipped5、48.531 秒，日志 SHA `960cf3fa69e1500adaa158fa24b237bd6aec0d61662ba2e16f7230f31ca1bf98`；Ruff、JSON、`git diff --check` 通过。机器证据 `docs/tushare-equity-announcement-append.evidence.json`。

下一步：集成人审查提交后合并；双端核对并让采集自然排空，只重启 Tushare 采集 worker。观察最多三轮 500-new-job 规划至 append done，再验收真实消费、固定发布和 Mac 离线镜像。`fund_share` 尾部饥饿与 `eco_cal` 单日饱和是下一顺位，未在本候选扩改。
