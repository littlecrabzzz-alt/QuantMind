# 主题：R01-P0.3 验收缺陷修复 AC-02/03/04/05（p03_execution F1E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-F1E1（wave F1 attempt 1）
- 状态：**done**（四项全修复+验收等价复跑 4/4 绿）
- 提交：`herdr/r01-p0` @ `6b6cab7cb3e6729b8d975197f5d9789a79d14d6d`（仅 owns 4 文件）
- 证据：`<run>/artifacts/p03/fixes-f1/`（before/repro.json、after/acceptance-equivalent.json、acceptance-rerun.log、README）

## 要点

1. **AC-02**：缺行情估值冻结政策——carry 最近有效市价+staleness（天数/来源日），连续缺日>5（可配）标 `valuation_reliable=false`；份额折算日 carry 价同比例换算；信号参考/_nav_with_bars 同政策；**独立复算自实现 carry**（只观察包行情）。真实缺日 159915 2021-02-08 复验：nav 不变、mark=3.084（成本 3.1029 不再使用）。
2. **AC-03**：checkpoint 恢复绑定完整冻结 config+合同版本（schema v3）；不匹配 `CheckpointConfigMismatch`（逐字段 diff）；缺绑定字段拒绝；PG 入口经 restore 强制；同参数续跑==不间断复测通过；AB-QUICKSTART"错参数取不到快照"表述已更正为"显式报错"。
3. **AC-04**：执行/入账层对终态订单幂等（重试不改现金/持仓/fills/费用/状态；卖光后重试不改写原成交）；同键异量 `SameKeyOrderConflict`；checkpoint 恢复后重试覆盖。
4. **AC-05**：约定执行时点价格缺失（0/None/NaN/inf）→ `MISSING_EXECUTION_PRICE` 拒单（账本枚举 stale_price），不隐式替代、无费用；open/close/vwap 模式全覆盖。

## 验证

- 全量回归 270 passed（新增 test_r01_f1.py 25 例）；ruff 全过；真实包 10 窗口 ALL_PASS 残差 0.0%；沙盒 PG checkpoint 11 项全 True。
- 原 independent_checks.py 本地实跑：import 期失败（AC-06 探针引用 p04 已删除的 readiness_passes，见 acceptance-rerun.log）；AC-02~05 按其断言逐字等价复跑 4/4 绿（after_rerun.py）；AC-01（分红 record-date 口径）为合同变更事项，非本任务。
