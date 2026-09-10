# RRG ETF 涨跌停日历证据候选完成

- 节点/分支/基线：Mac，`codex/rrg-calendar-evidence`，`3615bebae57d7e5fa9d6ae2a789433b267304d7b`；独立 worktree，不接触主工作树未提交文件。
- 固定发布版：`data-d54865a93b3468b2e6f4c03a6d60dbf85289e8219d87797a3478178d17cc16ab`，窗口 `20220901..20260901`。只读谱系快照包含 49 个原始根、1,462 个后代、780 个叶、25 个 `child_not_verified` 根和 53 个 `empty` 叶，快照 SHA256 `33401b8e060392a00a98e9a9e51475bfe553b3402c795045a858fe6edd2f1617`。
- 固定 SSE 日历证明 53/53 个空叶均为非开市窗口；其中固定生命周期代码日 0、剩余缺失代码日 0。25 个根的日期窗口可按 RRG 日历包络视为覆盖，但不修改生产任务状态，也不推断源端历史完整。
- 剩余 `etf_limit` 缺口为 74 个开市日生命周期代码日，其中月度执行缺口 1 个：`20260401 / SH560890`。这些缺口与空叶无重叠，仍需权威涨跌停/可交易性证据，不能用停牌假设补齐；RRG 继续 `blocked_data`。
- 工具新增可选、hash-pinned 的只读谱系输入，输出逐项 `etf-limit-missing-observations.jsonl`。无谱系时保持原审计行为；含开市日的空叶始终标为 `open_session_empty_unverified`。
- 安全边界：固定 reader 报告 `upstream_calls=0`、`credentials_accessed=false`；只读 SQLite 快照立即关闭；没有调用 Tushare、修改生产或发布 `CURRENT`。
- 验证：4 个专项 unittest 通过；Ruff 与 `git diff --check` 通过。实际报告、逐项缺口和输出 manifest 的 SHA256 分别为 `b569175e231e51e964208193d4de0f1761c1615c22da0fea4bd3a09b3d2b9c65`、`835890e23ef6bfb43e5e4678720802417c4d26e3a61d413bcea9265c4fc89ef1`、`2579201775903af139b92556292b08b38b2c8f04d84d206ccf48bad96141b233`。
